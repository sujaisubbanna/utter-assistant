<#
.SYNOPSIS
    Bootstrap installer for utter on Windows (PowerShell 5.1+).

.DESCRIPTION
    Mirrors install.sh's Linux logic for Windows:

      1. resolve the newest GitHub Release tag (API, with GITHUB_TOKEN/GH_TOKEN,
         else the releases/latest HTML redirect -- never API-only);
      2. download utter-core-<ver>.tar.gz + sha256sums.txt, verify the sha256
         and extract the core into %LOCALAPPDATA%\utter (or $env:UTTER_PREFIX);
      3. create the agent venv at <core>\.venv-agent with py -3.12 / python and
         install the CPU-first `windows` extra (incl. pywhispercpp);
      4. pull the MANDATORY whisper.cpp STT model (ggml-small.en.bin) into the
         model store and verify it. This step cannot be skipped: a failure
         aborts the install (Windows STT does not work without it);
      5. register the per-user Scheduled Tasks utter-runner and utter.service;
      6. write %APPDATA%\utter\config.toml from the shipped default if absent;
      7. download and silently install the settings GUI (Tauri NSIS *-setup.exe
         with /S, else the .msi with msiexec /i <file> /qn).

    The runner + voice daemon run as Scheduled Tasks at logon, not as Session 0
    services: UIA/input/hotkeys need an interactive session.

.PARAMETER Version
    Release tag to install (default: latest). Both "0.4.13" and "v0.4.13" work.

.PARAMETER DryRun
    Print the plan and the commands; change nothing.

.PARAMETER Uninstall
    Remove the Scheduled Tasks and the core tree. The config is kept.

.PARAMETER SkipGui
    Do not download/install the settings GUI.

.PARAMETER Prefix
    Install root (default: %LOCALAPPDATA%\utter, or $env:UTTER_PREFIX).

.EXAMPLE
    irm https://utter.sujaisubbanna.com/install.ps1 | iex
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Version v0.4.13
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall

.NOTES
    The Windows installers (NSIS/MSI) are currently UNSIGNED. SmartScreen may
    warn; the hash is checked against the release sha256sums when available.
    STT is mandatory: install.ps1 always pulls and verifies the whisper.cpp
    ggml-small.en.bin model (no flag skips it) so voice works out of the box.
    Environment: UTTER_REPO, UTTER_VERSION, UTTER_BASE_URL (local testing),
    UTTER_PREFIX, UTTER_MODELS, GITHUB_TOKEN / GH_TOKEN.
#>
[CmdletBinding()]
param(
    [string]$Version = $env:UTTER_VERSION,
    [switch]$DryRun,
    [switch]$Uninstall,
    [switch]$SkipGui,
    [string]$Prefix = $env:UTTER_PREFIX
)

$ErrorActionPreference = 'Stop'
# Invoke-WebRequest's progress bar makes PS 5.1 downloads an order of magnitude
# slower; the installer prints its own progress instead.
$ProgressPreference = 'SilentlyContinue'
$Script:Repo = if ($env:UTTER_REPO) { $env:UTTER_REPO } else { 'sujaisubbanna/utter-assistant' }
$Script:Ver = ''
$Script:VerNum = ''
$Script:BaseUrl = ''
$Script:Tar = $null

if (-not $Prefix) {
    $localAppData = [Environment]::GetFolderPath('LocalApplicationData')
    $Prefix = Join-Path $localAppData 'utter'
}
$Prefix = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Prefix))
$Script:Core = $Prefix
$Script:Venv = Join-Path $Prefix '.venv-agent'
$Script:VenvPython = Join-Path $Script:Venv 'Scripts\python.exe'
$Script:RunnerConfig = Join-Path $Prefix 'config.runner.toml'
$Script:AppData = [Environment]::GetFolderPath('ApplicationData')
$Script:ConfigDir = Join-Path $Script:AppData 'utter'
$Script:ConfigFile = Join-Path $Script:ConfigDir 'config.toml'
$Script:Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('utter-install-' + [guid]::NewGuid().ToString('N').Substring(0, 8))

