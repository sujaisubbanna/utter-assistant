# Native Windows support

Status: **P1 landed — opt-in / experimental.** The native `utter/win32/**`
backends, the portable runner transport and a PowerShell bootstrap installer
(`install.ps1`) are in place; the settings GUI ships as an (unsigned) NSIS/MSI
bundle built on `windows-latest`. Windows is still an explicit non-goal in
`README.md` and `docs/TRUST.md`; this file tracks the path to change that.

## Shape

The **protocol/policy brain is already portable** (framing, `runner/rpc.py`,
streams, handles, policy + provenance, `utter/router/**`, `utter/executor.py`,
the model store). The hard work is the **"plant"**: the platform integrations.
Mirror the macOS pattern — a `utter/win32/**` tree behind `utter/platform.py`,
plus a native runner transport and an NSIS/MSI installer.

## What already landed (P0 groundwork)

- `utter/platform.py`: `WINDOWS` + `is_windows()`, `sys.platform`/`UTTER_PLATFORM`
  aliases. (PR #51)
- `assistant/deps.py`: no longer hard-crashes on Windows (`import grp` guarded);
  Windows branch reports `powershell`/`nvidia-smi`/`ollama` and marks native
  backends advisory.
- `assistant/util.py`: `%LOCALAPPDATA%\utter` / `%APPDATA%\utter` paths.
- `assistant/doctor.py`: platform-specific runner start hint.
- `tests/platform/test_windows_detection.py`.
- `utter/win32/**`: desktop context, clipboard, launch, inject, pointer, hotkey,
  STT/TTS and screenshot backends, all behind `utter/platform.py`.
- **DPI-aware capture** (P2 item, landed early): `utter/win32/dpi.py` makes the
  process per-monitor DPI-aware (see below).

## Installer (`install.ps1`)

A PowerShell 5.1+ bootstrap installer, the Windows analogue of `install.sh`.
It is warning-free on a stock Windows 10 1803+ (which ships `tar.exe`).

```powershell
# latest release
irm https://utter.sujaisubbanna.com/install.ps1 | iex

# or, from a checkout / download
powershell -ExecutionPolicy Bypass -File install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File install.ps1 -Version v0.4.13
powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
powershell -ExecutionPolicy Bypass -File install.ps1 -SkipGui
```

What it does, in order:

1. **Resolve the release** — `api.github.com/repos/<repo>/releases/latest`
   (authenticated with `GITHUB_TOKEN`/`GH_TOKEN` when set), falling back to the
   `releases/latest` HTML redirect (`MaximumRedirection 0` + `Location`) so a
   rate-limited API never blocks an install. `-Version` pins a tag; both
   `0.4.13` and `v0.4.13` are accepted.
2. **Core** — download `utter-core-<ver>.tar.gz` + `sha256sums.txt`, verify the
   sha256, and merge-extract into `%LOCALAPPDATA%\utter`
   (`$env:UTTER_PREFIX` overrides; `-Prefix` also works). The merge keeps the
   runner endpoint/token files that live beside the core.
3. **Agent venv** — `<core>\.venv-agent` from `py -3.12` (else `py -3`, else
   `python`), then CPU-first runtime deps: `PyYAML requests numpy sounddevice
   pywin32 uiautomation comtypes mss`. `pywhispercpp` / `faster-whisper` are
   optional; GPU STT additionally needs CUDA 12 + cuDNN.
4. **Scheduled Tasks** — per-user `utter-runner` and `utter.service`, created
   `ONLOGON` with `schtasks /Create ... /F` and enabled with `/Change /ENABLE`
   (see below).
5. **Config** — `%APPDATA%\utter\config.toml` from the shipped
   `config.default.toml`, only when absent (default STT `whisper_cpp` /
   `ggml-small.en.bin`).
6. **Settings GUI** — the release's Tauri Windows installer, matched flexibly
   from the release assets (`*-setup.exe` or `*.msi`; product name `utter`):
   NSIS runs with `/S`, MSI with `msiexec /i <file> /qn /norestart`. Verified
   against `sha256sums-windows-x64.txt` when present. `-SkipGui` skips it; when
   no installer exists it warns and continues.

`-DryRun` prints every download, extraction and command and changes nothing.
`-Uninstall` deletes the two Scheduled Tasks and the core tree, and keeps the
config.

### Scheduled Tasks

Both are **per-user tasks at logon**, not Windows services: UIA, synthetic
input and global hotkeys need an interactive desktop session, which Session 0
services do not have.

| Task | Command | Role |
| --- | --- | --- |
| `utter-runner` | `"<core>\.venv-agent\Scripts\python.exe" -m runner --config "<core>\config.runner.toml"` | plugin supervisor + trust boundary |
| `utter.service` | `"<core>\.venv-agent\Scripts\python.exe" -m utter.daemon` | voice/context daemon |

```powershell
schtasks /Run    /TN utter-runner        # start now (otherwise at next logon)
schtasks /Query  /TN utter-runner /V
schtasks /Delete /TN utter-runner /F
```

### Unsigned installers

The NSIS/MSI bundles are **not code-signed yet**: SmartScreen may warn
("Windows protected your PC" → *More info* → *Run anyway*) and the `.msi`
installer is not signature-verified by the bootstrap. `install.ps1` checks the
GUI hash against the release checksums when they are published. Code signing is
tracked under P2.

## DPI awareness

Windows virtualises coordinates for DPI-unaware processes, while `mss`
screenshots and the pointer APIs work in physical pixels. `utter/win32/dpi.py`
makes the process per-monitor DPI-aware before capture and before window
lookups:

- `ensure_dpi_aware()` tries `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`
  (Win10 1607+), then `SetProcessDPIAware()` (Vista+), then
  `SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)` via `shcore` (Win8.1+).
  It is idempotent (`E_ACCESS_DENIED` means "already set", e.g. by a manifest).
- It is **best-effort**: every failure is swallowed, it returns `False` and is a
  **no-op on non-Windows hosts**, so `utter/win32/**` still imports and the
  Linux/macOS test suites run unchanged.
- Called from `utter/win32/screenshot.py` (`capture_output`,
  `total_geometry`) and `utter/win32/desktop.py` (`_focused_window`,
  `_raw_windows`, `_list_monitors`).

## Runner transport & trust (the key decision)

`runner` uses AF_UNIX + `SO_PEERCRED` (+ `/proc/<pid>/exe`) for peer identity.
On Windows that does **not** port as-is:

- Python 3.12/3.14 on Windows do **not** expose `socket.AF_UNIX`, and `asyncio`
  has no `create_unix_server()` (CPython gh-77589).
- No `SO_PEERCRED` on native Win32 (only `SIO_AF_UNIX_GETPEERPID` for a peer PID).

**P0 choice (implemented):** **loopback TCP 127.0.0.1:<port> + mandatory token**
(or **named pipes** later) in an ACL'd per-user location, with `fd.pass`
disabled (`-32005`), plugins on stdio, and permissions reported **advisory** (no
sandbox). Named pipes (`GetNamedPipeClientProcessId` + token SID) are the P2
hardening path for real peer identity. Do **not** weaken `docs/TRUST.md`
invariant #5.

### P0 transport contract (landed)

- **Selection** — `runner/platform.py`: `UTTER_RUNNER_TRANSPORT=unix|tcp` overrides
  the platform default (`tcp` on Windows, `unix` otherwise); `runner.socket_transport`
  in the TOML does the same. The override lets Linux tests exercise the TCP path.
- **Endpoint** — the server binds `127.0.0.1:0` (kernel-assigned port) and writes
  `%LOCALAPPDATA%\utter\runner.endpoint` = `{"host":"127.0.0.1","port":N}` atomically
  (temp file + `os.replace`). This file *is* `default_socket_path()` on Windows, and
  the assistant reads it (`assistant/util.py: runner_sock_path()`).
- **Token** — `%LOCALAPPDATA%\utter\runner-token`, created with
  `secrets.token_urlsafe(32)` via `O_CREAT|O_EXCL` (mode `0600` best-effort). The
  actual protection is **NTFS ACL inheritance** from the per-user profile
  directory; `chmod` on Windows only toggles the read-only bit and is advisory.
  A config `[socket] token` wins and is persisted to the same file so clients
  discover it; otherwise a fresh token is generated once and reused.
- **Auth** — every TCP client is default-deny until it sends
  `runner.auth {token}`. `allow_same_uid` / `allow_binaries` are **never** grants
  over TCP (there is no `SO_PEERCRED`); config validation rejects them with a
  clear error and requires a token.
- **No `fd.pass`** — `SCM_RIGHTS` does not exist here; `fd.pass` returns
  `-32005`, the runner does not advertise `host.fd.pass@1`, and plugins may only
  use the **stdio** transport (config rejects `connect`/`listen`).
- **Unix is byte-identical** — same AF_UNIX socket, `0600`, `SO_PEERCRED` /
  `/proc/<pid>/exe`, `SCM_RIGHTS`; the TCP code paths are never taken when
  `transport_kind() == "unix"`.

## Dependencies (wheels)

A **CPU-only** Windows path is shippable from wheels alone on 3.12/3.14:
`pywhispercpp` (CPU wheel) or `faster-whisper`+`ctranslate2` (CPU),
`sounddevice` (PortAudio DLLs bundled), `numpy`, `uiautomation`+`comtypes`
(a11y), `mss` (capture), `pywin32` (clipboard), `comtypes` (SAPI TTS). GPU STT
is **not** wheels-only (`ctranslate2` needs system CUDA 12 + cuDNN;
`pywhispercpp` GPU needs a source build).

The **`windows` extra** (`pip install -e ".[windows]"`) pins the CPU-first
runtime set — `numpy`, `sounddevice`, `pywin32`, `uiautomation`, `comtypes`,
`mss`. Optional STT (`pywhispercpp`) is intentionally left out until a
`win_amd64`/cp312 wheel is confirmed, so the extra always installs cleanly.

The vision/planner inference provisioner (`scripts/install_inference.sh`,
`python -m assistant inference install`) is **not supported on Windows yet**:
the CLI exits 1 with `not supported on Windows yet`, so the settings UI can show
a clear message instead of a failed download. `assistant inference status`
still reports whether the model directories are complete.

## CI (`windows-latest`)

`.github/workflows/windows.yml` runs on a real Windows runner (independent of the
Linux `verify` job) whenever `runner/**`, `assistant/**`, `tests/platform/**`,
`pyproject.toml` or the workflow change. It installs `.[windows]` (falling back
to the explicit wheel list), then asserts Windows detection + path/dependency
seams, the loopback-TCP runner transport, a core import smoke test, and
`python -m assistant --version`. `python -m runner._selftest` does **not** run
there: its non-e2e suite uses Unix-only primitives (`os.memfd_create`,
`os.getuid`, `socketpair`+`SCM_RIGHTS`, `AF_UNIX`).

## Phases

- **P0** — voice→action, no GUI: platform plumbing (landed), the transport
  above, `utter/win32/{desktop,clipboard,launch,inject,pointer,hotkey}.py`,
  STT/TTS/screenshot branches, a `windows` extra, tests.
- **P1** — GUI + service + installer: `%LOCALAPPDATA%`/`%APPDATA%` everywhere,
  **per-user Scheduled Task** (Session 0 services cannot do UIA/input/hotkeys),
  GUI WASAPI/PowerShell ports, PowerShell/NSIS installer, CI `windows-latest`,
  microphone-consent UX. **Landed:** path plumbing, the `windows` extra,
  `install.ps1` (core + venv + Scheduled Tasks + config + GUI), the Tauri
  NSIS/MSI bundles and the `windows-latest` CI jobs.
- **P2** — depth + hardening: full UI Automation, named-pipe transport, optional
  Windows Speech backend, toasts/media integration, code signing. DPI-aware
  capture (below) landed early.

## Spikes to run first

1. Transport: localhost TCP + token vs named pipes (decides P0).
2. Wheel installability on a real Win11 VM (esp. `ctranslate2`/`sounddevice`).
3. `WH_KEYBOARD_LL` PTT without admin.
4. UI Automation tree quality without elevation.
5. Tauri NSIS/MSI + per-user Scheduled Task + a relocatable Python runtime.

## Risks

- Weaker trust boundary (no peer identity without named pipes); no sandbox.
- UIPI blocks input into **elevated** windows unless Utter is elevated (avoid).
- Per-monitor DPI: `dpi.py` removes the screenshot↔pointer mismatch, but a
  per-monitor mixed-DPI setup is still worth re-testing after display changes.
- Packaging a Python runtime plus CUDA deps into an MSI is heavy.
- The Windows GUI bundles are unsigned, so SmartScreen warns on install.