# Mandatory Windows STT: whisper.cpp (pywhispercpp, CPU-first) + its ggml model.
# The model is pinned by size and content sha256; install.ps1 fails loudly if it
# cannot be pulled and verified. There is deliberately no skip flag.
$Script:WhisperModelSource = 'hf:ggerganov/whisper.cpp:ggml-small.en.bin'
$Script:WhisperModelName   = 'whisper.cpp'
$Script:WhisperModelSha256 = 'c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d'
$Script:WhisperModelBytes  = 487614201

# --------------------------------------------------------------------------- #
# output helpers -- fixed short tokens, no silent failures
# --------------------------------------------------------------------------- #
function Write-Info([string]$Message) { Write-Host "  $Message" }
function Write-Ok([string]$Message)   { Write-Host "  [ok] $Message" -ForegroundColor Green }
function Write-Note([string]$Message) { Write-Host "  note: $Message" -ForegroundColor DarkGray }
function Write-Warn([string]$Message) { Write-Host "  WARNING: $Message" -ForegroundColor Yellow }
function Write-Section([string]$Title) { Write-Host ""; Write-Host "== $Title ==" -ForegroundColor Cyan }

function Fail([string]$Message) {
    # Throw so callers (e.g. optional GUI checksum fetch) can catch; Main's
    # top-level try/catch prints once and exits non-zero.
    throw [System.Exception]::new($Message)
}

function Invoke-Native {
    # Run a native command, surface its output only on failure, and throw when
    # it exits non-zero (unless -AllowFailure). Returns the exit code.
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )
    Write-Verbose ("+ {0} {1}" -f $FilePath, ($Arguments -join ' '))
    $output = & $FilePath @Arguments 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        foreach ($line in @($output)) { if ($line) { Write-Host "    $line" } }
        if (-not $AllowFailure) {
            Fail "$FilePath exited with code $code"
        }
    }
    return [int]$code
}

# --------------------------------------------------------------------------- #
# release resolution
# --------------------------------------------------------------------------- #
function Normalize-Tag([string]$Value) {
    if ($Value -match '^v') { return $Value }
    return "v$Value"
}

function Get-GitHubHeaders {
    $headers = @{ 'User-Agent' = 'utter-installer' }
    # GITHUB_TOKEN wins, then GH_TOKEN (same precedence as install.sh).
    $token = if ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN } elseif ($env:GH_TOKEN) { $env:GH_TOKEN } else { '' }
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    return $headers
}

function Get-TagFromRedirect {
    # releases/latest is an HTML 302 to .../releases/tag/<tag>. It has no API
    # quota, so it is the fallback when the unauthenticated API 403s.
    $url = "https://github.com/$($Script:Repo)/releases/latest"
    $location = ''
    try {
        $resp = Invoke-WebRequest -Uri $url -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop
        $location = [string]$resp.Headers.Location
    }
    catch {
        $response = $_.Exception.Response
        if ($response) {
            try { $location = [string]$response.Headers['Location'] } catch { $location = '' }
            if (-not $location) {
                try { $location = [string]$response.Headers.Location } catch { $location = '' }
            }
        }
    }
    if ($location -and ($location -match '/releases/tag/([^/?#\s]+)')) {
        return $Matches[1]
    }
    return ''
}

function Get-LatestTag {
    $api = "https://api.github.com/repos/$($Script:Repo)/releases/latest"
    $tag = ''
    try {
        $resp = Invoke-RestMethod -Uri $api -Headers (Get-GitHubHeaders) -TimeoutSec 30
        if ($resp -and $resp.tag_name) { $tag = [string]$resp.tag_name }
    }
    catch {
        Write-Verbose "GitHub API lookup failed: $($_.Exception.Message)"
    }
    if (-not $tag) {
        $tag = Get-TagFromRedirect
    }
    return $tag
}

function Resolve-Release {
    if ($env:UTTER_BASE_URL) {
        if (-not $Version -or $Version -eq 'latest') {
            Fail "UTTER_BASE_URL is set but -Version latest; pass -Version <ver>"
        }
        $Script:BaseUrl = $env:UTTER_BASE_URL.TrimEnd('/')
        $Script:Ver = Normalize-Tag $Version
    }
    elseif (-not $Version -or $Version -eq 'latest') {
        if ($DryRun) {
            $Script:Ver = '<latest>'
        }
        else {
            Write-Info "querying: https://github.com/$($Script:Repo)/releases/latest"
            $tag = Get-LatestTag
            if (-not $tag) { Fail "could not resolve the latest release for $($Script:Repo)" }
            $Script:Ver = $tag
        }
        $Script:BaseUrl = "https://github.com/$($Script:Repo)/releases/download/$($Script:Ver)"
    }
    else {
        $Script:Ver = Normalize-Tag $Version
        $Script:BaseUrl = "https://github.com/$($Script:Repo)/releases/download/$($Script:Ver)"
    }
    $Script:VerNum = $Script:Ver -replace '^v', ''
}

function Get-ReleaseAssets {
    # Release assets as @{ Name; Url }, via the API then the HTML asset list.
    # Empty when both are unavailable (the caller then tries the known names).
    param([string]$Tag)
    $assets = @()
    $api = "https://api.github.com/repos/$($Script:Repo)/releases/tags/$Tag"
    try {
        $resp = Invoke-RestMethod -Uri $api -Headers (Get-GitHubHeaders) -TimeoutSec 30
        foreach ($a in @($resp.assets)) {
            $assets += [pscustomobject]@{ Name = [string]$a.name; Url = [string]$a.browser_download_url }
        }
    }
    catch {
        Write-Verbose "asset API lookup failed: $($_.Exception.Message)"
    }
    if ($assets.Count -eq 0) {
        # expanded_assets is the no-JS asset list GitHub serves on the release
        # page; no API quota.
        try {
            $page = "https://github.com/$($Script:Repo)/releases/expanded_assets/$Tag"
            $resp = Invoke-WebRequest -Uri $page -UseBasicParsing -TimeoutSec 30
            $needle = [regex]::Escape("/releases/download/$Tag/")
            foreach ($m in [regex]::Matches($resp.Content, 'href="[^"]*' + $needle + '([^"?]+)"')) {
                $name = [uri]::UnescapeDataString($m.Groups[1].Value)
                $assets += [pscustomobject]@{ Name = $name; Url = "$($Script:BaseUrl)/$name" }
            }
        }
        catch {
            Write-Verbose "asset page lookup failed: $($_.Exception.Message)"
        }
    }
    return $assets
}

# --------------------------------------------------------------------------- #
# download + verify
# --------------------------------------------------------------------------- #
function Save-Download {
    param([string]$Url, [string]$Dest)
    if ($DryRun) {
        Write-Info "  [dry-run] download $Url"
        return
    }
    Write-Info "  [get] $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing -TimeoutSec 600
    }
    catch {
        Fail "download failed: $Url ($($_.Exception.Message))"
    }
}

function Get-ExpectedHash {
    # Pull one asset's sha256 out of a "<hash>  <name>" (or "*<name>"/"./name")
    # checksums file. Returns $null when the file or entry is missing.
    param([string]$SumsFile, [string]$Asset)
    if (-not (Test-Path -LiteralPath $SumsFile)) { return $null }
    foreach ($line in Get-Content -LiteralPath $SumsFile) {
        if ($line -match '^\s*([0-9a-fA-F]{64})\s+(.+?)\s*$') {
            $hash = $Matches[1].ToLower()
            $name = $Matches[2].TrimStart('*')
            $name = $name -replace '^\./', ''
            $name = $name -replace '.*[\\/]', ''
            if ($name -eq $Asset) { return $hash }
        }
    }
    return $null
}

function Assert-Hash {
    param(
        [string]$File,
        [string]$SumsFile,
        [string]$Asset,
        [switch]$Optional
    )
    if ($DryRun) {
        Write-Info "  [dry-run] verify sha256 of $Asset"
        return
    }
    $want = Get-ExpectedHash -SumsFile $SumsFile -Asset $Asset
    if (-not $want) {
        if ($Optional) {
            Write-Warn "no checksum for $Asset in $(Split-Path -Leaf $SumsFile); skipping verification"
            return
        }
        Fail "missing checksum for $Asset in $(Split-Path -Leaf $SumsFile)"
    }
    $got = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLower()
    if ($want -ne $got) {
        Fail "sha256 mismatch for $Asset`: want $want got $got"
    }
    Write-Ok "sha256 $($got.Substring(0, 16))... $Asset"
}

function Get-TarExe {
    if ($Script:Tar) { return $Script:Tar }
    $cmd = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command tar -ErrorAction SilentlyContinue }
    if (-not $cmd) {
        Fail "tar.exe not found; Windows 10 1803+ (which ships bsdtar) is required"
    }
    $Script:Tar = $cmd.Source
    return $Script:Tar
}

# --------------------------------------------------------------------------- #
# core + venv
# --------------------------------------------------------------------------- #
function Install-Core {
    Write-Section "install core (runner + CLI)"
    New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
    $tarballName = "utter-core-$($Script:VerNum).tar.gz"
    $sumsName = 'sha256sums.txt'
    $tarball = Join-Path $Script:Tmp $tarballName
    $sums = Join-Path $Script:Tmp $sumsName

    Save-Download "$($Script:BaseUrl)/$tarballName" $tarball
    Save-Download "$($Script:BaseUrl)/$sumsName" $sums
    Assert-Hash -File $tarball -SumsFile $sums -Asset $tarballName

    if ($DryRun) {
        Write-Info "  [dry-run] extract $tarballName -> $Prefix"
        return
    }

    $tar = Get-TarExe
    $stage = Join-Path $Script:Tmp 'extract'
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    & $tar -xzf $tarball -C $stage
    if ($LASTEXITCODE -ne 0) { Fail "could not extract $tarballName (tar exit $LASTEXITCODE)" }
    $top = Get-ChildItem -LiteralPath $stage -Directory | Select-Object -First 1
    if (-not $top) { Fail "core tarball has no top-level directory" }
    # Merge into the prefix rather than replacing it: the runner's endpoint and
    # token live at %LOCALAPPDATA%\utter and must survive an upgrade.
    foreach ($item in Get-ChildItem -LiteralPath $top.FullName -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $Prefix -Recurse -Force
    }
    Write-Ok "extracted core -> $Prefix"
}

function Get-BasePython {
    # Prefer `py -3.12` (the interpreter the release targets), then any py -3,
    # then plain python. Returns @{ Exe; Args } or $null.
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in @('-3.12', '-3')) {
            $null = & $py.Source $v -c 'import sys' 2>&1
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{ Exe = $py.Source; Args = @($v) }
            }
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    if ($python) {
        return [pscustomobject]@{ Exe = $python.Source; Args = @() }
    }
    return $null
}

function Install-AgentVenv {
    Write-Section "create the agent venv"
    $base = Get-BasePython
    if (-not $base) {
        Fail "no Python 3.12+ found; install it from python.org (tick 'Add python.exe to PATH') or the Microsoft Store"
    }
    Write-Info "  base python: $($base.Exe) $($base.Args -join ' ')"

    if ($DryRun) {
        Write-Info "  [dry-run] $($base.Exe) $($base.Args -join ' ') -m venv `"$($Script:Venv)`""
        Write-Info "  [dry-run] $($Script:VenvPython) -m pip install `"$($Script:Core)[windows]`""
        return
    }

    if (-not (Test-Path -LiteralPath $Script:VenvPython)) {
        $arguments = @($base.Args) + @('-m', 'venv', $Script:Venv)
        Invoke-Native -FilePath $base.Exe -Arguments $arguments
    }
    # Install the CPU-first `windows` extra from the extracted core. It is the
    # single source of truth for the runtime set and now includes pywhispercpp,
    # so this is mandatory (a failure aborts the install rather than degrading).
    Invoke-Native -FilePath $Script:VenvPython -Arguments @(
        '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
        "$($Script:Core)[windows]"
    )
    Write-Ok "installed the Windows runtime (`windows` extra, incl. pywhispercpp) into $($Script:Venv)"
}

# --------------------------------------------------------------------------- #
# mandatory whisper.cpp STT model
# --------------------------------------------------------------------------- #
function Verify-WhisperModel {
    # True when $Path is the pinned ggml blob: exact size and content sha256.
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        if ((Get-Item -LiteralPath $Path).Length -ne $Script:WhisperModelBytes) { return $false }
        $got = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
    }
    catch {
        return $false
    }
    return ($got -eq $Script:WhisperModelSha256)
}

function Test-WhisperModel {
    # Idempotency probe: the pinned blob is already in the store and verifies.
    # Queries `assistant models show` so a UTTER_MODELS override (or the legacy
    # store) is honoured without hard-coding a path. Never throws; $false means
    # "pull it".
    if (-not (Test-Path -LiteralPath $Script:VenvPython)) { return $false }
    $raw = & $Script:VenvPython -m assistant models show $Script:WhisperModelName --json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $false }
    try {
        $data = ($raw | Out-String) | ConvertFrom-Json
    }
    catch {
        return $false
    }
    foreach ($entry in @($data.models)) {
        foreach ($f in @($entry.files)) {
            if ($f.sha256 -ne $Script:WhisperModelSha256) { continue }
            if (Verify-WhisperModel -Path $f.path) { return $true }
        }
    }
    return $false
}

function Install-WhisperModel {
    # MANDATORY: Windows STT is whisper.cpp only. There is no flag that skips
    # this, and any failure is fatal.
    Write-Section "whisper.cpp STT model (mandatory)"
    if ($DryRun) {
        Write-Info "  [dry-run] $($Script:VenvPython) -m assistant models pull $($Script:WhisperModelSource)"
        Write-Info "  [dry-run] require $($Script:WhisperModelBytes) bytes sha256 $($Script:WhisperModelSha256)"
        return
    }
    if (Test-WhisperModel) {
        Write-Ok "whisper.cpp model already present and verified"
        return
    }
    Write-Info "  pulling $($Script:WhisperModelSource) (resumable, ~$([math]::Round($Script:WhisperModelBytes / 1MB)) MiB)"
    $code = Invoke-Native -FilePath $Script:VenvPython -Arguments @(
        '-m', 'assistant', 'models', 'pull', $Script:WhisperModelSource
    ) -AllowFailure
    if ($code -ne 0) {
        Fail "mandatory whisper.cpp model download failed (exit $code): $($Script:WhisperModelSource). Windows STT cannot work without it."
    }
    if (-not (Test-WhisperModel)) {
        Fail "mandatory whisper.cpp model is missing or failed verification (sha256 $($Script:WhisperModelSha256)): $($Script:WhisperModelSource)"
    }
    Write-Ok "whisper.cpp model verified (sha256 $($Script:WhisperModelSha256.Substring(0, 16))...)"
}

# --------------------------------------------------------------------------- #
# scheduled tasks
# --------------------------------------------------------------------------- #
function Install-ScheduledTask {
    param([string]$Name, [string]$Command)
    # ONLOGON per-user task: the runner/daemon need the interactive session for
    # UIA/input/hotkeys, which Session 0 services cannot do.
    if ($DryRun) {
        Write-Info "  [dry-run] schtasks /Create /SC ONLOGON /TN $Name /TR `"$Command`" /F"
        Write-Info "  [dry-run] schtasks /Change /TN $Name /ENABLE"
        return
    }
    Invoke-Native -FilePath 'schtasks.exe' -Arguments @(
        '/Create', '/SC', 'ONLOGON', '/TN', $Name, '/TR', $Command, '/F'
    )
    Invoke-Native -FilePath 'schtasks.exe' -Arguments @('/Change', '/TN', $Name, '/ENABLE')
    Write-Ok "scheduled task $Name (at logon, enabled)"
}

function Install-ServiceTasks {
    Write-Section "register scheduled tasks"
    $runnerTr = '"{0}" -m runner --config "{1}"' -f $Script:VenvPython, $Script:RunnerConfig
    $daemonTr = '"{0}" -m utter.daemon' -f $Script:VenvPython
    Install-ScheduledTask -Name 'utter-runner' -Command $runnerTr
    Install-ScheduledTask -Name 'utter.service' -Command $daemonTr
}

# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
function Install-Config {
    Write-Section "config"
    if (Test-Path -LiteralPath $Script:ConfigFile) {
        Write-Note "keeping existing $($Script:ConfigFile) (not overwritten)"
        return
    }
    $src = Join-Path $Prefix 'config.default.toml'
    if (-not (Test-Path -LiteralPath $src)) {
        if ($DryRun) {
            Write-Info "  [dry-run] copy <core>\config.default.toml -> $($Script:ConfigFile)"
            return
        }
        Write-Warn "config.default.toml not found in the core tree; skipping config"
        return
    }
    if ($DryRun) {
        Write-Info "  [dry-run] copy $src -> $($Script:ConfigFile)"
        return
    }
    New-Item -ItemType Directory -Force -Path $Script:ConfigDir | Out-Null
    Copy-Item -LiteralPath $src -Destination $Script:ConfigFile -Force
    Write-Ok "wrote $($Script:ConfigFile) (STT whisper_cpp / ggml-small.en.bin)"
}

# --------------------------------------------------------------------------- #
# settings GUI (Tauri NSIS / MSI)
# --------------------------------------------------------------------------- #
function Test-UrlExists([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -TimeoutSec 20
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Select-GuiInstaller {
    # Prefer the NSIS *-setup.exe (/S), else the WiX .msi (/qn). Asset names are
    # matched flexibly from the release listing, then the known names are tried.
    # Returns @{ Kind = 'nsis'|'msi'; Name; Url } or $null.
    $candidates = @()

    if (-not $env:UTTER_BASE_URL -and -not $DryRun) {
        # -DryRun stays offline: asset lookup needs a network call, and the
        # known release names below are enough to print the plan.
        $assets = Get-ReleaseAssets -Tag $Script:Ver
        $exe = @($assets | Where-Object { $_.Name -match '(?i)setup\.exe$' })
        if ($exe.Count -eq 0) {
            $exe = @($assets | Where-Object { $_.Name -match '(?i)\.exe$' -and $_.Name -match '(?i)utter' })
        }
        if ($exe.Count -gt 0) {
            $pick = @($exe | Where-Object { $_.Name -match '(?i)x64|amd64' }) | Select-Object -First 1
            if (-not $pick) { $pick = $exe | Select-Object -First 1 }
            $candidates += [pscustomobject]@{ Kind = 'nsis'; Name = $pick.Name; Url = $pick.Url }
        }
        $msi = @($assets | Where-Object { $_.Name -match '(?i)\.msi$' })
        if ($msi.Count -gt 0) {
            $pick = @($msi | Where-Object { $_.Name -match '(?i)x64|amd64' }) | Select-Object -First 1
            if (-not $pick) { $pick = $msi | Select-Object -First 1 }
            $candidates += [pscustomobject]@{ Kind = 'msi'; Name = $pick.Name; Url = $pick.Url }
        }
    }

    if ($candidates.Count -eq 0) {
        # Known names from the release workflow (productName is "utter").
        $candidates = @(
            [pscustomobject]@{
                Kind = 'nsis'
                Name = "utter-gui_$($Script:VerNum)_x64-setup.exe"
                Url = "$($Script:BaseUrl)/utter-gui_$($Script:VerNum)_x64-setup.exe"
            },
            [pscustomobject]@{
                Kind = 'msi'
                Name = "utter-gui_$($Script:VerNum)_x64.msi"
                Url = "$($Script:BaseUrl)/utter-gui_$($Script:VerNum)_x64.msi"
            }
        )
    }

    foreach ($candidate in $candidates) {
        if ($DryRun -or (Test-UrlExists $candidate.Url)) {
            return $candidate
        }
    }
    return $null
}

function Install-Gui {
    if ($SkipGui) {
        Write-Note "GUI skipped (-SkipGui)"
        return
    }
    Write-Section "install settings GUI"
    $gui = Select-GuiInstaller
    if (-not $gui) {
        Write-Warn "no Windows GUI installer (*-setup.exe / *.msi) found in release $($Script:Ver); skipping"
        return
    }
    Write-Info "  found: $($gui.Name)"

    $file = Join-Path $Script:Tmp $gui.Name
    Save-Download $gui.Url $file

    # Verify against sha256sums-windows-x64.txt when the release ships it.
    # A mismatch is fatal; a missing checksums file is only a warning.
    $guiSums = Join-Path $Script:Tmp 'sha256sums-windows-x64.txt'
    $haveSums = $false
    if (-not $DryRun) {
        try {
            Save-Download "$($Script:BaseUrl)/sha256sums-windows-x64.txt" $guiSums
            $haveSums = $true
        }
        catch {
            Write-Warn "could not fetch sha256sums-windows-x64.txt: $($_.Exception.Message)"
        }
    }
    if ($haveSums) {
        Assert-Hash -File $file -SumsFile $guiSums -Asset $gui.Name -Optional
    }

    if ($DryRun) {
        if ($gui.Kind -eq 'nsis') {
            Write-Info "  [dry-run] & `"$file`" /S"
        }
        else {
            Write-Info "  [dry-run] msiexec /i `"$file`" /qn /norestart"
        }
        return
    }

    if ($gui.Kind -eq 'nsis') {
        $proc = Start-Process -FilePath $file -ArgumentList '/S' -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            Fail "GUI installer exited with code $($proc.ExitCode)"
        }
    }
    else {
        $proc = Start-Process -FilePath 'msiexec.exe' `
            -ArgumentList @('/i', $file, '/qn', '/norestart') -Wait -PassThru
        if ($proc.ExitCode -notin @(0, 3010)) {
            Fail "msiexec exited with code $($proc.ExitCode)"
        }
    }
    Write-Ok "installed the settings GUI"
    Write-Warn "the Windows installers are unsigned; SmartScreen may warn (choose 'More info' > 'Run anyway')"
}

# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #
function Uninstall-Utter {
    Write-Section "uninstall"
    Write-Info "This removes:"
    Write-Info "  scheduled tasks  utter-runner, utter.service"
    Write-Info "  core + venv      $Prefix"
    Write-Info "This keeps your config: $($Script:ConfigFile)"
    Write-Host ""

    if ($DryRun) {
        Write-Info "  [dry-run] schtasks /Delete /TN utter-runner /F"
        Write-Info "  [dry-run] schtasks /Delete /TN utter.service /F"
        Write-Info "  [dry-run] remove $Prefix"
        return
    }

    foreach ($name in @('utter-runner', 'utter.service')) {
        $code = Invoke-Native -FilePath 'schtasks.exe' `
            -Arguments @('/Delete', '/TN', $name, '/F') -AllowFailure
        if ($code -eq 0) { Write-Ok "removed scheduled task $name" }
        else { Write-Note "scheduled task $name not present" }
    }
    if (Test-Path -LiteralPath $Prefix) {
        Remove-Item -LiteralPath $Prefix -Recurse -Force
        Write-Ok "removed $Prefix"
    }
    else {
        Write-Note "not present: $Prefix"
    }
    Write-Note "your config at $($Script:ConfigFile) was kept"
}

# --------------------------------------------------------------------------- #
# banner + summary
# --------------------------------------------------------------------------- #
function Write-Banner {
    Write-Host ""
    Write-Host "  utter installer" -ForegroundColor Yellow -NoNewline
    Write-Host " | Windows | $($Script:Ver)"
    Write-Host "  ------------------------------------------------------------"
}

function Write-Summary {
    Write-Section "done"
    Write-Host "  Installed utter $($Script:Ver) into $Prefix" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Services (Scheduled Tasks, run at logon):"
    Write-Host "    utter-runner   python -m runner --config $($Script:RunnerConfig)"
    Write-Host "    utter.service  python -m utter.daemon"
    Write-Host ""
    Write-Host "  Next steps:"
    if (-not $SkipGui) {
        Write-Host "    1. Open 'utter' from the Start menu (first-run wizard)."
    }
    Write-Host "    2. Start the services now (or sign out and back in):"
    Write-Host "         schtasks /Run /TN utter-runner"
    Write-Host "         schtasks /Run /TN utter.service"
    Write-Host "    3. Config: $($Script:ConfigFile)"
    Write-Host "    4. Check the install:"
    Write-Host "         & `"$($Script:VenvPython)`" -m runner --check-config --config `"$($Script:RunnerConfig)`""
    Write-Host "    5. Uninstall:"
    Write-Host "         powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall"
}

function Main {
    if ($Uninstall) {
        Uninstall-Utter
        return
    }

    New-Item -ItemType Directory -Force -Path $Script:Tmp | Out-Null
    Resolve-Release
    Write-Banner
    Write-Info "  release: $($Script:Ver)"
    Write-Info "  prefix:  $Prefix"
    Write-Info "  config:  $($Script:ConfigFile)"
    if ($DryRun) { Write-Info "  mode:    dry run (nothing is changed)" }

    Install-Core
    Install-AgentVenv
    Install-WhisperModel
    Install-ServiceTasks
    Install-Config
    Install-Gui

    if ($DryRun) {
        Write-Section "done"
        Write-Host "  Dry run complete. Re-run without -DryRun to apply."
    }
    else {
        Write-Summary
    }
}

try {
    Main
}
catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (Test-Path -LiteralPath $Script:Tmp) {
        Remove-Item -LiteralPath $Script:Tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
