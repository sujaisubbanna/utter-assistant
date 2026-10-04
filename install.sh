#!/usr/bin/env bash
# utter bootstrap installer — interactive step-by-step wizard + curl | bash.
#
#   curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
#   curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes
#
# In a terminal this is an interactive wizard: it walks every component and asks
# whether you want it (showing what it is, its size, whether sudo is needed, and
# what was detected on this machine). With --yes it accepts the recommended
# defaults non-interactively. Piped with no --yes it prints the plan and exits
# without changing anything.
#
# Every download is verified against sha256sums.txt from the GitHub Release.
#
#  3. add it to the requested locale list in docs/TRANSLATING.md.
#  4. no code change is needed.
#
# Environment:
#   UTTER_INSTALL_LANG  force the installer's UI language (e.g. de, de-DE, zh)
#   UTTER_REPO      GitHub repo "owner/name" (default: sujaisubbanna/utter-assistant)
#   UTTER_VERSION   release tag (default: latest)
#   UTTER_BASE_URL  override the download base (default: GitHub Releases;
#                       set to http://127.0.0.1:PORT for local testing)
#   PREFIX              install prefix (default: $HOME/.local)
#   UTTER_UI        terminal UI style: auto (default), gum, or plain
#   UTTER_COLOR     color depth: auto (default), truecolor, 256, 16, or plain
#   UTTER_NO_ANIM   set to disable the logo sweep / typewriter animation
#   UTTER_PYTHON    python interpreter baked into the assistant wrapper
#   UTTER_MODEL_STT / _DECISION / _VISION / _TTS
#                       optional model source for a tier (hf:org/repo[:file],
#                       https://… or file://…); pulled only if that tier is chosen
#   UTTER_MODEL_STT_<LANG> / UTTER_MODEL_TTS_<LANG>
#                       per-language overrides (e.g. UTTER_MODEL_STT_DE_DE or
#                       UTTER_MODEL_STT_DE) that fall back to the generic tier var
#   UTTER_TTS_VOICE_<LANG> / UTTER_TTS_VOICE
#                       voice name/path written to [tts] voice for that language
#   UTTER_LOCALE_PACK_<LANG> / UTTER_LOCALE_PACK
#                       optional UI localization pack source; only offered (and
#                       only pulled) when it is configured
#
# Flags:
#   --appimage         install the AppImage (no sudo; default)
#   --package          install the .deb/.rpm via the package manager (sudo)
#   --only <csv>       only offer these components (core,lang,gui,units,models,…)
#   --skip <csv>       never offer these components
#   --with-noctalia    mark the optional Noctalia widget as recommended
#   --dry-run          run the walk, print the plan, change nothing
#   --uninstall        menu of installed components (per-component install-state)
#   --yes, -y          accept all recommended defaults, no prompts
#   -h, --help
set -euo pipefail

# --------------------------------------------------------------------------- #
# section: defaults + argument parsing
# --------------------------------------------------------------------------- #
UTTER_REPO="${UTTER_REPO:-sujaisubbanna/utter-assistant}"
UTTER_VERSION="${UTTER_VERSION:-latest}"
UTTER_BASE_URL="${UTTER_BASE_URL:-}"
PREFIX="${PREFIX:-$HOME/.local}"

MODE="appimage"        # appimage | package
DRY_RUN=0
UNINSTALL=0
PURGE=0
ASSUME_YES=0
ONLY_CSV=""
SKIP_CSV=""
WITH_NOCTALIA=0

usage() {
    cat <<'USAGE'
utter bootstrap installer — interactive step-by-step wizard + curl | bash.

  curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
  curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes

In a terminal this is an interactive wizard: it walks every component and asks
whether you want it (showing what it is, its size, whether sudo is needed, and
what was detected on this machine). With --yes it accepts the recommended
defaults non-interactively. Piped with no --yes it prints the plan and exits
without changing anything.

Every download is verified against sha256sums.txt from the GitHub Release.

Environment:
  UTTER_REPO      GitHub repo "owner/name" (default: sujaisubbanna/utter-assistant)
  UTTER_VERSION   release tag (default: latest)
  UTTER_BASE_URL  override the download base (GitHub Releases; use
                      http://127.0.0.1:PORT for local testing)
  PREFIX              install prefix (default: $HOME/.local)
  UTTER_UI        terminal UI style: auto (default), gum, or plain
  UTTER_PYTHON    python interpreter baked into the assistant wrapper
  UTTER_MODEL_STT / _DECISION / _VISION / _TTS
                      optional source per model tier (hf:org/repo[:file],
                      https://… or file://…); pulled only if that tier is chosen
  UTTER_MODEL_STT_<LANG> / UTTER_MODEL_TTS_<LANG>
                      per-language override for the multilingual speech model
                      or the TTS voice (falls back to UTTER_MODEL_STT / _TTS)
  UTTER_TTS_VOICE_<LANG> / UTTER_TTS_VOICE
                      voice name/path written to [tts] voice
  UTTER_LOCALE_PACK_<LANG> / UTTER_LOCALE_PACK
                      optional UI localization pack; only offered when configured

Flags:
  --appimage         install the AppImage (no sudo; default)
  --package          install the .deb/.rpm via the package manager (sudo)
  --only <csv>       only offer these components (core,lang,gui,units,models,…)
  --skip <csv>       never offer these components
  --with-noctalia    mark the optional Noctalia widget as recommended
  --dry-run          run the walk, print the plan, change nothing
  --uninstall        menu of installed components (per-component install-state)
  --purge            with --uninstall: also remove downloaded models
  --yes, -y          accept all recommended defaults, no prompts
    -h, --help         show this help
USAGE
}

# macOS has a much smaller install path than the Linux wizard: a single .dmg
# whose app self-installs its runtime on first launch. Its usage is separate so
# `curl … | bash --help` documents the macOS flags on a Mac.
macos_usage() {
    cat <<'USAGE'
utter installer (macOS)

  curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
  curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes

Downloads the utter-gui .dmg for this Mac (Apple Silicon or Intel), verifies it
against the release checksums, installs utter.app to /Applications (or
~/Applications when /Applications is not writable), re-signs it with a stable
identity so macOS privacy grants persist, and launches it. The app's Set up page
then unpacks its runtime and asks for Microphone, Speech Recognition, Input
Monitoring, Accessibility and Screen Recording.

Flags:
  (none)         install (this is the default)
  --uninstall    remove the app, runtime, logs and launchd agents; keep config
  --dry-run      print the plan (version, arch, URLs, target) and change nothing
  --yes, -y      accept defaults / confirm removal without prompting
  -h, --help     show this help

Defaults:
  install path   /Applications/utter.app (fallback ~/Applications/utter.app)
  runtime        ~/Library/Application Support/utter/runtime
  config         ~/.config/utter (kept on uninstall)

Environment:
  UTTER_REPO      GitHub repo "owner/name" (default: sujaisubbanna/utter-assistant)
  UTTER_VERSION   release tag (default: latest)
  UTTER_BASE_URL  override the download base (use http://127.0.0.1:PORT for tests)
USAGE
}

need_value() {
    # need_value <flag> <value>
    [[ $# -ge 2 && -n "${2:-}" ]] || { printf 'ERROR: %s needs a value\n' "$1" >&2; exit 2; }
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --appimage)       MODE="appimage" ;;
        --package)        MODE="package" ;;
        --only)           need_value "$1" "${2:-}"; ONLY_CSV="${2:-}"; shift ;;
        --skip)           need_value "$1" "${2:-}"; SKIP_CSV="${2:-}"; shift ;;
        --with-noctalia)  WITH_NOCTALIA=1 ;;
        --dry-run)        DRY_RUN=1 ;;
        --uninstall)      UNINSTALL=1 ;;
        --purge)          PURGE=1 ;;
        --yes|-y)         ASSUME_YES=1 ;;
        -h|--help)
            if [[ "$(uname -s)" == "Darwin" ]]; then macos_usage; else usage; fi
            exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

# --------------------------------------------------------------------------- #
# section: macOS (Darwin) install path
# --------------------------------------------------------------------------- #
# macOS gets a much smaller path than the Linux wizard: a single .dmg whose app
# self-installs its runtime on first launch. It is dispatched HERE, before the
# i18n/UI sections, because a stock Mac runs bash 3.2 (`/bin/bash`) which cannot
# even parse the `declare -A` used by the Linux wizard. This block is
# self-contained and bash-3.2 compatible; the Linux code path below is untouched.
#
# Released macOS assets (per tag):
#   utter-gui_<ver>_<arch>.dmg        arch: aarch64 | x86_64
#   sha256sums-macos-<arch>.txt
#
# Release resolution mirrors the Linux resolve_release() below so the
# UTTER_VERSION / UTTER_BASE_URL overrides and the GitHub `releases/latest`
# lookup behave identically.
if [[ "$(uname -s)" == "Darwin" ]]; then

MAC_ARCH=""
MAC_DMG=""
MAC_SUMS=""
MAC_APP_NAME="utter.app"
MAC_IDENT="org.utter.settings"
MAC_TMP="$(mktemp -d "${TMPDIR:-/tmp}/utter-install.XXXXXX")"
MAC_MOUNT=""

macos_note() { printf '  note: %s\n' "$*"; }
macos_warn() { printf '  WARNING: %s\n' "$*" >&2; }
macos_die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

macos_cleanup() {
    if [[ -n "${MAC_MOUNT:-}" ]]; then
        hdiutil detach "$MAC_MOUNT" -quiet 2>/dev/null || true
    fi
    rm -rf "$MAC_TMP" 2>/dev/null || true
}

macos_detect_arch() {
    case "$(uname -m)" in
        arm64)  MAC_ARCH="aarch64" ;;
        x86_64) MAC_ARCH="x86_64" ;;
        *) macos_die "unsupported macOS architecture: $(uname -m) (expected arm64 or x86_64)" ;;
    esac
}

# macos_target — preferred utter.app destination (/Applications, else ~/Applications)
macos_target() {
    if [[ -d /Applications && -w /Applications ]]; then
        printf '%s' "/Applications/$MAC_APP_NAME"
    else
        printf '%s' "$HOME/Applications/$MAC_APP_NAME"
    fi
}

# macos_resolve_release — mirrors resolve_release() (see the Linux section below)
macos_resolve_release() {
    local api
    if [[ -n "$UTTER_BASE_URL" ]]; then
        MAC_BASE_URL="${UTTER_BASE_URL%/}"
        [[ "$UTTER_VERSION" == "latest" ]] && \
            macos_die "UTTER_BASE_URL is set but UTTER_VERSION=latest; set UTTER_VERSION"
        MAC_VER="$UTTER_VERSION"
    else
        if [[ "$UTTER_VERSION" == "latest" ]]; then
            if (( DRY_RUN )); then
                MAC_VER="<latest>"
            else
                api="https://api.github.com/repos/$UTTER_REPO/releases/latest"
                printf '  querying: %s\n' "$api"
                MAC_VER="$(curl -fsSL "$api" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1 || true)"
                [[ -n "$MAC_VER" ]] || macos_die "could not resolve the latest release for $UTTER_REPO"
            fi
        else
            MAC_VER="$UTTER_VERSION"
        fi
        MAC_BASE_URL="https://github.com/$UTTER_REPO/releases/download/$MAC_VER"
    fi
    MAC_VER_NUM="${MAC_VER#v}"
}

macos_asset_names() {
    MAC_DMG="utter-gui_${MAC_VER_NUM}_${MAC_ARCH}.dmg"
    MAC_SUMS="sha256sums-macos-${MAC_ARCH}.txt"
}

# macos_download <url> <dest> — curl with retries; DRY_RUN only prints
macos_download() {
    local url="$1" dest="$2"
    if (( DRY_RUN )); then
        printf '  [dry-run] download %s\n' "$url"
        return 0
    fi
    printf '  [get] %s\n' "$url"
    curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url" \
        || macos_die "download failed: $url"
}

# macos_verify <asset> <sums-file> — trust `shasum -a 256`, never GNU sha256sum
macos_verify() {
    local asset="$1" sums="$2" want got
    if (( DRY_RUN )); then
        printf '  [dry-run] verify sha256 of %s against %s\n' "$asset" "$(basename "$sums")"
        return 0
    fi
    [[ -f "$sums" ]] || macos_die "missing checksums $(basename "$sums") (cannot verify $asset)"
    # Release checksums are generated with `shasum -a 256 ./*`, so the path
    # field carries a "./" prefix; match on the basename.
    want="$(awk -v a="$asset" '{ n=$2; sub(/^\*/, "", n); sub(/^\.\//, "", n); if (n==a) { print $1; exit } }' "$sums")"
    [[ -n "$want" ]] || macos_die "$asset not listed in $(basename "$sums")"
    got="$(shasum -a 256 "$MAC_TMP/$asset" | awk '{print $1}')"
    [[ "$want" == "$got" ]] \
        || macos_die "sha256 mismatch for $asset: want $want got $got"
    printf '  [ok] sha256 %s... %s\n' "${got:0:16}" "$asset"
}

# macos_re_sign <app> — explicit identifier-based designated requirement (no
# certificate). Keeps TCC (Microphone/Speech/Accessibility/…) grants valid
# across updates; without it ad-hoc signatures change cdhash on every build.
macos_re_sign() {
    local app="$1"
    if ! command -v codesign >/dev/null 2>&1; then
        macos_warn "codesign not found; skipping re-sign (macOS privacy grants may not persist)"
        return 0
    fi
    printf '  re-signing with a stable identifier so privacy grants persist\n'
    codesign --force --sign - --identifier "$MAC_IDENT" \
        --requirements "=designated => identifier \"$MAC_IDENT\"" \
        --timestamp=none "$app" \
        || macos_warn "re-sign failed; privacy grants may not persist across updates"
}

macos_plan() {
    local dmg_url="${MAC_BASE_URL}/${MAC_DMG}"
    local sums_url="${MAC_BASE_URL}/${MAC_SUMS}"
    local dest; dest="$(macos_target)"
    printf '\n== plan (dry run) ==\n'
    printf '  os:         macOS (%s)\n' "$(uname -m)"
    printf '  version:    %s\n' "$MAC_VER"
    printf '  arch:       %s\n' "$MAC_ARCH"
    printf '  dmg:        %s\n' "$dmg_url"
    printf '  checksums:  %s\n' "$sums_url"
    printf '  target:     %s\n' "$dest"
    printf '\nThis is a dry run: nothing will be downloaded, installed or changed.\n'
    printf 'Without --dry-run this downloads and verifies the .dmg, copies utter.app\n'
    printf 'to the target above, re-signs it with a stable identity and launches it.\n'
    printf "The app's Set up page then unpacks the runtime and asks for permissions.\n"
}

macos_install() {
    local dmg_url="${MAC_BASE_URL}/${MAC_DMG}"
    local sums_url="${MAC_BASE_URL}/${MAC_SUMS}"
    local dest src

    printf '\n== install ==\n'
    printf '  version:    %s\n' "$MAC_VER"
    printf '  arch:       %s\n' "$MAC_ARCH"
    printf '  dmg:        %s\n' "$MAC_DMG"

    macos_download "$dmg_url" "$MAC_TMP/$MAC_DMG"
    macos_download "$sums_url" "$MAC_TMP/$MAC_SUMS"
    macos_verify "$MAC_DMG" "$MAC_TMP/$MAC_SUMS"

    dest="$(macos_target)"
    if [[ "$dest" != "/Applications/$MAC_APP_NAME" ]]; then
        macos_note "/Applications is not writable; installing to $dest instead"
    fi

    if (( DRY_RUN )); then
        printf '  [dry-run] hdiutil attach %s\n' "$MAC_TMP/$MAC_DMG"
        printf '  [dry-run] ditto utter.app -> %s\n' "$dest"
        printf '  [dry-run] xattr -cr; codesign --force --sign - --identifier %s\n' "$MAC_IDENT"
        printf '  [dry-run] open %s\n' "$dest"
        return 0
    fi

    MAC_MOUNT="$(mktemp -d "$MAC_TMP/dmg.XXXXXX")"
    hdiutil attach -nobrowse -quiet -mountpoint "$MAC_MOUNT" "$MAC_TMP/$MAC_DMG" \
        || macos_die "could not mount $MAC_DMG"

    src=""
    if [[ -d "$MAC_MOUNT/$MAC_APP_NAME" ]]; then
        src="$MAC_MOUNT/$MAC_APP_NAME"
    else
        src="$(find "$MAC_MOUNT" -maxdepth 1 -type d -name '*.app' 2>/dev/null | head -1)"
    fi
    if [[ -z "$src" ]]; then
        hdiutil detach "$MAC_MOUNT" -quiet 2>/dev/null || true
        MAC_MOUNT=""
        macos_die "no .app bundle found in $MAC_DMG"
    fi

    mkdir -p "$(dirname "$dest")"
    if [[ -e "$dest" ]]; then
        printf '  removing previous %s\n' "$dest"
        rm -rf "$dest"
    fi
    if ! ditto "$src" "$dest"; then
        hdiutil detach "$MAC_MOUNT" -quiet 2>/dev/null || true
        MAC_MOUNT=""
        macos_die "could not copy utter.app to $dest"
    fi
    hdiutil detach "$MAC_MOUNT" -quiet 2>/dev/null \
        || macos_warn "could not detach $MAC_DMG (it may still be mounted)"
    MAC_MOUNT=""

    xattr -cr "$dest" 2>/dev/null || true
    macos_re_sign "$dest"

    printf '\n'
    printf 'Installed %s\n' "$dest"
    open "$dest" || macos_warn "could not launch utter; open $dest manually"

    printf '\n== next steps ==\n'
    printf 'utter should open to its Set up page. On first launch it unpacks the\n'
    printf 'bundled runtime into ~/Library/Application Support/utter/runtime/ and\n'
    printf 'writes the com.utter.assistant / com.utter.runner launchd agents.\n'
    printf 'Grant Microphone, Speech Recognition, Input Monitoring, Accessibility and\n'
    printf 'Screen Recording when macOS asks, so the assistant can hear and act.\n'
}

macos_remove_path() {
    local p="$1"
    if (( DRY_RUN )); then
        printf '  [dry-run] remove %s\n' "$p"
    elif [[ -e "$p" || -L "$p" ]]; then
        rm -rf "$p"
        printf '  removed   %s\n' "$p"
    else
        printf '  not present: %s\n' "$p"
    fi
}

macos_uninstall() {
    local uid label ans
    uid="$(id -u)"

    printf '\n== uninstall (macOS) ==\n'
    printf 'This removes:\n'
    printf '  /Applications/utter.app (and ~/Applications/utter.app)\n'
    printf '  ~/Library/Application Support/utter (runtime, models, state)\n'
    printf '  ~/Library/Logs/utter\n'
    printf '  ~/Library/LaunchAgents/com.utter.assistant.plist\n'
    printf '  ~/Library/LaunchAgents/com.utter.runner.plist\n'
    printf 'This keeps your config: ~/.config/utter (remove it manually if you want).\n\n'

    if (( ! ASSUME_YES && ! DRY_RUN )); then
        if [[ ! -t 0 ]]; then
            printf 'stdin is not a terminal; nothing was removed.\n'
            printf 'Re-run with: bash install.sh --uninstall --yes\n'
            return 0
        fi
        printf 'Remove the items above? [y/N] '
        IFS= read -r ans || ans=""
        case "$ans" in
            [yY]|[yY][eE][sS]) ;;
            *) printf 'Aborted; nothing removed.\n'; return 0 ;;
        esac
    fi

    for label in com.utter.assistant com.utter.runner; do
        if (( DRY_RUN )); then
            printf '  [dry-run] launchctl bootout gui/%s/%s\n' "$uid" "$label"
        else
            launchctl bootout "gui/$uid/$label" 2>/dev/null || true
        fi
    done

    if (( DRY_RUN )); then
        printf '  [dry-run] quit utter if running\n'
    else
        osascript -e 'tell application "utter" to quit' >/dev/null 2>&1 || true
        pkill -f '/utter.app/Contents/MacOS' 2>/dev/null || true
    fi

    macos_remove_path "/Applications/$MAC_APP_NAME"
    macos_remove_path "$HOME/Applications/$MAC_APP_NAME"
    macos_remove_path "$HOME/Library/Application Support/utter"
    macos_remove_path "$HOME/Library/Logs/utter"
    macos_remove_path "$HOME/Library/LaunchAgents/com.utter.assistant.plist"
    macos_remove_path "$HOME/Library/LaunchAgents/com.utter.runner.plist"

    if (( DRY_RUN )); then
        printf '\nDry run: nothing was actually removed.\n'
    else
        printf '\nUninstalled. Your config at ~/.config/utter was kept.\n'
    fi
}

macos_main() {
    macos_detect_arch

    if (( UNINSTALL )); then
        macos_uninstall
        return 0
    fi

    # --only/--skip/--with-noctalia/--appimage/--package are Linux-only.
    if [[ "$MODE" == "package" ]]; then
        macos_die "--package is Linux-only; on macOS the installer always uses the .dmg"
    fi
    if [[ -n "$ONLY_CSV" || -n "$SKIP_CSV" || "$WITH_NOCTALIA" == "1" ]]; then
        macos_note "--only/--skip/--with-noctalia/--appimage/--package are Linux-only; ignored on macOS"
    fi

    macos_resolve_release
    macos_asset_names

    if (( DRY_RUN )); then
        macos_plan
        return 0
    fi

    macos_install
    return 0
}

trap 'macos_cleanup' EXIT
macos_main
exit 0

fi  # Darwin

# --------------------------------------------------------------------------- #
# section: i18n — installer UI language (English inline; locale files are data)
# --------------------------------------------------------------------------- #
# This script stays a single self-contained file and the published
# `curl … | bash` one-liner keeps working in English even when no locale files
# are present. Translations live beside the script as data:
#
#     install/i18n/<lang>.sh          (repo / checkout)
#     <PREFIX>/share/utter/i18n/<lang>.sh     (installed tree)
#
# A locale file is plain bash assigning the `L10N` associative array. It is
# sourced when present; nothing is ever fetched over the network for it. With
# no file, every lookup falls back to the English source silently — a missing
# key never prints a raw key. Locale files are not part of this single-file
# script: they are data looked up beside the script or in $SHARE_DIR/i18n, so
# `curl … | bash` keeps working in English with no extra files.
#
# Machine-drafted locale files ship UNREVIEWED; see docs/TRANSLATING.md.
#
# The UI language is the detected system locale (LC_ALL -> LC_MESSAGES -> LANG),
# overridable with UTTER_INSTALL_LANG (e.g. `de`, `de-DE`, `pt-BR`). This is the
# INSTALLER's language; it is independent of the language step, which chooses
# the spoken STT/TTS language written to config.toml.
#
# Printf safety: translated text is always passed to `printf` as a `%s`
# argument, never as a format string. `t <key> [args…]` substitutes `{1}`…`{N}`
# positionally as literal data, so a translation containing `%s` or `$(…)` is
# printed verbatim and can never inject a format.

declare -A L10N=()
UTTER_I18N_LOADED=""
UTTER_I18N_LANG="en"

# _i18n_base_lang <raw> — first subtag, lowercased (de-DE -> de, zh_CN.UTF-8 -> zh)
_i18n_base_lang() {
    local raw="${1:-}"
    raw="${raw%%@*}"; raw="${raw%%.*}"; raw="${raw//_/-}"
    raw="${raw%%-*}"
    printf '%s' "${raw,,}"
}

# _i18n_system_lang — base language from the system locale, or empty (C/POSIX)
_i18n_system_lang() {
    local raw="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}"
    case "${raw^^}" in ''|C|POSIX) return 0 ;; esac
    _i18n_base_lang "$raw"
}

# _i18n_script_dir — directory of this script when it is a real file (not a
# `curl | bash` pipe); empty when piped or unresolvable.
_i18n_script_dir() {
    local self="${BASH_SOURCE[0]:-}"
    [[ -n "$self" && -f "$self" ]] || return 0
    local d; d="$(cd -- "$(dirname -- "$self")" 2>/dev/null && pwd)"
    printf '%s' "$d"
}

# i18n_init — resolve the UI language and source its locale file, silently
# falling back to English when no locale file is available.
i18n_init() {
    local lang
    lang="$(_i18n_base_lang "${UTTER_INSTALL_LANG:-}")"
    [[ -n "$lang" ]] || lang="$(_i18n_system_lang)"
    [[ -n "$lang" ]] || lang="en"
    UTTER_I18N_LANG="$lang"
    [[ "$lang" == "en" ]] && return 0
    local dir f
    dir="$(_i18n_script_dir)"
    for f in \
        "${dir:+$dir/install/i18n/$lang.sh}" \
        "${UTTER_I18N_DIR:+$UTTER_I18N_DIR/$lang.sh}" \
        "$PREFIX/share/utter/i18n/$lang.sh"; do
        [[ -n "$f" && -r "$f" ]] || continue
        L10N=()
        # shellcheck disable=SC1090
        if source "$f" 2>/dev/null; then
            UTTER_I18N_LOADED="$f"
            return 0
        fi
    done
    L10N=()
    return 0
}
i18n_init

# l10n <english> — the translation for an exact English message, else English.
# An explicitly blanked translation is treated as missing (falls back).
# An empty message (blank line) is returned as-is: `L10N[]` is not a valid
# subscript, so the empty key must short-circuit.
l10n() {
    local key="${1:-}" val
    [[ -n "$key" ]] || return 0
    val="${L10N[$key]-}"
    if [[ -n "$val" ]]; then printf '%s' "$val"; else printf '%s' "$key"; fi
}

# _i18n_escape <s> — literal replacement text for parameter expansion
# (guard `&` which is special under bash's patsub_replacement, and backslash).
_i18n_escape() {
    local s="${1-}"
    s="${s//\\/\\\\}"
    s="${s//&/\\&}"
    printf '%s' "$s"
}

# t <key> [args…] — print the translation for <key>, substituting {1}…{N} with
# the arguments as literal text. Printed with `printf '%s'`: never a format.
t() {
    local key="${1:-}"; shift || true
    local out; out="$(l10n "$key")"
    if (( $# )); then
        local i=0 a
        for a in "$@"; do
            i=$(( i + 1 ))
            out="${out//\{$i\}/$(_i18n_escape "$a")}"
        done
    fi
    printf '%s' "$out"
}

# t_line <key> [args…] — t plus a trailing newline (for direct printing).
t_line() { t "$@"; printf '\n'; }

# say_f <key> [args…] — say for a message with runtime substitutions; the
# translation substitutes {1}…{N} as literal data and is wrapped like say.
say_f() { say "$(t "$@")"; }
# note_f / warn_f / sub_f — same idea for the other output helpers.
note_f() { note "$(t "$@")"; }
warn_f() { warn "$(t "$@")"; }
sub_f()  { sub "$(t "$@")"; }
# field_f <keykey> <valkey> [args…] — field where the value is looked up (the
# key column stays a fixed short label); args substitute into the value cell.
field_f() {
    local kk="$1" vk="$2"; shift 2
    field "$kk" "$(t "$vk" "$@")"
}
# section_f <key> [args…] — section for a message with runtime substitutions.
section_f() { section "$(t "$@")"; }
# ok_f <key> [args…] / ask_yn_f <def> <key> [args…] — substitution variants.
ok_f() { ok "$(t "$@")"; }
ask_yn_f() {
    local def="$1" key="$2"; shift 2
    local prompt; prompt="$(t "$key" "$@")"
    [[ "$prompt" == "  "* ]] || prompt="  $prompt"
    ask_yn "$def" "$prompt"
}
# run_f <key> <cmd…> — run where the description takes {1} = first cmd argument.
run_f() {
    local key="$1"; shift
    run "$(t "$key" "${1:-}")" "$@"
}

# --------------------------------------------------------------------------- #
# section: ui — one canonical output set (colors, banners, tables, prompts)
# --------------------------------------------------------------------------- #
# Rendering adapts to the environment:
#   UTTER_UI=auto|gum|plain        (default auto)
#   UTTER_COLOR=auto|truecolor|256|16|plain   (default auto)
#   UTTER_NO_ANIM=1                (disable the logo sweep / typewriter)
#   NO_COLOR, TERM=dumb, non-tty stdout, --yes, --dry-run
#       -> plain ASCII, no animation, zero escape bytes
# In a real terminal `gum` is preferred for confirm/menu/spinner prompts when it
# is already on PATH; the built-in UI is always the fallback. Nothing is ever
# downloaded for the UI.

UI_MODE="${UTTER_UI:-auto}"
case "$UI_MODE" in
    auto|gum|plain) ;;
    *) UI_MODE="auto" ;;
esac

# Terminal state is sampled once, at startup. Doing `-t 1` later inside a
# command substitution would see the substitution pipe, not the real terminal.
UI_OUT_TTY=0; [[ -t 1 ]] && UI_OUT_TTY=1
UI_IN_TTY=0;  [[ -t 0 ]] && UI_IN_TTY=1
is_tty() { (( UI_IN_TTY )); }            # stdin is a terminal (wizard/prompt gate)
ui_tty() { (( UI_IN_TTY )) && (( UI_OUT_TTY )); }   # both ends (interactive prompt gate)
ui_out_tty() { (( UI_OUT_TTY )); }       # stdout is a terminal (styling/animation gate)

# --yes and --dry-run are fully plain (zero escape bytes), by design.
ui_plain_forced() {
    [[ "$UI_MODE" == "plain" ]] && return 0
    (( ASSUME_YES )) && return 0
    (( DRY_RUN )) && return 0
    return 1
}

# ui_depth — color depth: 3=truecolor, 2=256, 1=16, 0=plain.
ui_depth() {
    # explicit overrides win (handy for tests), then the plain-forced cases.
    case "${UTTER_COLOR:-auto}" in
        truecolor|24bit|3) printf '3'; return 0 ;;
        256|2)             printf '2'; return 0 ;;
        16|1)              printf '1'; return 0 ;;
        plain|0)           printf '0'; return 0 ;;
    esac
    case "${FORCE_COLOR:-}" in
        3|truecolor)   printf '3'; return 0 ;;
        2|256)         printf '2'; return 0 ;;
        1|16)          printf '1'; return 0 ;;
        0|plain|false) printf '0'; return 0 ;;
    esac
    ui_plain_forced && { printf '0'; return 0; }
    [[ -n "${NO_COLOR:-}" ]] && { printf '0'; return 0; }
    [[ "${TERM:-}" == "dumb" ]] && { printf '0'; return 0; }
    ui_out_tty || { printf '0'; return 0; }
    case "${COLORTERM:-}" in truecolor|24bit) printf '3'; return 0 ;; esac
    case "${TERM:-}" in
        *truecolor*|*-direct|xterm-kitty|alacritty|wezterm|foot|contour|ghostty) printf '3'; return 0 ;;
        *256color*) printf '2'; return 0 ;;
    esac
    printf '1'
}
UI_DEPTH="$(ui_depth)"

ui_color_ok() { [[ "$UI_DEPTH" -gt 0 ]]; }

ui_unicode_ok() {
    ui_plain_forced && return 1
    [[ "${TERM:-}" == "dumb" ]] && return 1
    ui_out_tty || return 1
    case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
        *[Uu][Tt][Ff]-8|*[Uu][Tt][Ff]8) return 0 ;;
    esac
    return 1
}

ui_anim_ok() {
    (( ASSUME_YES )) && return 1
    (( DRY_RUN )) && return 1
    [[ -n "${UTTER_NO_ANIM:-}" ]] && return 1
    [[ -n "${NO_COLOR:-}" ]] && return 1
    [[ "$UI_MODE" == "plain" ]] && return 1
    [[ "${TERM:-}" == "dumb" ]] && return 1
    ui_out_tty || return 1
    return 0
}

ui_gum_ok() {
    ui_plain_forced && return 1
    [[ "${TERM:-}" == "dumb" ]] && return 1
    ui_tty || return 1
    command -v gum >/dev/null 2>&1
}

# --- palette --------------------------------------------------------------- #
# Semantic roles. The legacy C_RED/C_GREEN/... names stay populated so existing
# callers keep working; they are aliases of the semantic colours.
C_RESET=""; C_BOLD=""; C_DIM=""
C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""
C_ACCENT=""; C_ACC_HI=""; C_ACC_LO=""; C_FG=""; C_MUTED=""; C_FAINT=""
C_OK=""; C_WARN=""; C_ERR=""
case "$UI_DEPTH" in
    3)
        C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
        C_ACCENT=$'\033[38;2;247;201;72m'; C_ACC_HI=$'\033[38;2;255;224;138m'
        C_ACC_LO=$'\033[38;2;154;107;0m';   C_FG=$'\033[38;2;236;236;236m'
        C_MUTED=$'\033[38;2;139;139;137m';  C_FAINT=$'\033[38;2;88;88;86m'
        C_OK=$'\033[38;2;123;216;143m';     C_WARN=$'\033[38;2;242;194;48m'
        C_ERR=$'\033[38;2;255;107;107m'
        C_RED="$C_ERR"; C_GREEN="$C_OK"; C_YELLOW="$C_WARN"
        C_BLUE=$'\033[38;2;122;162;247m'; C_CYAN="$C_ACCENT"
        ;;
    2)
        C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
        C_ACCENT=$'\033[38;5;221m'; C_ACC_HI=$'\033[38;5;222m'
        C_ACC_LO=$'\033[38;5;136m'; C_FG=$'\033[38;5;255m'
        C_MUTED=$'\033[38;5;245m';  C_FAINT=$'\033[38;5;240m'
        C_OK=$'\033[38;5;114m';     C_WARN=$'\033[38;5;221m'
        C_ERR=$'\033[38;5;203m'
        C_RED="$C_ERR"; C_GREEN="$C_OK"; C_YELLOW="$C_WARN"
        C_BLUE=$'\033[38;5;111m'; C_CYAN="$C_ACCENT"
        ;;
    1)
        C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
        C_ACCENT=$'\033[93m'; C_ACC_HI=$'\033[93m'; C_ACC_LO=$'\033[33m'
        C_FG=$'\033[97m'; C_MUTED=$'\033[90m'; C_FAINT=$'\033[90m'
        C_OK=$'\033[92m'; C_WARN=$'\033[93m'; C_ERR=$'\033[91m'
        C_RED="$C_ERR"; C_GREEN="$C_OK"; C_YELLOW="$C_WARN"
        C_BLUE=$'\033[94m'; C_CYAN=$'\033[93m'
        ;;
esac

if ui_unicode_ok; then
    GL_H="─"; GL_ELL="…"
    SPIN_FRAMES="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    RULE_CH="─"
    TASK_PENDING="·"; TASK_DONE="✓"; TASK_FAIL="✗"; TASK_RUN="▸"
    STEP_DONE="●"; STEP_TODO="○"
else
    GL_H=""; GL_ELL="..."
    SPIN_FRAMES="|/-\\"
    RULE_CH="-"
    TASK_PENDING="."; TASK_DONE="ok"; TASK_FAIL="XX"; TASK_RUN=">"
    STEP_DONE="#"; STEP_TODO="-"
fi

# --- core output ----------------------------------------------------------- #

say() {
    local text cols; text="$(l10n "$*")"
    cols="$(ui_cols)"
    if (( ${#text} <= cols )); then printf '%s\n' "$text"; return 0; fi
    local indent="" rest="$text"
    while [[ "$rest" == " "* ]]; do indent+=" "; rest="${rest# }"; done
    ui_wrap "$indent" "$rest"
}

# field <key> <value> — aligned "  key   value" row; long values wrap to the
# terminal width with a continuation indent aligned under the value column.
# The key column is a fixed short technical label (kept as-is so the 9-char
# alignment holds); the value is looked up, and values built from runtime data
# fall back to English unchanged.
field() {
    local key="${1:-}" value cols avail
    value="$(l10n "${2:-}")"
    cols="$(ui_cols)"; avail=$(( cols - 11 )); (( avail < 8 )) && avail=8
    if (( ${#value} <= avail )); then
        printf '  %s%-9s%s%s\n' "$C_MUTED" "$key" "$C_RESET" "$value"
        return 0
    fi
    printf '  %s%-9s%s' "$C_MUTED" "$key" "$C_RESET"
    ui_wrap_first "           " "$avail" "$value"
}
# sub <text> — continuation line, aligned under a field value
sub() { say "           $(l10n "$*")"; }

# The ok/note/WARNING/ERROR prefixes are fixed short tokens: they are kept
# untranslated so the hard-coded indent/width math stays correct. Only the
# message body is looked up.
ok() {
    printf '  %s[ok]%s ' "$C_OK" "$C_RESET"
    ui_wrap_first "       " "$(( $(ui_cols) - 7 ))" "$(l10n "$*")"
}
note() {
    printf '  %snote:%s ' "$C_MUTED" "$C_RESET"
    ui_wrap_first "        " "$(( $(ui_cols) - 8 ))" "$(l10n "$*")"
}
warn() { printf '  %sWARNING:%s %s\n' "$C_WARN" "$C_RESET" "$(l10n "$*")" >&2; }
die()  { printf '%sERROR:%s %s\n' "$C_ERR" "$C_RESET" "$(l10n "$*")" >&2; exit 1; }

# ui_cols — terminal width, always a positive integer (COLUMNS, then tput, then 80)
ui_cols() {
    local n="${COLUMNS:-}"
    case "${n:-}" in ''|*[!0-9]*) n="$(tput cols 2>/dev/null || true)" ;; esac
    case "${n:-}" in ''|*[!0-9]*) n=80 ;; esac
    (( n > 0 )) || n=80
    printf '%s' "$n"
}

# ui_wrap <indent> <text> — print text word-wrapped, indent on every line.
# In very narrow terminals (<40 cols) over-long tokens are hard-split so the
# line never exceeds the width; at normal widths tokens are left intact.
ui_wrap() {
    local indent="$1" text="${2:-}" cols avail current="" tok
    local -a words=(); local w
    cols="$(ui_cols)"; avail=$(( cols - ${#indent} )); (( avail < 8 )) && avail=8
    for w in $text; do
        if (( cols < 40 )); then
            while (( ${#w} > avail )); do words+=("${w:0:avail}"); w="${w:avail}"; done
        fi
        [[ -n "$w" ]] && words+=("$w")
    done
    for tok in "${words[@]:-}"; do
        if [[ -z "$current" ]]; then current="$tok"
        elif (( ${#current} + 1 + ${#tok} <= avail )); then current+=" $tok"
        else printf '%s%s\n' "$indent" "$current"; current="$tok"; fi
    done
    [[ -n "$current" ]] && printf '%s%s\n' "$indent" "$current"
    return 0
}
# ui_wrap_first <cont_indent> <avail> <text> — first line printed bare (the
# caller already wrote a prefix); continuation lines get the indent.
ui_wrap_first() {
    local indent="$1" avail="$2" text="${3:-}" current="" tok first=1
    local -a words=(); local w cols
    cols="$(ui_cols)"
    for w in $text; do
        if (( cols < 40 )); then
            while (( ${#w} > avail )); do words+=("${w:0:avail}"); w="${w:avail}"; done
        fi
        [[ -n "$w" ]] && words+=("$w")
    done
    for tok in "${words[@]:-}"; do
        if [[ -z "$current" ]]; then current="$tok"
        elif (( ${#current} + 1 + ${#tok} <= avail )); then current+=" $tok"
        else
            if (( first )); then printf '%s\n' "$current"; first=0
            else printf '%s%s\n' "$indent" "$current"; fi
            current="$tok"
        fi
    done
    if (( first )); then printf '%s\n' "$current"
    else printf '%s%s\n' "$indent" "$current"; fi
    return 0
}

# ui_rule [width] — faint horizontal rule, clamped to the terminal
ui_rule() {
    local w="${1:-56}" cols s
    cols="$(ui_cols)"
    (( w > cols - 4 )) && w=$(( cols - 4 ))
    (( w < 8 )) && w=8
    printf -v s '%*s' "$w" ''; s="${s// /$RULE_CH}"
    printf '  %s%s%s\n' "$C_FAINT" "$s" "$C_RESET"
}

# section <title> — phase banner
section() {
    local title; title="$(l10n "$*")"
    local cols pad rule hdr
    if [[ "$RULE_CH" == "-" ]]; then
        hdr="== $title =="
        printf '\n'
        if (( ${#hdr} <= $(ui_cols) )); then printf '%s\n' "$hdr"; else ui_wrap "" "$hdr"; fi
        return 0
    fi
    cols="$(ui_cols)"
    pad=$(( cols - ${#title} - 4 )); (( pad < 4 )) && pad=4; (( pad > 56 )) && pad=56
    printf -v rule '%*s' "$pad" ''; rule="${rule// /$RULE_CH}"
    printf '\n%s%s %s%s%s %s%s\n' \
        "$C_ACCENT" "${RULE_CH}${RULE_CH}" "$C_BOLD" "$title" "$C_RESET" \
        "$C_FAINT" "$rule" "$C_RESET"
}

# step_header <n> <total> <label> — wizard step indicator with a progress bar
step_header() {
    local n="$1" total="$2" label; label="$(l10n "${3:-}")"
    local cols pfx cont maxdots dots="" i
    cols="$(ui_cols)"
    pfx="[${n}/${total}]"
    cont="$(printf '%*s' "$(( ${#pfx} + 1 ))" '')"
    if [[ "$RULE_CH" == "-" ]]; then
        printf '\n%s ' "$pfx"
        ui_wrap_first "$cont" "$(( cols - ${#pfx} - 1 ))" "$label"
        return 0
    fi
    maxdots=$(( cols - 2 ))
    (( maxdots > total )) && maxdots=$total
    for (( i=1; i<=maxdots; i++ )); do
        if (( i <= n )); then dots+="$STEP_DONE"; else dots+="$STEP_TODO"; fi
    done
    if (( ${#pfx} + ${#label} + ${#dots} + 3 <= cols )); then
        printf '\n%s%s%s %s%s%s  %s%s%s\n' \
            "$C_DIM" "$pfx" "$C_RESET" "$C_BOLD" "$label" "$C_RESET" \
            "$C_ACCENT" "$dots" "$C_RESET"
    else
        printf '\n%s%s%s ' "$C_DIM" "$pfx" "$C_RESET"
        ui_wrap_first "$cont" "$(( cols - ${#pfx} - 1 ))" "$label"
        [[ -n "$dots" ]] && printf '  %s%s%s\n' "$C_ACCENT" "$dots" "$C_RESET"
    fi
    ui_rule
}

# ui_key_legend — the y/n/a/s/q line shown under a wizard question
ui_key_legend() {
    (( ASSUME_YES )) && return 0
    printf '    %sy yes · n no · a all remaining · s skip remaining · q quit%s\n' "$C_MUTED" "$C_RESET"
}

# run <description> <command...> — execute, or print it under --dry-run
run() {
    local desc; desc="$(l10n "${1:-}")"; shift || true
    if (( DRY_RUN )); then
        say_f "  [dry-run] {1}" "$desc"
        say_f "            \$ {1}" "$*"
    else
        say_f "  [run] {1}" "$desc"
        "$@"
    fi
}

# --------------------------------------------------------------------------- #
# section: logo + banner
# --------------------------------------------------------------------------- #
# Solid lowercase "utter", 6 rows. x-height letters (u/e/r) leave row 0 blank
# for the ascender line; the two t's carry the crossbar on row 2. Rendered with
# a per-column amber ramp (no rainbow) and an optional moving highlight, or an
# ASCII fallback when the locale/terminal cannot show blocks.
LOGO_ROWS=6
LOGO_SEQ=(U T T E R)
LOGO_U=('     ' '█   █' '█   █' '█   █' '█   █' ' ███ ')
LOGO_T=(' ██  ' ' ██  ' '█████' ' ██  ' ' ██  ' ' ██  ')
LOGO_E=('     ' '████ ' '█   █' '█████' '█    ' ' ███ ')
LOGO_R=('     ' '████ ' '█   █' '█    ' '█    ' '█    ')
LOGO_LINES=()
LOGO_COLS=29
LOGO_BASE=()
LOGO_COL_SGR=()

# ui_lerp_var <a> <b> <pct> — "r;g;b" mix into $REPL (no subshell)
ui_lerp_var() {
    local ar ag ab br bg bb
    IFS=';' read -r ar ag ab <<<"$1"
    IFS=';' read -r br bg bb <<<"$2"
    REPL="$(( ar + (br-ar)*$3/100 ));$(( ag + (bg-ag)*$3/100 ));$(( ab + (bb-ab)*$3/100 ))"
}
# ui_sgr_var <r;g;b> — foreground SGR for the active depth into $SGRV
ui_sgr_var() {
    local r g b; IFS=';' read -r r g b <<<"$1"
    case "$UI_DEPTH" in
        3) SGRV=$'\033[38;2;'"$r;$g;$b"$'m' ;;
        2) SGRV=$'\033[38;5;'"$(( 16 + 36*(r/43) + 6*(g/43) + (b/43) ))"$'m' ;;
        1) if (( r > 220 )); then SGRV=$'\033[93m'; else SGRV=$'\033[33m'; fi ;;
        *) SGRV="" ;;
    esac
}

ui_logo_build() {
    local row gi line gname
    LOGO_LINES=()
    for (( row=0; row<LOGO_ROWS; row++ )); do
        line=""
        for gi in "${!LOGO_SEQ[@]}"; do
            gname="LOGO_${LOGO_SEQ[gi]}"
            local -n g="$gname"
            line+="${g[row]}"
            (( gi < ${#LOGO_SEQ[@]} - 1 )) && line+=" "
        done
        LOGO_LINES[row]="$line"
    done
    LOGO_COLS="${#LOGO_LINES[0]}"
}

ui_logo_precompute() {
    local x pct
    LOGO_BASE=(); LOGO_COL_SGR=()
    for (( x=0; x<LOGO_COLS; x++ )); do
        pct=$(( x * 100 / (LOGO_COLS-1) ))
        ui_lerp_var '154;107;0' '247;201;72' "$pct"; LOGO_BASE[x]="$REPL"
        ui_sgr_var "$REPL"; LOGO_COL_SGR[x]="$SGRV"
    done
}

# ui_logo [sweep_col] — print the wordmark; sweep_col adds the highlight band
ui_logo() {
    local sweep="${1:-}" row x ch line colr d
    for (( row=0; row<LOGO_ROWS; row++ )); do
        local src="${LOGO_LINES[row]}"
        line=""
        for (( x=0; x<LOGO_COLS; x++ )); do
            ch="${src:x:1}"
            [[ "$ch" == " " ]] && { line+=" "; continue; }
            colr="${LOGO_COL_SGR[x]}"
            if [[ -n "$sweep" ]]; then
                d=$(( x - sweep )); (( d < 0 )) && d=$(( -d ))
                if (( d < 6 )); then
                    ui_lerp_var "${LOGO_BASE[x]}" '255;224;138' "$(( (6-d)*16 ))"
                    ui_sgr_var "$REPL"; colr="$SGRV"
                fi
            fi
            line+="${colr}${ch}"
        done
        if (( UI_DEPTH > 0 )); then printf '%s\033[0m\n' "$line"; else printf '%s\n' "$line"; fi
    done
}

ui_ascii_logo() {
    cat <<'ASCII'
 _   _ _   _ _   _ _____ ____
| | | | |_| | | | |_   _|  _ \
| |_| |  _  | |_| | | | | |_) |
 \__,_|_| |_|\__,_| |_| |  _ <
                        |_| \_\
ASCII
}

ui_compact_logo() {
    printf '  %s%sutter%s\n' "$C_BOLD" "$C_ACCENT" "$C_RESET"
}

# ui_cursor_hide/show + exit restore — never leave the cursor hidden.
UI_CURSOR_HIDDEN=0
TICKER_PID=""
ui_cursor_hide() {
    ui_anim_ok || return 0
    (( UI_CURSOR_HIDDEN )) && return 0
    printf '\033[?25l'; UI_CURSOR_HIDDEN=1
}
ui_cursor_show() {
    (( UI_CURSOR_HIDDEN )) || return 0
    printf '\033[?25h'; UI_CURSOR_HIDDEN=0
}
ui_on_exit() {
    ui_cursor_show
    if [[ -n "${TICKER_PID:-}" ]]; then
        kill "$TICKER_PID" 2>/dev/null || true
        TICKER_PID=""
    fi
    return 0
}

# ui_logo_sweep — one-time shine across the wordmark, then settle.
ui_logo_sweep() {
    local p
    if ! ui_anim_ok; then ui_logo; return 0; fi
    if (( $(ui_cols) < LOGO_COLS + 2 )); then ui_logo; return 0; fi
    ui_cursor_hide
    ui_logo
    for p in -3 0 3 6 9 12 15 18 21 24 27 30; do
        printf '\033[%dA' "$LOGO_ROWS"
        ui_logo "$p"
        sleep 0.045
    done
    printf '\033[%dA' "$LOGO_ROWS"
    ui_logo
    ui_cursor_show
}

# ui_tagline — typewriter line under the logo (plain when not animating).
ui_tagline() {
    local text="local voice -> desktop actions" i ind=7
    ui_unicode_ok && text="local voice → desktop actions"
    (( $(ui_cols) < 40 )) && ind=0
    if ui_anim_ok; then
        printf '%*s' "$ind" ' '
        for (( i=0; i<${#text}; i++ )); do printf '%s' "${text:i:1}"; sleep 0.012; done
        printf '\n'
    else
        printf '%*s%s\n' "$ind" '' "$text"
    fi
}

ui_banner() {
    local cols; cols="$(ui_cols)"
    if ui_unicode_ok; then
        ui_logo_build
        ui_logo_precompute
        if (( cols >= LOGO_COLS + 2 )); then
            ui_logo_sweep
        elif (( cols >= 34 )); then
            ui_ascii_logo
        else
            ui_compact_logo
        fi
    else
        if (( cols >= 34 )); then ui_ascii_logo; else ui_compact_logo; fi
    fi
    printf '\n'
    ui_tagline
}

# --------------------------------------------------------------------------- #
# section: live task list
# --------------------------------------------------------------------------- #
# One row per selected component (pending/working/done/failed). In live mode the
# block is redrawn in place with a background spinner; when live mode is not
# supported (plain, --yes, --dry-run, non-tty, narrow) rows are appended instead
# and no cursor movement is emitted.
TASK_LABELS=(); TASK_STATES=(); TASK_START=()
TASK_DRAWN=0; TASK_ACTIVE=0; TASK_W=24
SPIN_GLYPH=""

ui_tasks_supported() {
    ui_anim_ok || return 1
    (( UI_DEPTH > 0 )) || return 1
    (( $(ui_cols) >= 50 )) || return 1
    return 0
}

ui_tasks_init() {
    TASK_LABELS=("$@"); TASK_STATES=(); TASK_START=()
    local i w=0
    for i in "${!TASK_LABELS[@]}"; do
        TASK_STATES[i]=pending; TASK_START[i]=0
        (( ${#TASK_LABELS[i]} > w )) && w=${#TASK_LABELS[i]}
    done
    (( w < 24 )) && w=24; TASK_W=$w
    TASK_DRAWN=0; TASK_ACTIVE=1
    ui_rule
    ui_tasks_draw
}

ui_tasks_draw() {
    local i st glyph status t pad
    (( TASK_DRAWN )) && printf '\033[%dA' "${#TASK_LABELS[@]}"
    for (( i=0; i<${#TASK_LABELS[@]}; i++ )); do
        st="${TASK_STATES[i]}"
        case "$st" in
            pending) glyph="$TASK_PENDING"; status="${C_MUTED}pending${C_RESET}" ;;
            running) glyph="${SPIN_GLYPH:-$TASK_RUN}"; status="${C_ACCENT}working${C_RESET}" ;;
            done)    t=$(( SECONDS - TASK_START[i] ))
                     glyph="$TASK_DONE"; status="${C_OK}done (${t}s)${C_RESET}" ;;
            failed)  glyph="$TASK_FAIL"; status="${C_ERR}failed${C_RESET}" ;;
            *)       glyph=" "; status="" ;;
        esac
        printf -v pad '%*s' "$(( TASK_W - ${#TASK_LABELS[i]} ))" ''
        printf '\r\033[K  %s%-2s%s %s%s %s\n' \
            "$C_ACCENT" "$glyph" "$C_RESET" "${TASK_LABELS[i]}" "$pad" "$status"
    done
    TASK_DRAWN=1
}

ui_task_ticker_start() {
    ui_tasks_supported || return 0
    (
        trap 'exit 0' TERM INT
        _tick=0
        while :; do
            SPIN_GLYPH="${SPIN_FRAMES:_tick%${#SPIN_FRAMES}:1}"
            ui_tasks_draw
            _tick=$(( _tick + 1 ))
            sleep 0.12
        done
    ) &
    TICKER_PID=$!
}

ui_task_ticker_stop() {
    [[ -n "${TICKER_PID:-}" ]] || return 0
    kill "$TICKER_PID" 2>/dev/null || true
    wait "$TICKER_PID" 2>/dev/null || true
    TICKER_PID=""
    ui_tasks_draw
}

ui_task_dump_failure() {
    local id="$1" label="$2" log="$3"
    say ""
    printf '  %s%s %s%s\n' "$C_ERR" "$TASK_FAIL" "$label" "$C_RESET"
    printf '  %s--- last lines of the %s log ---%s\n' "$C_MUTED" "$id" "$C_RESET"
    tail -n 12 "$log" 2>/dev/null | sed 's/^/    /' || true
}

# ui_task_run <index> <id> <label> — run one component, updating the list.
ui_task_run() {
    local idx="$1" id="$2" label="$3" log rc=0
    TASK_STATES[idx]=running; TASK_START[idx]=$SECONDS
    if ui_tasks_supported; then
        ui_tasks_draw
        ui_task_ticker_start
        log="$TASK_LOG_DIR/$id.log"; : > "$log"
        ( run_component "$id" ) >>"$log" 2>&1 || rc=$?
        ui_task_ticker_stop
        if (( rc == 0 )); then TASK_STATES[idx]=done; else TASK_STATES[idx]=failed; fi
        ui_tasks_draw
        if (( rc != 0 )); then
            ui_task_dump_failure "$id" "$label" "$log"
            return "$rc"
        fi
        return 0
    fi
    # Non-live path: print the label wrapped to the terminal width so a long
    # (e.g. translated) component name never overflows a narrow/piped output.
    printf '  %s%s%s ' "$C_ACCENT" "$TASK_RUN" "$C_RESET"
    ui_wrap_first "     " "$(( $(ui_cols) - 5 ))" "$label ..."
    run_component "$id" || rc=$?
    if (( rc == 0 )); then
        printf '  %s%s%s ' "$C_OK" "$TASK_DONE" "$C_RESET"
        ui_wrap_first "     " "$(( $(ui_cols) - 5 ))" "$label"
        return 0
    fi
    printf '  %s%s%s ' "$C_ERR" "$TASK_FAIL" "$C_RESET"
    ui_wrap_first "     " "$(( $(ui_cols) - 5 ))" "$label"
    return "$rc"
}

run_install_phase() {
    local -a ids=() labels=(); local i
    for i in "${!COMP_IDS[@]}"; do
        [[ "$(decision_of "${COMP_IDS[i]}")" == "yes" ]] || continue
        ids+=("${COMP_IDS[i]}"); labels+=("${COMP_LABELS[i]}")
    done
    if (( ${#ids[@]} == 0 )); then
        note "no components selected; nothing to install"
        return 0
    fi
    if ui_tasks_supported; then
        TASK_LOG_DIR="${TMP:-${TMPDIR:-/tmp}}/task-logs"
        mkdir -p "$TASK_LOG_DIR"
        ui_tasks_init "${labels[@]}"
    fi
    for i in "${!ids[@]}"; do
        if ! ui_task_run "$i" "${ids[i]}" "${labels[i]}"; then
            die "component failed: ${ids[i]}"
        fi
    done
    TASK_ACTIVE=0
    if ui_tasks_supported; then ui_rule; fi
    return 0
}

# macOS has its own, much smaller path: the .dmg from the release page plus the
# self-installing app. It is dispatched near the top of this script (before the
# i18n/UI sections, so it also runs under macOS's bash 3.2); the code below is
# the Linux (Wayland/systemd) wizard and is never reached on Darwin.

# --- spinner + downloads --------------------------------------------------- #

SPIN_PID=""
spin_start() {
    ui_anim_ok || return 0
    (( TASK_ACTIVE )) && return 0     # the task list already shows progress
    local msg="$1" frames="$SPIN_FRAMES" i=0
    (
        trap 'exit 0' TERM INT
        while :; do
            printf '\r%s%s%s %s' "$C_ACCENT" "${frames:i:1}" "$C_RESET" "$msg" >&2
            i=$(( (i + 1) % ${#frames} ))
            sleep 0.12
        done
    ) &
    SPIN_PID=$!
    return 0
}

spin_stop() {
    [[ -n "$SPIN_PID" ]] || return 0
    kill "$SPIN_PID" 2>/dev/null || true
    wait "$SPIN_PID" 2>/dev/null || true
    SPIN_PID=""
    printf '\r\033[K' >&2
    return 0
}

# ui_spin_run <message> <command...> — run a long command under the spinner
ui_spin_run() {
    local msg="$1"; shift
    if ui_gum_ok; then
        local grc=0
        gum spin --spinner line --title "$msg" -- "$@" || grc=$?
        return "$grc"
    fi
    if (( TASK_ACTIVE )); then
        "$@"
        return $?
    fi
    spin_start "$msg"
    local rc=0
    "$@" || rc=$?
    spin_stop
    return "$rc"
}

# ui_download <url> <dest> — download with the best available progress display
ui_download() {
    local url="$1" dest="$2" rc=0
    if ui_gum_ok; then
        gum spin --spinner line --title "downloading $(basename "$url")" -- \
            curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url" || rc=$?
        return "$rc"
    fi
    if (( TASK_ACTIVE )); then
        # The task list owns the screen; stay quiet so the log stays clean.
        curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url"
        return $?
    fi
    if ui_anim_ok; then
        curl -fL --retry 3 --retry-delay 2 --progress-bar -o "$dest" "$url" >&2 || rc=$?
        return "$rc"
    fi
    curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url"
}

# ui_gum_ask <default y|n> <prompt> — gum-backed prompt that keeps y/n/a/s/q
ui_gum_ask() {
    local def="$1" prompt="$2" choice=""
    local -a opts
    if [[ "$def" == "y" ]]; then
        opts=("Yes (recommended)" "No" "Yes to all remaining" "Skip all remaining" "Quit")
    else
        opts=("No (recommended)" "Yes" "Yes to all remaining" "Skip all remaining" "Quit")
    fi
    if ! choice="$(gum choose --header "$prompt" "${opts[@]}")"; then
        QUIT=1
        return 1
    fi
    case "$choice" in
        "Yes"*)          return 0 ;;
        "No"*)           return 1 ;;
        "Yes to all"*)   ALL_YES=1; return 0 ;;
        "Skip all"*)     ALL_SKIP=1; return 1 ;;
        "Quit"*)         QUIT=1; return 1 ;;
        *)               [[ "$def" == "y" ]] && return 0 || return 1 ;;
    esac
}

# --------------------------------------------------------------------------- #
# section: paths
# --------------------------------------------------------------------------- #
BIN_DIR="$PREFIX/bin"
SHARE_DIR="$PREFIX/share/utter"
# The model store sits beside the install tree, not inside it, so removing
# "$SHARE_DIR" on uninstall never deletes downloaded models. --purge removes it.
MODELS_DIR="${UTTER_MODELS:-${XDG_DATA_HOME:-$HOME/.local/share}/utter-models}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/utter"
STATE_FILE="$STATE_DIR/install.json"
COMP_DIR="$STATE_DIR/components"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/utter"
CONFIG_FILE="$CONFIG_DIR/config.toml"
GUI_BIN="$BIN_DIR/utter-gui"
ASSISTANT_BIN="$BIN_DIR/assistant"
DESKTOP_FILE="$APPS_DIR/utter-gui.desktop"
RUNNER_UNIT="$UNIT_DIR/utter-runner.service"
NOCTALIA_PLUGINS="${NOCTALIA_PLUGINS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins}"
NOCTALIA_DEST="$NOCTALIA_PLUGINS/utter"
SYMLINK_PATH="$HOME/.local/bin/utter-gui"
ICON_NAME="org.utter.settings"
ICON_THEME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
ICON_FILES=(
    "$ICON_THEME_DIR/32x32/apps/$ICON_NAME.png"
    "$ICON_THEME_DIR/64x64/apps/$ICON_NAME.png"
    "$ICON_THEME_DIR/128x128/apps/$ICON_NAME.png"
    "$ICON_THEME_DIR/256x256/apps/$ICON_NAME.png"
    "$ICON_THEME_DIR/scalable/apps/$ICON_NAME.svg"
)

TMP="$(mktemp -d)"
trap 'ui_on_exit; rm -rf "$TMP"' EXIT
trap 'ui_on_exit; exit 130' INT TERM

# --------------------------------------------------------------------------- #
# section: detection — arch + distro
# --------------------------------------------------------------------------- #
detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64) echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        *) echo "unknown" ;;
    esac
}
ARCH="$(detect_arch)"
[[ "$ARCH" != "unknown" ]] || die "unsupported architecture: $(uname -m)"

detect_pkg_mgr() {
    local id="" like=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        id="${ID:-}"; like="${ID_LIKE:-}"
    fi
    case " $id $like " in
        *" arch "*|*" cachyos "*|*" manjaro "*|*" endeavouros "*) echo "pacman"; return ;;
        *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*) echo "apt"; return ;;
        *" fedora "*|*" rhel "*|*" centos "*|*" nobara "*) echo "dnf"; return ;;
        *" opensuse "*|*" suse "*|*" sles "*) echo "zypper"; return ;;
    esac
    for c in pacman apt-get dnf zypper; do
        command -v "$c" >/dev/null 2>&1 && { echo "$c"; return; }
    done
    echo "unknown"
}
PKG_MGR="$(detect_pkg_mgr)"

DISTRO_ID="unknown"; DISTRO_LIKE=""
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-unknown}"; DISTRO_LIKE="${ID_LIKE:-}"
fi

# --------------------------------------------------------------------------- #
# section: system-dependency probe (used by the deps step)
# --------------------------------------------------------------------------- #
pkg_for() {
    # logical name -> per-distro package name ("" = not packaged / varies)
    local logical="$1"
    case "$PKG_MGR:$logical" in
        pacman:wtype)        echo "wtype" ;;
        pacman:ydotool)      echo "ydotool" ;;
        pacman:grim)         echo "grim" ;;
        pacman:wl-clipboard) echo "wl-clipboard" ;;
        pacman:pipewire)     echo "pipewire" ;;
        pacman:webkit2gtk)   echo "webkit2gtk-4.1" ;;
        pacman:libsoup)      echo "libsoup3" ;;
        pacman:keyd)         echo "keyd" ;;
        apt:wtype)           echo "wtype" ;;
        apt:ydotool)         echo "ydotool" ;;
        apt:grim)            echo "grim" ;;
        apt:wl-clipboard)    echo "wl-clipboard" ;;
        apt:pipewire)        echo "pipewire" ;;
        apt:webkit2gtk)      echo "libwebkit2gtk-4.1-0" ;;
        apt:libsoup)         echo "libsoup-3.0-0" ;;
        apt:keyd)            echo "" ;;
        dnf:wtype)           echo "wtype" ;;
        dnf:ydotool)         echo "ydotool" ;;
        dnf:grim)            echo "grim" ;;
        dnf:wl-clipboard)    echo "wl-clipboard" ;;
        dnf:pipewire)        echo "pipewire" ;;
        dnf:webkit2gtk)      echo "webkit2gtk4.1" ;;
        dnf:libsoup)         echo "libsoup3" ;;
        dnf:keyd)            echo "" ;;
        zypper:wtype)        echo "wtype" ;;
        zypper:ydotool)      echo "ydotool" ;;
        zypper:grim)         echo "grim" ;;
        zypper:wl-clipboard) echo "wl-clipboard" ;;
        zypper:pipewire)     echo "pipewire" ;;
        zypper:webkit2gtk)   echo "libwebkit2gtk-4_1-0" ;;
        zypper:libsoup)      echo "libsoup-3_0-0" ;;
        zypper:keyd)         echo "" ;;
        *)                   echo "" ;;
    esac
}

lib_present() {
    # lib_present <pkg-config-name> <ldconfig-substring>
    { command -v pkg-config >/dev/null 2>&1 && pkg-config --exists "$1" 2>/dev/null; } && return 0
    command -v ldconfig >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q "$2"
}

dep_present() {
    case "$1" in
        wtype)        command -v wtype >/dev/null 2>&1 ;;
        ydotool)      command -v ydotool >/dev/null 2>&1 ;;
        ydotoold)     command -v ydotoold >/dev/null 2>&1 ;;
        grim)         command -v grim >/dev/null 2>&1 ;;
        wl-clipboard) command -v wl-copy >/dev/null 2>&1 ;;
        pipewire)     command -v pw-play >/dev/null 2>&1 || command -v pipewire >/dev/null 2>&1 ;;
        webkit2gtk)   lib_present "webkit2gtk-4.1" "libwebkit2gtk-4.1" ;;
        libsoup)      lib_present "libsoup-3.0" "libsoup-3.0" ;;
        systemd-user) _systemd_user_ok ;;
        keyd)         command -v keyd >/dev/null 2>&1 ;;
        *)            false ;;
    esac
}

_systemd_user_ok() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

DEP_REQUIRED=(wtype ydotool grim wl-clipboard pipewire webkit2gtk libsoup)
DEP_OPTIONAL=(keyd)

missing_pkgs() {
    # echo the mapped package names for missing required deps
    local out=() logical pkg
    for logical in "${DEP_REQUIRED[@]}"; do
        if ! dep_present "$logical"; then
            pkg="$(pkg_for "$logical")"
            [[ -n "$pkg" ]] && out+=("$pkg")
        fi
    done
    printf '%s\n' "${out[@]:-}"
}

# --------------------------------------------------------------------------- #
# section: detection — per-component probes
# --------------------------------------------------------------------------- #
command -v noctalia >/dev/null 2>&1 && NOCTALIA_PRESENT=1 || NOCTALIA_PRESENT=0
[[ -d "${XDG_DATA_HOME:-$HOME/.local/share}/noctalia" ]] && NOCTALIA_PRESENT=1

found_core() {
    if [[ -x "$ASSISTANT_BIN" || -d "$SHARE_DIR" ]]; then
        field_f "found:" "already present at {1}" "$SHARE_DIR"
    else
        field "found:" "not installed"
    fi
}

found_units() {
    if [[ -f "$RUNNER_UNIT" ]]; then
        field_f "found:" "unit installed ({1})" "$RUNNER_UNIT"
    elif _systemd_user_ok; then
        field "found:" "systemd --user available, no unit yet"
    else
        field "found:" "systemd --user unavailable"
    fi
}

found_gui() {
    if [[ -x "$GUI_BIN" ]]; then
        field_f "found:" "installed at {1}" "$GUI_BIN"
    elif [[ -x "$SYMLINK_PATH" ]]; then
        field_f "found:" "installed at {1}" "$SYMLINK_PATH"
    else
        field "found:" "not installed"
    fi
}

found_models() {
    local root="${UTTER_MODELS:-${XDG_DATA_HOME:-$HOME/.local/share}/utter-models}"
    local legacy="${XDG_DATA_HOME:-$HOME/.local/share}/utter/models"
    local n=0
    if [[ -d "$root/manifests" ]]; then
        n="$(find "$root/manifests" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
    fi
    if (( n == 0 )) && [[ -d "$legacy/manifests" ]]; then
        field_f "found:" "legacy models under {1} (migrated on first use)" "$legacy"
    else
        field_f "found:" "{1} model manifest(s) under {2}" "$n" "$root"
    fi
}

found_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        field_f "found:" "exists ({1})" "$CONFIG_FILE"
    else
        field "found:" "not present"
    fi
}

found_stt() {
    local parts=()
    command -v whisper-cli >/dev/null 2>&1 && parts+=("whisper-cli")
    command -v whisper-cpp >/dev/null 2>&1 && parts+=("whisper-cpp")
    command -v whisper >/dev/null 2>&1 && parts+=("whisper")
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import faster_whisper' >/dev/null 2>&1; then
        parts+=("faster-whisper (python)")
    fi
    if (( ${#parts[@]} )); then
        field "found:" "${parts[*]}"
    else
        field "found:" "no STT backend detected"
    fi
}

found_perception() {
    local parts=()
    command -v vulkaninfo >/dev/null 2>&1 && parts+=("vulkaninfo")
    [[ -e /dev/accel ]] && parts+=("accel devices")
    command -v nvidia-smi >/dev/null 2>&1 && parts+=("nvidia-smi")
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import vllm' >/dev/null 2>&1 && parts+=("vllm (python)")
        python3 -c 'import transformers' >/dev/null 2>&1 && parts+=("transformers (python)")
    fi
    if (( ${#parts[@]} )); then
        field "found:" "${parts[*]}"
    else
        field "found:" "no perception/vision server deps detected"
    fi
}

found_noctalia() {
    if (( NOCTALIA_PRESENT )); then
        field "found:" "Noctalia detected"
        [[ -d "$NOCTALIA_DEST" ]] && sub_f "widget already at {1}" "$NOCTALIA_DEST"
    else
        field "found:" "Noctalia not detected"
    fi
}

found_deps() {
    local present=() miss=() logical
    for logical in "${DEP_REQUIRED[@]}"; do
        if dep_present "$logical"; then present+=("$logical"); else miss+=("$logical"); fi
    done
    field_f "found:" "present: {1}" "${present[*]:-none}"
    sub_f "missing: {1}" "${miss[*]:-none}"
}

found_lang() {
    local syscode
    syscode="$(resolve_system_language)"
    if [[ -n "$syscode" ]]; then
        field_f "found:" "system language {1}" "$syscode"
    else
        field "found:" "no system language (C/POSIX); English default"
    fi
    sub "English ships inline; other languages need an opt-in download"
}

run_dep_probe() {
    case "$1" in
        deps)        found_deps ;;
        core)        found_core ;;
        lang)        found_lang ;;
        units)       found_units ;;
        models)      found_models ;;
        gui)         found_gui ;;
        stt)         found_stt ;;
        perception)  found_perception ;;
        noctalia)    found_noctalia ;;
        config)      found_config ;;
    esac
}

# --------------------------------------------------------------------------- #
# section: component registry
# --------------------------------------------------------------------------- #
COMP_IDS=(deps core lang units models gui stt perception noctalia config)
COMP_LABELS=(
    "System deps"
    "Core runner + CLI"
    "Language"
    "systemd user units"
    "Models"
    "GUI"
    "STT backend"
    "Perception (vision server deps)"
    "Noctalia widget (optional)"
    "Config"
)
COMP_WHAT=(
    "Wayland/input/audio tools and libs (wtype, ydotool, grim, wl-clipboard, pipewire, webkit2gtk-4.1, libsoup-3.0)"
    "protocol + reference runner + assistant CLI + bundled plugins"
    "spoken language (STT/TTS) and optional per-language downloads"
    "utter-runner.service user unit (+ optional enable & start)"
    "recommended STT / decision-head / vision models (always the user's choice)"
    "Tauri settings window (AppImage to \$PREFIX/bin, .desktop entry)"
    "speech-to-text backend (faster-whisper or a whisper.cpp build)"
    "vision grounding server deps (UI-TARS via vLLM / transformers)"
    "optional bar widget, attention panel and OSD for the Noctalia shell"
    "~/.config/utter/config.toml from the shipped default"
)
COMP_SIZE=(
    "varies (distro packages)"
    "~6 MB download"
    "English ships inline; downloads opt-in"
    "<10 KB"
    "several GB per accepted tier"
    "release AppImage (tens of MB)"
    "varies (existing install or your own)"
    "varies (vLLM/transformers stack)"
    "<100 KB"
    "<10 KB"
)
COMP_SUDO=(1 0 0 0 0 0 0 0 0 0)

# Translate the static component tables once, in place, so every consumer
# (preview table, width computation, wizard headings, plan) sees the localized
# text. Values that have no translation stay English.
i18n_localize_components() {
    local i v
    for i in "${!COMP_LABELS[@]}"; do COMP_LABELS[i]="$(l10n "${COMP_LABELS[i]}")"; done
    for i in "${!COMP_WHAT[@]}";   do COMP_WHAT[i]="$(l10n "${COMP_WHAT[i]}")"; done
    for i in "${!COMP_SIZE[@]}";   do COMP_SIZE[i]="$(l10n "${COMP_SIZE[i]}")"; done
}
i18n_localize_components

TOTAL=${#COMP_IDS[@]}
DECISION=()      # yes | skip (indexed like COMP_IDS)
ENABLE_UNITS=0
OVERWRITE_CONFIG=0
MODELS_YES=""    # csv of accepted tier keys
LANG_CODE=""     # chosen spoken language, normalized (e.g. en-GB); empty = English
LANG_TTS_VOICE=""  # voice name/path to write to [tts] voice (non-English only)
LANG_STT_SRC=""  # source for the multilingual STT model, if offered/accepted
LANG_TTS_SRC=""  # source for a TTS voice model, if offered/accepted
LANG_UI_PACK=""  # source for a UI localization pack, if offered/accepted
LANG_ACCEPT=()   # csv of accepted language downloads: stt,tts,ui
LANG_DEFAULT="English (default)"

# The release publishes x86_64 GUI assets only.
GUI_AVAILABLE=1
[[ "$ARCH" == "amd64" ]] || GUI_AVAILABLE=0

# decision_of <id> — the recorded decision ("yes" | "skip") for a component id;
# "skip" when the component is unknown or was never reached. Decisions are
# looked up by id so reordering/inserting components cannot silently shift a
# hardcoded numeric index.
decision_of() {
    local want="$1" i
    for i in "${!COMP_IDS[@]}"; do
        if [[ "${COMP_IDS[i]}" == "$want" ]]; then
            printf '%s' "${DECISION[i]:-skip}"
            return 0
        fi
    done
    printf 'skip'
}

# --only / --skip
declare -A ONLY_MAP=() SKIP_MAP=()
if [[ -n "$ONLY_CSV" ]]; then
    IFS=, read -ra _only <<<"$ONLY_CSV"
    for c in "${_only[@]}"; do
        c="${c// /}"; [[ -n "$c" ]] && ONLY_MAP["$c"]=1
    done
fi
if [[ -n "$SKIP_CSV" ]]; then
    IFS=, read -ra _skip <<<"$SKIP_CSV"
    for c in "${_skip[@]}"; do
        c="${c// /}"; [[ -n "$c" ]] && SKIP_MAP["$c"]=1
    done
fi

allowed() {
    local id="$1"
    [[ -n "${SKIP_MAP[$id]:-}" ]] && return 1
    if (( ${#ONLY_MAP[@]} )); then
        [[ -n "${ONLY_MAP[$id]:-}" ]] || return 1
    fi
    return 0
}

# --------------------------------------------------------------------------- #
# section: release resolution
# --------------------------------------------------------------------------- #
VER=""; VER_NUM=""; BASE_URL=""
resolve_release() {
    if [[ -n "$UTTER_BASE_URL" ]]; then
        BASE_URL="${UTTER_BASE_URL%/}"
        [[ "$UTTER_VERSION" == "latest" ]] && \
            die "UTTER_BASE_URL is set but UTTER_VERSION=latest; set UTTER_VERSION"
        VER="$UTTER_VERSION"
    else
        if [[ "$UTTER_VERSION" == "latest" ]]; then
            local api="https://api.github.com/repos/$UTTER_REPO/releases/latest"
            if (( DRY_RUN )); then
                VER="<latest>"
            else
                say_f "  querying: {1}" "$api"
                # `|| true` keeps a failed request from tripping `set -e` so the
                # friendly error below is the one the user sees.
                VER="$(curl -fsSL "$api" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1 || true)"
                [[ -n "$VER" ]] || die "$(t "could not resolve the latest release for {1}" "$UTTER_REPO")"
            fi
        else
            VER="$UTTER_VERSION"
        fi
        BASE_URL="https://github.com/$UTTER_REPO/releases/download/$VER"
    fi
    VER_NUM="${VER#v}"
}

# asset names (stable convention)
GUI_APPIMAGE=""; GUI_DEB=""; GUI_RPM=""; CORE_TARBALL=""; SUMS="sha256sums.txt"
set_asset_names() {
    GUI_APPIMAGE="utter-gui_${VER_NUM}_${ARCH}.AppImage"
    GUI_DEB="utter-gui_${VER_NUM}_${ARCH}.deb"
    GUI_RPM="utter-gui-${VER_NUM}-1.x86_64.rpm"
    CORE_TARBALL="utter-core-${VER_NUM}.tar.gz"
}

# --------------------------------------------------------------------------- #
# section: download + verify
# --------------------------------------------------------------------------- #
SUMS_FETCHED=0
CORE_FETCHED=0
GUI_FETCHED=0
GUI_ASSET=""

fetch() {
    # fetch <asset> — download to $TMP/<asset>. A marker file makes the cache
    # survive when components run in subshells (live task list).
    local asset="$1"
    local url="$BASE_URL/$asset"
    if (( DRY_RUN )); then
        say_f "  [dry-run] download {1}" "$url"
        return 0
    fi
    [[ -f "$TMP/.fetched/$asset" ]] && return 0
    say_f "  [get] {1}" "$url"
    ui_download "$url" "$TMP/$asset" || die "$(t "download failed: {1}" "$url")"
    mkdir -p "$TMP/.fetched"; : > "$TMP/.fetched/$asset"
}

verify() {
    # verify <asset> — check against sha256sums.txt
    local asset="$1"
    if (( DRY_RUN )); then
        say_f "  [dry-run] verify sha256 of {1} against {2}" "$asset" "$SUMS"
        return 0
    fi
    [[ -f "$TMP/$SUMS" ]] || die "$(t "missing {1} (cannot verify {2})" "$SUMS" "$asset")"
    local want got
    want="$(awk -v a="$asset" '$2==a || $2=="*"a {print $1}' "$TMP/$SUMS" | head -1)"
    [[ -n "$want" ]] || die "$(t "{1} not listed in {2}" "$asset" "$SUMS")"
    got="$(sha256sum "$TMP/$asset" | awk '{print $1}')"
    if [[ "$want" != "$got" ]]; then
        die "$(t "sha256 mismatch for {1}: want {2} got {3}" "$asset" "$want" "$got")"
    fi
    ok_f "sha256 {1}{2} {3}" "${got:0:16}" "$GL_ELL" "$asset"
}

ensure_sums() {
    (( SUMS_FETCHED )) && return 0
    fetch "$SUMS"
    SUMS_FETCHED=1
}

fetch_core() {
    (( CORE_FETCHED )) && return 0
    ensure_sums
    fetch "$CORE_TARBALL"
    verify "$CORE_TARBALL"
    CORE_FETCHED=1
}

choose_gui_asset() {
    if [[ "$MODE" == "appimage" ]]; then
        GUI_ASSET="$GUI_APPIMAGE"
    elif [[ "$PKG_MGR" == "apt" ]]; then
        GUI_ASSET="$GUI_DEB"
    elif [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "zypper" ]]; then
        GUI_ASSET="$GUI_RPM"
    else
        GUI_ASSET="$GUI_APPIMAGE"
        note "no native package manager for --package; falling back to AppImage"
        MODE="appimage"
    fi
}

fetch_gui() {
    (( GUI_FETCHED )) && return 0
    ensure_sums
    fetch "$GUI_ASSET"
    verify "$GUI_ASSET"
    GUI_FETCHED=1
}

CORE_TMP_ROOT=""
extract_core_tmp() {
    # Set CORE_TMP_ROOT to the extracted top-level directory (shared temp copy).
    # The marker keeps the cache across components that run in subshells.
    [[ -n "$CORE_TMP_ROOT" ]] && return 0
    if [[ -f "$TMP/.core-root" ]]; then
        IFS= read -r CORE_TMP_ROOT < "$TMP/.core-root" || true
        [[ -n "$CORE_TMP_ROOT" ]] && return 0
    fi
    fetch_core
    if (( DRY_RUN )); then
        CORE_TMP_ROOT="$TMP/extract/<core>"
        return 0
    fi
    mkdir -p "$TMP/extract"
    ui_spin_run "extracting $CORE_TARBALL" tar -xzf "$TMP/$CORE_TARBALL" -C "$TMP/extract"
    CORE_TMP_ROOT="$(find "$TMP/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [[ -n "$CORE_TMP_ROOT" ]] || die "core tarball has no top-level directory"
    printf '%s\n' "$CORE_TMP_ROOT" > "$TMP/.core-root"
}

ensure_core_context() {
    # Set CORE_CONTEXT to an extracted core tree (installed tree preferred).
    if [[ -d "$SHARE_DIR/assistant" ]]; then
        CORE_CONTEXT="$SHARE_DIR"
    else
        extract_core_tmp
        CORE_CONTEXT="$CORE_TMP_ROOT"
    fi
}
CORE_CONTEXT=""

# --------------------------------------------------------------------------- #
# section: prompts
# --------------------------------------------------------------------------- #
ALL_YES=0
ALL_SKIP=0
QUIT=0

ask_yn() {
    # ask_yn <default y|n> <prompt> ; return 0 = yes, 1 = no; sets QUIT/ALL_*
    local def="$1" prompt="$2"
    local hint="[Y/n]"; [[ "$def" == "n" ]] && hint="[y/N]"
    if (( UI_DEPTH > 0 )); then
        if [[ "$def" == "y" ]]; then
            hint="[${C_BOLD}${C_ACCENT}Y${C_RESET}${C_DIM}/n${C_RESET}]"
        else
            hint="[${C_DIM}y/${C_BOLD}${C_ACCENT}N${C_RESET}]"
        fi
    fi
    local ans=""
    if (( ALL_YES )); then printf '%s %s ' "$prompt" "$hint"; say "y (all remaining)"; return 0; fi
    if (( ALL_SKIP )); then printf '%s %s ' "$prompt" "$hint"; say "n (skip all remaining)"; return 1; fi
    if ui_gum_ok; then
        local rc=0
        ui_gum_ask "$def" "$prompt" || rc=$?
        return "$rc"
    fi
    while true; do
        printf '%s %s ' "$prompt" "$hint"
        IFS= read -r ans || ans=""
        ans="${ans//[[:space:]]/}"
        case "${ans,,}" in
            "")    [[ "$def" == "y" ]] && return 0 || return 1 ;;
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            a|all) ALL_YES=1; return 0 ;;
            s|skip) ALL_SKIP=1; return 1 ;;
            q|quit) QUIT=1; return 1 ;;
            *) warn "please answer y, n, a, s, or q" ;;
        esac
    done
}

announce_default() {
    # announce_default <y|n>
    if [[ "$1" == "y" ]]; then say "  default: yes (recommended)"; else say "  default: no (recommended)"; fi
}

# --------------------------------------------------------------------------- #
# section: install-state (per-component records; marker dirs, no JSON in bash)
# --------------------------------------------------------------------------- #
D_FILES=(); D_DIRS=(); D_UNITS=(); D_PACKAGES=(); D_KEEP=0

reset_record() { D_FILES=(); D_DIRS=(); D_UNITS=(); D_PACKAGES=(); D_KEEP=0; }

record_component() {
    # record_component <id> <label> <version> <method> <sudo 0|1> <assistant>
    local id="$1" label="$2" version="$3" method="$4" sudo="$5" assistant="$6"
    local dir="$COMP_DIR/$id"
    if (( DRY_RUN )); then
        say_f "  [dry-run] record component {1} -> {2}" "$id" "$dir"
        return 0
    fi
    mkdir -p "$dir"
    printf '%s\n' "$label"     > "$dir/label"
    printf '%s\n' "$version"   > "$dir/version"
    printf '%s\n' "$method"    > "$dir/method"
    printf '%s\n' "$sudo"      > "$dir/sudo"
    printf '%s\n' "$assistant" > "$dir/assistant"
    printf '%s\n' "$D_KEEP"    > "$dir/keep"
    : > "$dir/files"
    local x
    for x in "${D_FILES[@]:-}";    do [[ -n "$x" ]] && printf '%s\n' "$x" >> "$dir/files";    done
    : > "$dir/dirs"
    for x in "${D_DIRS[@]:-}";     do [[ -n "$x" ]] && printf '%s\n' "$x" >> "$dir/dirs";     done
    : > "$dir/units"
    for x in "${D_UNITS[@]:-}";    do [[ -n "$x" ]] && printf '%s\n' "$x" >> "$dir/units";    done
    : > "$dir/packages"
    for x in "${D_PACKAGES[@]:-}"; do [[ -n "$x" ]] && printf '%s\n' "$x" >> "$dir/packages"; done
    return 0
}

rebuild_install_json() {
    if (( DRY_RUN )); then
        say_f "  [dry-run] write {1}" "$STATE_FILE"
        return 0
    fi
    command -v python3 >/dev/null 2>&1 || { warn "python3 missing; per-component state kept, install.json not regenerated"; return 0; }
    mkdir -p "$STATE_DIR"
    python3 - "$COMP_DIR" "$STATE_FILE" "$VER_NUM" "$ARCH" "$PREFIX" "$ASSISTANT_BIN" <<'PY'
import glob, json, os, sys
from datetime import datetime, timezone

comp_dir, out, ver, arch, prefix, assistant = sys.argv[1:7]
files, units, packages, components = [], [], [], {}

def read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [ln for ln in fh.read().splitlines() if ln]
    except OSError:
        return []

for d in sorted(glob.glob(os.path.join(comp_dir, "*"))):
    if not os.path.isdir(d):
        continue
    cid = os.path.basename(d)
    comp = {
        "label": (read_lines(os.path.join(d, "label")) or [cid])[0],
        "version": (read_lines(os.path.join(d, "version")) or [""])[0],
        "method": (read_lines(os.path.join(d, "method")) or [""])[0],
        "sudo": (read_lines(os.path.join(d, "sudo")) or ["0"])[0] == "1",
        "assistant": (read_lines(os.path.join(d, "assistant")) or [""])[0],
        "keep": (read_lines(os.path.join(d, "keep")) or ["0"])[0] == "1",
        "files": read_lines(os.path.join(d, "files")),
        "dirs": read_lines(os.path.join(d, "dirs")),
        "units": read_lines(os.path.join(d, "units")),
        "packages": read_lines(os.path.join(d, "packages")),
    }
    components[cid] = comp
    for item, bucket in ((comp["files"], files), (comp["units"], units), (comp["packages"], packages)):
        for v in item:
            if v and v not in bucket:
                bucket.append(v)

data = {
    "version": ver,
    "schema": "utter-install-state/2",
    "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "method": "bootstrap-wizard",
    "release": ver,
    "arch": arch,
    "prefix": prefix,
    "assistant": assistant,
    "protocol": "1.0",
    "files": files,
    "units": units,
    "packages": packages,
    "components": components,
}
tmp = out + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.replace(tmp, out)
PY
    ok_f "wrote {1}" "$STATE_FILE"
}

# --------------------------------------------------------------------------- #
# section: plan + banner
# --------------------------------------------------------------------------- #
print_banner() {
    ui_banner
    local iver="${VER:-$UTTER_VERSION}"
    if (( $(ui_cols) < 48 )); then
        say_f "  installer · Linux (Wayland) · {1}" "$iver"
    else
        printf '  %sinstaller%s · Linux (Wayland) · %s%s%s\n' \
            "$C_BOLD" "$C_RESET" "$C_MUTED" "$iver" "$C_RESET"
    fi
    ui_rule
    field "distro" "$DISTRO_ID${DISTRO_LIKE:+ (like: $DISTRO_LIKE)}"
    field "arch" "$ARCH"
    field "prefix" "$PREFIX"
    field "pkg mgr" "$PKG_MGR"
    field "mode" "$MODE"
    field "release" "${VER:-$UTTER_VERSION}"
    field "python" "${UTTER_PYTHON:-auto-detected}"
}

# Width of the component-label column, shared by the preview and plan tables.
comp_label_width() {
    local w=0 i
    for i in "${!COMP_LABELS[@]}"; do
        (( ${#COMP_LABELS[i]} > w )) && w=${#COMP_LABELS[i]}
    done
    (( w < 24 )) && w=24
    printf '%s' "$w"
}

print_component_preview() {
    say ""
    say "Components (this installer walks them one by one):"
    local i w def cols; w="$(comp_label_width)"; cols="$(ui_cols)"
    if (( cols < 56 )); then
        ui_rule "$(( cols - 2 ))"
        for i in "${!COMP_IDS[@]}"; do
            say "  $((i+1))   ${COMP_LABELS[i]}"
        done
        return 0
    fi
    if [[ -n "$GL_H" ]]; then
        printf '  %s%-3s %-*s %-*s %s%s\n' "$C_MUTED" "#" "$w" "component" 8 "default" "size" "$C_RESET"
    else
        printf '  %-3s %-*s %-*s %s\n' "#" "$w" "component" 8 "default" "size"
    fi
    ui_rule "$(( w + 24 ))"
    for i in "${!COMP_IDS[@]}"; do
        def="${REC_BY_ID[${COMP_IDS[i]}]:-n}"
        [[ "$def" == "y" ]] && def="yes" || def="no"
        printf '  %-3s %-*s %-*s %s\n' "$((i+1))" "$w" "${COMP_LABELS[i]}" 8 "$def" "${COMP_SIZE[i]}"
    done
}

print_plan() {
    print_banner
    print_component_preview
    say ""
    say "Recommended defaults: core, systemd units and GUI; the language step is"
    say "English (inline, no downloads); models/STT/perception are opt-in."
    say "Nothing is downloaded or changed until you confirm."
}

# --------------------------------------------------------------------------- #
# section: uninstall
# --------------------------------------------------------------------------- #
read_component_field() {
    # read_component_field <dir> <field>
    local f="$1/$2"
    [[ -f "$f" ]] && head -1 "$f" || true
}

do_uninstall() {
    section "uninstall"
    say_f "  prefix: {1}" "$PREFIX"

    local dirs=()
    if [[ -d "$COMP_DIR" ]]; then
        while IFS= read -r d; do dirs+=("$d"); done \
            < <(find "$COMP_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    fi

    # Legacy state (installed by an older installer): fall back to known paths.
    # Without per-component records there is no menu to pick from, so require an
    # explicit --yes (or --dry-run) before touching anything.
    if (( ${#dirs[@]} == 0 )); then
        if (( ! ASSUME_YES && ! DRY_RUN )); then
            note "no per-component install-state found; the classic bootstrap paths are:"
            sub "$GUI_BIN"
            sub "$ASSISTANT_BIN"
            sub "$DESKTOP_FILE"
            sub "$RUNNER_UNIT"
            sub "$SHARE_DIR"
            say ""
            say "Nothing removed. Re-run with --yes to remove them:"
            say "    curl -fsSL <install.sh-url> | bash -s -- --uninstall --yes"
            return 0
        fi
        do_uninstall_legacy
        return 0
    fi

    local i id label
    say ""
    say "Installed components:"
    for i in "${!dirs[@]}"; do
        id="$(basename "${dirs[i]}")"
        label="$(read_component_field "${dirs[i]}" label)"
        local keep=""; [[ "$(read_component_field "${dirs[i]}" keep)" == "1" ]] && keep=" (kept by default)"
        printf '  %d) %-16s %s%s\n' "$((i+1))" "$id" "${label:-$id}" "$keep"
    done

    if (( ! ASSUME_YES && ! DRY_RUN )) && ! is_tty; then
        say ""
        say "Nothing removed. Re-run with --yes to remove all installed components:"
        say "    curl -fsSL <install.sh-url> | bash -s -- --uninstall --yes"
        return 0
    fi

    local remove=()
    if (( ASSUME_YES )); then
        for i in "${!dirs[@]}"; do
            [[ "$(read_component_field "${dirs[i]}" keep)" == "1" ]] && continue
            remove+=("${dirs[i]}")
        done
    elif ui_gum_ok; then
        local -a menu=() picked=()
        local line out=""
        for i in "${!dirs[@]}"; do
            id="$(basename "${dirs[i]}")"
            label="$(read_component_field "${dirs[i]}" label)"
            [[ "$(read_component_field "${dirs[i]}" keep)" == "1" ]] && label="$label (kept by default)"
            menu+=("${id}  ${label:-$id}")
        done
        if ! out="$(gum choose --no-limit \
                --header "Select components to remove (nothing selected = all except kept)" \
                "${menu[@]}")"; then
            say "Aborted; nothing removed."
            return 0
        fi
        while IFS= read -r line; do
            [[ -n "$line" ]] && picked+=("$line")
        done <<<"$out"
        if (( ${#picked[@]} == 0 )); then
            for i in "${!dirs[@]}"; do
                [[ "$(read_component_field "${dirs[i]}" keep)" == "1" ]] && continue
                remove+=("${dirs[i]}")
            done
        else
            local p
            for p in "${picked[@]}"; do
                id="${p%% *}"
                for i in "${!dirs[@]}"; do
                    [[ "$(basename "${dirs[i]}")" == "$id" ]] && remove+=("${dirs[i]}")
                done
            done
        fi
    else
        local selection=""
        printf '\nSelect components to remove [Enter = all except kept, numbers/comma, a = all, q = quit]: '
        IFS= read -r selection || selection=""
        selection="${selection// /}"
        case "${selection,,}" in
            q|quit) say "Aborted; nothing removed."; return 0 ;;
        esac
        if [[ "${selection,,}" == "all" || "${selection,,}" == "a" || -z "$selection" ]]; then
            for i in "${!dirs[@]}"; do
                [[ "$(read_component_field "${dirs[i]}" keep)" == "1" ]] && continue
                remove+=("${dirs[i]}")
            done
        else
            local -A want=()
            IFS=, read -ra nums <<<"$selection"
            for n in "${nums[@]}"; do
                [[ "$n" =~ ^[0-9]+$ ]] || continue
                if (( n >= 1 && n <= ${#dirs[@]} )); then
                    want["${dirs[$((n-1))]}"]=1
                fi
            done
            for d in "${dirs[@]}"; do [[ -n "${want[$d]:-}" ]] && remove+=("$d"); done
        fi
    fi

    if (( ${#remove[@]} == 0 )); then
        say "No components selected; nothing removed."
        return 0
    fi

    section "removing"
    local d cid
    for d in "${remove[@]}"; do
        cid="$(basename "$d")"
        say_f "  - {1}" "$cid"
        remove_component "$d"
        if (( DRY_RUN )); then
            say_f "  [dry-run] remove record {1}" "$d"
        else
            rm -rf "$d"
        fi
    done

    if command -v systemctl >/dev/null 2>&1; then
        run "reload systemd user manager" systemctl --user daemon-reload || true
    fi

    if (( ! DRY_RUN )); then
        if [[ -d "$COMP_DIR" ]] && [[ -z "$(ls -A "$COMP_DIR" 2>/dev/null)" ]]; then
            rmdir "$COMP_DIR" 2>/dev/null || true
        fi
        if [[ ! -d "$COMP_DIR" || -z "$(ls -A "$COMP_DIR" 2>/dev/null)" ]]; then
            rm -f "$STATE_FILE" 2>/dev/null || true
        else
            rebuild_install_json
        fi
    fi

    if (( PURGE )); then
        if [[ -d "$MODELS_DIR" ]]; then
            run "--purge: remove downloaded models $MODELS_DIR" rm -rf "$MODELS_DIR"
        else
            note "no models dir at $MODELS_DIR"
        fi
    else
        note "downloaded models kept at $MODELS_DIR (pass --uninstall --purge to remove)"
    fi

    section "done"
    if (( PURGE )); then
        say_f "Uninstalled. User config in {1} and downloaded models were removed (--purge)." "$CONFIG_DIR"
    else
        say_f "Uninstalled. User config in {1} and downloaded models are kept." "$CONFIG_DIR"
    fi
}

remove_component() {
    local d="$1"
    local f u pkg line
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        run_f "remove {1}" "$line" rm -f "$line"
    done < <(read_component_lines "$d" files)
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        run_f "remove {1}" "$line" rm -rf "$line"
    done < <(read_component_lines "$d" dirs)
    while IFS= read -r u; do
        [[ -n "$u" ]] || continue
        if command -v systemctl >/dev/null 2>&1; then
            run_f "disable --now {1}" "$u" systemctl --user disable --now "$u" || true
        fi
    done < <(read_component_lines "$d" units)
    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue
        case "$PKG_MGR" in
            pacman) say_f "  to remove the package: sudo pacman -Rns {1}" "$pkg" ;;
            apt)    say_f "  to remove the package: sudo apt-get remove {1}" "$pkg" ;;
            dnf)    say_f "  to remove the package: sudo dnf remove {1}" "$pkg" ;;
            zypper) say_f "  to remove the package: sudo zypper remove {1}" "$pkg" ;;
            *)      say_f "  to remove the package: {1}" "$pkg" ;;
        esac
    done < <(read_component_lines "$d" packages)
}

read_component_lines() {
    local f="$1/$2"
    [[ -f "$f" ]] && cat "$f" || true
}

do_uninstall_legacy() {
    note "no per-component install-state found; removing the classic bootstrap paths"
    [[ -f "$GUI_BIN" ]] && run_f "remove {1}" "$GUI_BIN" rm -f "$GUI_BIN" || note "no GUI binary"
    [[ -L "$SYMLINK_PATH" ]] && run_f "remove {1}" "$SYMLINK_PATH" rm -f "$SYMLINK_PATH" || true
    [[ -f "$ASSISTANT_BIN" ]] && run_f "remove {1}" "$ASSISTANT_BIN" rm -f "$ASSISTANT_BIN" || note "no assistant wrapper"
    [[ -f "$DESKTOP_FILE" ]] && run_f "remove {1}" "$DESKTOP_FILE" rm -f "$DESKTOP_FILE" || note "no desktop file"
    for icon in "${ICON_FILES[@]}"; do
        [[ -f "$icon" ]] && run_f "remove {1}" "$icon" rm -f "$icon" || true
    done
    [[ -f "$RUNNER_UNIT" ]] && run_f "remove {1}" "$RUNNER_UNIT" rm -f "$RUNNER_UNIT" || note "no runner unit"
    if [[ -d "$SHARE_DIR" ]]; then
        run_f "remove {1}" "$SHARE_DIR" rm -rf "$SHARE_DIR"
    else
        note_f "no core tree at {1}" "$SHARE_DIR"
    fi
    if command -v systemctl >/dev/null 2>&1; then
        run "reload systemd user manager" systemctl --user daemon-reload || true
    fi
    [[ -f "$STATE_FILE" ]] && run_f "remove {1}" "$STATE_FILE" rm -f "$STATE_FILE" || true
    if (( PURGE )); then
        if [[ -d "$MODELS_DIR" ]]; then
            run "--purge: remove downloaded models $MODELS_DIR" rm -rf "$MODELS_DIR"
        else
            note "no models dir at $MODELS_DIR"
        fi
        section "done"
        say_f "Uninstalled. User config in {1} and models were removed (--purge)." "$CONFIG_DIR"
    else
        note "downloaded models kept at $MODELS_DIR"
        section "done"
        say_f "Uninstalled. User config in {1} and models are kept." "$CONFIG_DIR"
    fi
}

if (( UNINSTALL )); then
    do_uninstall
    exit 0
fi

# --------------------------------------------------------------------------- #
# section: recommendations (needed by the plan preview and the wizard)
# --------------------------------------------------------------------------- #
declare -A REC_BY_ID=()
compute_recommendations() {
    local miss; miss="$(missing_pkgs)"
    [[ -n "$miss" ]] && REC_BY_ID[deps]=y || REC_BY_ID[deps]=n
    REC_BY_ID[core]=y
    REC_BY_ID[lang]=y
    REC_BY_ID[units]=y
    REC_BY_ID[models]=n
    (( GUI_AVAILABLE )) && REC_BY_ID[gui]=y || REC_BY_ID[gui]=n
    REC_BY_ID[stt]=n
    REC_BY_ID[perception]=n
    REC_BY_ID[noctalia]=n
    (( WITH_NOCTALIA )) && REC_BY_ID[noctalia]=y
    [[ -f "$CONFIG_FILE" ]] && REC_BY_ID[config]=n || REC_BY_ID[config]=y
}
compute_recommendations

# --------------------------------------------------------------------------- #
# section: non-interactive gate (curl | bash with no --yes): plan only
# --------------------------------------------------------------------------- #
if (( ! ASSUME_YES && ! DRY_RUN )) && ! is_tty; then
    section "plan"
    print_plan
    say ""
    say "stdin is not a terminal, so the wizard was not started and nothing was changed."
    say "To install with all recommended defaults:"
    say "    curl -fsSL <install.sh-url> | bash -s -- --yes"
    say "To customise:"
    say "    curl -fsSL <install.sh-url> | bash -s -- --only core,gui --skip models --dry-run"
    say "Flags after '-s --' are honoured: --only <csv> --skip <csv> --dry-run"
    say "  --package --appimage --with-noctalia --uninstall --yes --help"
    exit 0
fi

# --------------------------------------------------------------------------- #
# section: release + asset names
# --------------------------------------------------------------------------- #
resolve_release
set_asset_names

# --------------------------------------------------------------------------- #
# section: interactive wizard
# --------------------------------------------------------------------------- #
print_banner

present_step() {
    local i="$1" id="$2"
    field "what" "${COMP_WHAT[i]}"
    field "size" "${COMP_SIZE[i]}"
    if (( COMP_SUDO[i] )) || { [[ "$id" == "gui" ]] && [[ "$MODE" == "package" ]]; }; then
        field "sudo" "yes (system package manager)"
    else
        field "sudo" "no"
    fi
    run_dep_probe "$id"
}

recommend_tiers() {
    # echo lines: key|title|size|reason
    local json=""
    if [[ -x "$ASSISTANT_BIN" ]]; then
        json="$("$ASSISTANT_BIN" recommend --json 2>/dev/null || true)"
    elif [[ -d "$SHARE_DIR/assistant" ]] && command -v python3 >/dev/null 2>&1; then
        json="$(cd "$SHARE_DIR" && python3 -m assistant recommend --json 2>/dev/null || true)"
    else
        local here; here="$(cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || echo "")"
        if [[ -n "$here" && -d "$here/assistant" ]] && command -v python3 >/dev/null 2>&1; then
            json="$(cd "$here" && python3 -m assistant recommend --json 2>/dev/null || true)"
        fi
    fi
    if [[ -n "$json" ]] && command -v python3 >/dev/null 2>&1; then
        if printf '%s' "$json" | python3 -c '
import json, sys
r = json.load(sys.stdin)
s = r.get("suggestions", {})

def size(d):
    if d.get("est_vram_gb"):
        return "~%d GB VRAM" % round(d["est_vram_gb"])
    if d.get("est_ram_gb"):
        return "~%d GB RAM" % round(d["est_ram_gb"])
    return "size varies"

stt = s.get("stt", {})
stt_title = "%s / %s (%s)" % (stt.get("backend", "?"), stt.get("model", "?"), stt.get("device", "?"))
print("stt", stt_title, size(stt), stt.get("reason", ""), sep="|")
llm = s.get("decision_llm", {})
llm_title = "%s %s" % (llm.get("model", "?"), llm.get("quant", ""))
print("decision", llm_title, size(llm), llm.get("reason", ""), sep="|")
vis = s.get("vision", {})
print("vision", vis.get("model", "?"), size(vis), vis.get("reason", ""), sep="|")
' 2>/dev/null; then
            return 0
        fi
    fi
    # Static fallback: core not installed yet, so describe the planned tiers.
    printf '%s\n' \
        "stt|STT|recommended whisper model (size varies)|see: assistant recommend" \
        "decision|Decision head|7-8B (q4/awq), ~6 GB|follows your GPU" \
        "vision|Vision|UI-TARS grounding, ~8 GB|follows your GPU"
}

MODEL_TIER_KEYS=()
MODEL_TIER_TITLES=()
MODEL_TIER_SIZES=()

# --------------------------------------------------------------------------- #
# section: language (spoken STT/TTS; English ships inline)
# --------------------------------------------------------------------------- #
# resolve_system_language — normalize LC_ALL/LC_MESSAGES/LANG to lang[-REGION]
# (en_GB.UTF-8 -> en-GB), or print nothing when the locale is C/POSIX/unknown.
resolve_system_language() {
    local raw="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}"
    raw="${raw%%@*}"
    raw="${raw%%.*}"
    [[ -n "$raw" ]] || return 0
    case "${raw^^}" in
        C|POSIX) return 0 ;;
    esac
    local lang="" rest="" script="" region=""
    lang="${raw%%[_-]*}"; rest="${raw#"$lang"}"; rest="${rest#[_-]}"
    case "$rest" in
        [A-Za-z][A-Za-z][A-Za-z][A-Za-z][_-]*) script="${rest%%[_-]*}"; rest="${rest#"$script"}"; rest="${rest#[_-]}" ;;
    esac
    case "$rest" in
        [A-Za-z][A-Za-z]|[0-9][0-9][0-9]) region="$rest" ;;
    esac
    lang="${lang,,}"
    if [[ -n "$script" ]]; then
        printf '%s-%s%s' "$lang" "${script^}" "${region:+-${region^^}}"
    else
        printf '%s%s' "$lang" "${region:+-${region^^}}"
    fi
}

# language env-key token: de-DE -> DE_DE, de -> DE
lang_env_token() {
    local code="$1"
    printf '%s' "${code^^}" | tr '-' '_'
}

# lang_env_source <prefix> <code> — UTTER_MODEL_STT_DE_DE first, then
# UTTER_MODEL_STT_DE, then the generic UTTER_MODEL_STT; print nothing when none
# is configured.
lang_env_source() {
    local prefix="$1" code="$2" token full short
    token="$(lang_env_token "$code")"
    full="$prefix"_"$token"
    short="$prefix"_"${token%%_*}"
    if [[ -n "${!full:-}" ]]; then printf '%s' "${!full}"; return 0; fi
    if [[ -n "${!short:-}" ]]; then printf '%s' "${!short}"; return 0; fi
    if [[ -n "${!prefix:-}" ]]; then printf '%s' "${!prefix}"; return 0; fi
    return 0
}

# lang_locale_pack <code> — an explicitly configured UI localization pack, or
# empty. There is no guessed default: a pack is only offered when the user (or
# a pack feed) provided UTTER_LOCALE_PACK_<LANG> / UTTER_LOCALE_PACK.
lang_locale_pack() {
    local code="$1" token lpack lgeneric
    token="$(lang_env_token "$code")"
    lpack="UTTER_LOCALE_PACK_$token"
    lgeneric="UTTER_LOCALE_PACK_${token%%_*}"
    if [[ -n "${!lpack:-}" ]]; then printf '%s' "${!lpack}"; return 0; fi
    if [[ -n "${!lgeneric:-}" ]]; then printf '%s' "${!lgeneric}"; return 0; fi
    if [[ -n "${UTTER_LOCALE_PACK:-}" ]]; then printf '%s' "${UTTER_LOCALE_PACK}"; return 0; fi
    return 0
}

# lang_voice_value <code> — voice to persist for a language: an explicit
# UTTER_TTS_VOICE_<LANG> override, else the language itself (espeak derives a
# voice from [tts] language when voice is empty).
lang_voice_value() {
    local code="$1" token v
    token="$(lang_env_token "$code")"
    v="UTTER_TTS_VOICE_$token"
    if [[ -n "${!v:-}" ]]; then printf '%s' "${!v}"; return 0; fi
    v="UTTER_TTS_VOICE_${token%%_*}"
    if [[ -n "${!v:-}" ]]; then printf '%s' "${!v}"; return 0; fi
    printf '%s' "$code"
}

# lang_chosen_label — human label for the current LANG_CODE.
lang_chosen_label() {
    [[ -n "$LANG_CODE" ]] && printf '%s (%s)' "$LANG_CODE" "$LANG_CODE" || printf '%s' "$LANG_DEFAULT"
}

# lang_offer_downloads — after a non-English language is chosen, OFFER each
# matching download (default No). Nothing is fetched unless the user accepts,
# and everything routes through `assistant models pull` via exec_lang.
lang_offer_downloads() {
    local code="$1"
    local stt_src tts_src ui_src
    stt_src="$(lang_env_source UTTER_MODEL_STT "$code")"
    tts_src="$(lang_env_source UTTER_MODEL_TTS "$code")"
    ui_src="$(lang_locale_pack "$code")"

    say ""
    say "  English ships inline and needs no downloads."
    say_f "  For {1}, everything below is optional — press Enter to skip." "$code"
    say ""

    if [[ -n "$stt_src" ]]; then
        field "stt" "multilingual speech recognition (~480 MB, or ~1.6 GB for large-v3-turbo)"
        sub "the English default distil-small.en only speaks English"
        if ask_yn "n" "  Download the multilingual STT model (~480 MB / ~1.6 GB)?"; then
            LANG_STT_SRC="$stt_src"; LANG_ACCEPT+=(stt)
        fi
        (( QUIT )) && return 1
    else
        note "no multilingual STT source configured; add it later with:"
        say_f "        UTTER_MODEL_STT_{1}=hf:org/repo assistant models pull <src>" "$(lang_env_token "$code")"
    fi

    if [[ -n "$tts_src" ]]; then
        field_f "tts" "spoken replies for {1} (voice model/path)" "$code"
        if ask_yn "n" "  Download the TTS voice for $code?"; then
            LANG_TTS_SRC="$tts_src"; LANG_ACCEPT+=(tts)
        fi
        (( QUIT )) && return 1
    else
        note "no TTS voice source configured; espeak/spd-say voices need no download."
    fi

    if [[ -n "$ui_src" ]]; then
        field "ui pack" "settings-window localization pack (<5 MB)"
        if ask_yn "n" "  Download the $code settings-window localization pack?"; then
            LANG_UI_PACK="$ui_src"; LANG_ACCEPT+=(ui)
        fi
        (( QUIT )) && return 1
    fi

    if (( ${#LANG_ACCEPT[@]} == 0 )); then
        say ""
        note "no downloads accepted; you can add them later (see the command printed above)."
    fi
    return 0
}

# run_language_step — the wizard body for the language component. Sets
# LANG_CODE / LANG_TTS_VOICE and, when a non-English language is chosen,
# offers (never forces) the matching downloads.
run_language_step() {
    local syscode choice other
    syscode="$(resolve_system_language)"

    say ""
    say "  Spoken language for speech-to-text and spoken replies."
    say "  English ships inline and needs no downloads; other languages do."
    if [[ -n "$syscode" ]]; then
        say_f "  Detected system language: {1}" "$syscode"
    else
        say "  System language: not detected (C/POSIX); defaulting to English."
    fi
    say ""

    # Non-interactive / --yes: English, no downloads, print how to change later.
    if (( ASSUME_YES )); then
        LANG_CODE=""
        say "  default: English (default) — no downloads"
        say_f "  to add a language later: edit [stt]/[tts] language in {1}" "$CONFIG_FILE"
        say "  then pull a multilingual model: assistant models pull <hf:org/repo[:file]>"
        return 0
    fi

    local -a opts=("English (default)")
    [[ -n "$syscode" && "$syscode" != en* ]] && opts+=("$syscode")
    opts+=("Other language (type a code)")

    if ui_gum_ok; then
        if ! choice="$(gum choose --header "Spoken language" "${opts[@]}")"; then
            QUIT=1
            return 1
        fi
    else
        local n=0 o
        for o in "${opts[@]}"; do n=$((n+1)); printf '  %d) %s\n' "$n" "$o"; done
        printf '  choose [1-%d] (Enter = 1): ' "$n"
        local ans=""
        IFS= read -r ans || ans=""
        ans="${ans//[[:space:]]/}"
        case "${ans,,}" in
            q|quit) QUIT=1; return 1 ;;
            "")     choice="${opts[0]}" ;;
            *[!0-9]*|"") choice="${opts[0]}" ;;
            *)
                if (( ans >= 1 && ans <= ${#opts[@]} )); then
                    choice="${opts[$((ans-1))]}"
                else
                    choice="${opts[0]}"
                fi
                ;;
        esac
    fi

    if [[ "$choice" == "Other language"* ]]; then
        printf '  Language code (e.g. de, de-DE, pt-BR): '
        IFS= read -r other || other=""
        other="${other//[[:space:]]/}"
        if [[ -n "$other" ]]; then
            LANG_CODE="$(normalize_lang_code "$other")"
        fi
    elif [[ "$choice" == "English"* || "$choice" == "$LANG_DEFAULT" ]]; then
        LANG_CODE=""
    else
        LANG_CODE="$(normalize_lang_code "$choice")"
    fi

    if [[ -z "$LANG_CODE" || "$LANG_CODE" == en || "$LANG_CODE" == en-* ]]; then
        LANG_CODE=""
        say "  selected: English (default) — inline, no downloads."
        say_f "  to switch later, edit [stt]/[tts] language in {1}" "$CONFIG_FILE"
        return 0
    fi

    LANG_TTS_VOICE="$(lang_voice_value "$LANG_CODE")"
    say_f "  selected: {1}" "$LANG_CODE"
    lang_offer_downloads "$LANG_CODE"
}

# normalize_lang_code <raw> — lowercase the language subtag, uppercase the
# region, keep an optional hyphen. Unknown shapes are passed through unchanged.
normalize_lang_code() {
    local raw="$1" lang rest region
    raw="${raw%%@*}"; raw="${raw%%.*}"; raw="${raw//_/-}"
    lang="${raw%%-*}"; rest="${raw#*-}"
    lang="${lang,,}"
    if [[ "$rest" == "$raw" ]]; then
        printf '%s' "$lang"; return 0
    fi
    region="${rest##*-}"; region="${rest%%-*}"
    case "$region" in
        [A-Za-z][A-Za-z]|[0-9][0-9][0-9]) region="${region^^}" ;;
        *) region="" ;;
    esac
    printf '%s%s' "$lang" "${region:+-${region}}"
}

wizard() {
    local i id rec
    for i in "${!COMP_IDS[@]}"; do
        id="${COMP_IDS[i]}"
        rec="${REC_BY_ID[$id]:-no}"

        # Noctalia: auto-skip when the shell is not present.
        if [[ "$id" == "noctalia" ]] && (( ! NOCTALIA_PRESENT )); then
            step_header "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
            note "Noctalia not detected; skipping. Install it with --with-noctalia once Noctalia is present."
            DECISION[i]="skip"
            continue
        fi

        # GUI: the release publishes x86_64 GUI assets only.
        if [[ "$id" == "gui" ]] && (( ! GUI_AVAILABLE )); then
            step_header "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
            note_f "no GUI assets are published for {1} yet (the AppImage/deb/rpm are x86_64 only); skipping." "$ARCH"
            DECISION[i]="skip"
            continue
        fi

        # --only / --skip
        if ! allowed "$id"; then
            step_header "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
            note "skipped (not selected by --only/--skip)"
            DECISION[i]="skip"
            continue
        fi

        step_header "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
        present_step "$i" "$id"

        # Language: choose the spoken language; English is inline and default.
        if [[ "$id" == "lang" ]]; then
            ui_rule
            run_language_step
            (( QUIT )) && return 1
            DECISION[i]="yes"
            continue
        fi

        # Models are handled per tier.
        if [[ "$id" == "models" ]]; then
            if (( ASSUME_YES )); then
                say "  default: no (recommended) — models are opt-in"
                DECISION[i]="skip"
                continue
            fi
            ui_rule
            say ""
            say "  Recommended tiers:"
            MODEL_TIER_KEYS=(); MODEL_TIER_TITLES=(); MODEL_TIER_SIZES=()
            local line key title size reason
            while IFS='|' read -r key title size reason; do
                [[ -n "$key" ]] || continue
                MODEL_TIER_KEYS+=("$key"); MODEL_TIER_TITLES+=("$title")
                MODEL_TIER_SIZES+=("$size")
                printf '    %-9s %s\n' "$key" "$title"
                printf '              size: %s  (%s)\n' "$size" "$reason"
            done < <(recommend_tiers)
            local accepted=0 idx
            for idx in "${!MODEL_TIER_KEYS[@]}"; do
                if ask_yn_f "n" "  Download the {1} model ({2})?" "${MODEL_TIER_TITLES[idx]}" "${MODEL_TIER_SIZES[idx]}"; then
                    accepted=1
                    MODELS_YES="${MODELS_YES:+$MODELS_YES,}${MODEL_TIER_KEYS[idx]}"
                fi
                (( QUIT )) && return 1
            done
            if (( accepted )); then DECISION[i]="yes"; else DECISION[i]="skip"; fi
            continue
        fi

        if (( ASSUME_YES )); then
            announce_default "$rec"
            [[ "$rec" == "y" ]] && DECISION[i]="yes" || DECISION[i]="skip"
        else
            ui_rule
            ui_key_legend
            if ask_yn_f "$rec" "  Install {1}?" "${COMP_LABELS[i]}"; then
                DECISION[i]="yes"
            else
                DECISION[i]="skip"
            fi
            (( QUIT )) && return 1
        fi
    done
    return 0
}

if ! wizard; then
    say ""
    say "Quit before making any changes."
    exit 0
fi

# sub-questions (asked once, after the walk)
if [[ "$(decision_of units)" == "yes" ]] && (( ! ASSUME_YES )); then
    if ask_yn "n" "  Enable and start utter-runner.service now?"; then
        ENABLE_UNITS=1
    fi
    (( QUIT )) && { say "Quit before making any changes."; exit 0; }
fi
if [[ "$(decision_of config)" == "yes" ]] && [[ -f "$CONFIG_FILE" ]]; then
    if ask_yn "n" "  $CONFIG_FILE exists — overwrite it with the default?"; then
        OVERWRITE_CONFIG=1
    fi
    (( QUIT )) && { say "Quit before making any changes."; exit 0; }
fi

# --------------------------------------------------------------------------- #
# section: plan review
# --------------------------------------------------------------------------- #
section "plan review"
sudo_used=0
PLAN_W="$(comp_label_width)"
PLAN_COMPACT=0
(( $(ui_cols) < 56 )) && PLAN_COMPACT=1
if (( ! PLAN_COMPACT )); then
    if [[ -n "$GL_H" ]]; then
        printf '  %s%-3s %-*s %-8s %s%s\n' "$C_MUTED" "#" "$PLAN_W" "component" "action" "sudo" "$C_RESET"
    else
        printf '  %-3s %-*s %-8s %s\n' "#" "$PLAN_W" "component" "action" "sudo"
    fi
fi
for i in "${!COMP_IDS[@]}"; do
    id="${COMP_IDS[i]}"
    d="${DECISION[i]:-skip}"
    _sudo="-"
    if [[ "$d" == "yes" ]]; then
        if (( COMP_SUDO[i] )) || { [[ "$id" == "gui" ]] && [[ "$MODE" == "package" ]]; }; then
            _sudo="sudo"; sudo_used=1
        fi
        if (( PLAN_COMPACT )); then
            if [[ "$_sudo" == "sudo" ]]; then
                say "  $((i+1))   ${COMP_LABELS[i]} (install, sudo)"
            else
                say "  $((i+1))   ${COMP_LABELS[i]} (install)"
            fi
        else
            printf '  %-3s %-*s %-8s %s\n' "$((i+1))" "$PLAN_W" "${COMP_LABELS[i]}" "install" "$_sudo"
        fi
    else
        if (( PLAN_COMPACT )); then
            say "  $((i+1))   ${COMP_LABELS[i]} (skip)"
        else
            printf '  %-3s %-*s %-8s %s\n' "$((i+1))" "$PLAN_W" "${COMP_LABELS[i]}" "skip" "-"
        fi
    fi
done
if (( ENABLE_UNITS )); then say_f "  units: enable + start utter-runner.service now"; fi
if [[ -n "$LANG_CODE" ]]; then
    say_f "  language: {1} (English default otherwise)" "$LANG_CODE"
else
    say "  language: English (default) — inline, no downloads"
fi
if (( ${#MODELS_YES} )); then say_f "  models accepted: {1}" "$MODELS_YES"; fi
if (( sudo_used )); then say "  sudo: required for one or more selected steps"; else say "  sudo: not required"; fi

if (( ! ASSUME_YES )); then
    if ! ask_yn "y" "Proceed with this plan?"; then
        say "Aborted; nothing changed."
        exit 0
    fi
fi

# --------------------------------------------------------------------------- #
# section: execution
# --------------------------------------------------------------------------- #
asset_names_ready() { [[ -n "$CORE_TARBALL" ]]; }
asset_names_ready || { resolve_release; set_asset_names; }

exec_deps() {
    section "system deps"
    local missing_csv; missing_csv="$(missing_pkgs | paste -sd, - 2>/dev/null || missing_pkgs | tr '\n' ',')"
    if [[ -z "$missing_csv" ]]; then
        say "  all required dependencies are already present"
        return 0
    fi
    say_f "  missing packages: {1}" "$missing_csv"
    local PKGS=()
    local p
    while IFS= read -r p; do [[ -n "$p" ]] && PKGS+=("$p"); done < <(missing_pkgs)
    local INSTALL_CMD=()
    case "$PKG_MGR" in
        pacman) INSTALL_CMD=(sudo pacman -S --needed --noconfirm "${PKGS[@]}") ;;
        apt)    INSTALL_CMD=(sudo apt-get install -y "${PKGS[@]}") ;;
        dnf)    INSTALL_CMD=(sudo dnf install -y "${PKGS[@]}") ;;
        zypper) INSTALL_CMD=(sudo zypper --non-interactive install "${PKGS[@]}") ;;
        *)      INSTALL_CMD=() ;;
    esac
    if (( ${#INSTALL_CMD[@]} == 0 )); then
        warn "$(t "no package manager command for '{1}'; install manually: {2}" "$PKG_MGR" "${PKGS[*]}")"
    elif (( DRY_RUN )); then
        run "install system dependencies" "${INSTALL_CMD[@]}"
    elif sudo -n true 2>/dev/null; then
        run "install system dependencies" "${INSTALL_CMD[@]}"
    else
        warn "no passwordless sudo; printing the command instead:"
        say "            \$ ${INSTALL_CMD[*]}"
        note "run it yourself, then re-run"
    fi
    reset_record
    D_PACKAGES=("${PKGS[@]}")
    record_component deps "System deps" "$VER_NUM" "$PKG_MGR" 1 "$ASSISTANT_BIN"
}

# ensure_python_deps — make `python -m assistant` and the utter_py plugin
# importable. The core needs PyYAML + requests; prefer an existing venv in the
# core tree, create one if needed, else fall back to a --user install. Uses
# python3 explicitly and never relies on a bare `python`. Sets ASSISTANT_PY to
# the interpreter that should run the plugin.
ASSISTANT_PY=""
ensure_python_deps() {
    local py="" c
    for c in "${UTTER_PYTHON:-}" "$SHARE_DIR/.venv-agent/bin/python" "$SHARE_DIR/.venv/bin/python"; do
        [[ -n "$c" ]] || continue
        if command -v "$c" >/dev/null 2>&1 || [[ -x "$c" ]]; then py="$c"; break; fi
    done
    if [[ -z "$py" ]] && command -v python3 >/dev/null 2>&1; then py="$(command -v python3)"; fi
    [[ -n "$py" ]] || { warn "no python3 on PATH; cannot install assistant dependencies"; return 0; }

    if "$py" -c 'import yaml, requests' >/dev/null 2>&1; then
        say "  assistant Python dependencies already present"
        ASSISTANT_PY="$py"
        return 0
    fi

    local venv="$SHARE_DIR/.venv-agent"
    if (( DRY_RUN )); then
        ASSISTANT_PY="$venv/bin/python"
        run_f "create {1}" "$venv" python3 -m venv "$venv"
        run "install PyYAML + requests" "$venv/bin/python" -m pip install --quiet --disable-pip-version-check PyYAML requests
        return 0
    fi

    if [[ ! -x "$venv/bin/python" ]] && command -v python3 >/dev/null 2>&1; then
        python3 -m venv "$venv" >/dev/null 2>&1 || true
    fi
    if [[ -x "$venv/bin/python" ]] \
        && "$venv/bin/python" -m pip install --quiet --disable-pip-version-check PyYAML requests >/dev/null 2>&1; then
        ok_f "installed PyYAML + requests into {1}" "$venv"
        ASSISTANT_PY="$venv/bin/python"
        return 0
    fi
    if "$py" -m pip install --user --quiet --disable-pip-version-check PyYAML requests >/dev/null 2>&1; then
        ok "installed PyYAML + requests for the user"
        ASSISTANT_PY="$py"
        return 0
    fi
    warn "could not install PyYAML + requests; install them yourself: python3 -m pip install --user PyYAML requests"
    ASSISTANT_PY="$py"
    return 0
}

# fix_plugin_python — the shipped utter_py manifest uses a bare `["python", …]`
# entrypoint and the runner config uses `["python3", …]`. Point both at
# ASSISTANT_PY so the plugin starts with the core's dependencies even when
# `python` is not on PATH and system `python3` lacks PyYAML/requests.
fix_plugin_python() {
    [[ -n "$ASSISTANT_PY" ]] || return 0
    local files=(
        "$SHARE_DIR/plugins/utter_py/utter-plugin.toml"
        "$SHARE_DIR/config.m3.toml"
    )
    if (( DRY_RUN )); then
        say_f "  [dry-run] point plugin entrypoints at {1}" "$ASSISTANT_PY"
        return 0
    fi
    local f
    for f in "${files[@]}"; do
        [[ -f "$f" ]] || continue
        sed -i \
            -e "s|entrypoint = \\[\"python\", \"-m\", \"plugin\"\\]|entrypoint = [\"${ASSISTANT_PY}\", \"-m\", \"plugin\"]|" \
            -e "s|entrypoint = \\[\"python3\", \"-m\", \"plugin\"\\]|entrypoint = [\"${ASSISTANT_PY}\", \"-m\", \"plugin\"]|" \
            "$f"
    done
    ok_f "plugin utter_py will run with {1}" "$ASSISTANT_PY"
}

exec_core() {
    section "install core (runner + assistant CLI)"
    fetch_core
    run_f "create {1}" "$SHARE_DIR" mkdir -p "$SHARE_DIR"
    if (( DRY_RUN )); then
        say_f "  [dry-run] extract {1} -> {2}" "$CORE_TARBALL" "$SHARE_DIR"
    else
        local extract="$TMP/extract"
        mkdir -p "$extract"
        ui_spin_run "extracting $CORE_TARBALL" tar -xzf "$TMP/$CORE_TARBALL" -C "$extract"
        local top; top="$(find "$extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
        [[ -n "$top" ]] || die "core tarball has no top-level directory"
        rm -rf "$SHARE_DIR"
        mv "$top" "$SHARE_DIR"
        ok_f "extracted core -> {1}" "$SHARE_DIR"
    fi

    run_f "create {1}" "$BIN_DIR" mkdir -p "$BIN_DIR"
    if (( DRY_RUN )); then
        say_f "  [dry-run] write {1} (wrapper for python -m assistant)" "$ASSISTANT_BIN"
    else
        cat > "$ASSISTANT_BIN" <<WRAP
#!/usr/bin/env bash
# utter assistant wrapper (installed by install.sh)
set -euo pipefail
CORE="$SHARE_DIR"
export PYTHONPATH="\$CORE\${PYTHONPATH:+:\$PYTHONPATH}"
PY="\${UTTER_PYTHON:-}"
if [[ -z "\$PY" ]]; then
    for c in "\$CORE/.venv-agent/bin/python" "\$CORE/.venv/bin/python" python3; do
        if command -v "\$c" >/dev/null 2>&1 || [[ -x "\$c" ]]; then PY="\$c"; break; fi
    done
fi
[[ -n "\$PY" ]] || { echo "assistant: no python interpreter found" >&2; exit 1; }
exec "\$PY" -m assistant "\$@"
WRAP
        chmod +x "$ASSISTANT_BIN"
        ok_f "wrote {1}" "$ASSISTANT_BIN"
    fi
    ensure_python_deps
    fix_plugin_python
    reset_record
    D_FILES=("$ASSISTANT_BIN")
    D_DIRS=("$SHARE_DIR")
    record_component core "Core runner + CLI" "$VER_NUM" "tarball" 0 "$ASSISTANT_BIN"
}

exec_units() {
    section "install systemd user units"
    local unit_src=""
    if [[ -f "$SHARE_DIR/install/utter-runner.service" ]]; then
        unit_src="$SHARE_DIR/install/utter-runner.service"
    else
        ensure_core_context
        unit_src="$CORE_CONTEXT/install/utter-runner.service"
    fi
    if [[ -f "$unit_src" ]] || (( DRY_RUN )); then
        run_f "create {1}" "$UNIT_DIR" mkdir -p "$UNIT_DIR"
        # The unit ships with @REPO@ placeholders; point them at the installed
        # core tree, or systemd tries to run a literal "@REPO@" path.
        install_unit() { sed "s|@REPO@|$SHARE_DIR|g" "$unit_src" > "$RUNNER_UNIT"; }
        run "install utter-runner.service" install_unit
        if command -v systemctl >/dev/null 2>&1; then
            run "reload systemd user manager" systemctl --user daemon-reload || true
        fi
        if (( ENABLE_UNITS )); then
            run "enable + start the runner" systemctl --user enable --now utter-runner.service
        else
            note "enable later with: systemctl --user enable --now utter-runner.service"
        fi
        reset_record
        D_FILES=("$RUNNER_UNIT")
        D_UNITS=("utter-runner.service")
        record_component units "systemd user unit" "$VER_NUM" "systemd" 0 "$ASSISTANT_BIN"
    else
        warn "no runner unit found in the core tree; skipping systemd wiring"
    fi
}

exec_lang() {
    section "language"
    if [[ -z "$LANG_CODE" ]]; then
        say "  English (default) — ships inline, no downloads."
        say_f "  To switch languages later, edit [stt]/[tts] language in {1}" "$CONFIG_FILE"
        say "  and pull a multilingual model: assistant models pull <hf:org/repo[:file]>"
        reset_record
        D_KEEP=1
        record_component lang "Language (English)" "$VER_NUM" "inline" 0 "$ASSISTANT_BIN"
        return 0
    fi
    say_f "  Selected language: {1}" "$LANG_CODE"
    if (( ${#LANG_ACCEPT[@]} == 0 )); then
        say "  No downloads accepted; English-only models keep working."
        say "  Add a multilingual model later: assistant models pull <hf:org/repo[:file]>"
        reset_record
        D_KEEP=1
        record_component lang "Language ($LANG_CODE)" "$VER_NUM" "inline" 0 "$ASSISTANT_BIN"
        return 0
    fi
    if [[ ! -x "$ASSISTANT_BIN" ]] && [[ ! -d "$SHARE_DIR/assistant" ]]; then
        warn "core/CLI is not installed; cannot pull language downloads. Run with the core step enabled."
        reset_record
        D_KEEP=1
        record_component lang "Language ($LANG_CODE)" "$VER_NUM" "inline" 0 "$ASSISTANT_BIN"
        return 0
    fi
    local kind src
    for kind in "${LANG_ACCEPT[@]}"; do
        case "$kind" in
            stt) src="$LANG_STT_SRC" ;;
            tts) src="$LANG_TTS_SRC" ;;
            ui)  src="$LANG_UI_PACK" ;;
            *)   src="" ;;
        esac
        if [[ -n "$src" ]]; then
            run_f "pull {1} {2} download ({3})" "$LANG_CODE" "$kind" "$src" "$ASSISTANT_BIN" models pull "$src"
        else
            note_f "no source configured for the {1} {2} download; pull it later with:" "$LANG_CODE" "$kind"
            say "        assistant models pull <hf:org/repo[:file] | https://… | file://…>"
        fi
    done
    reset_record
    D_KEEP=1
    record_component lang "Language ($LANG_CODE)" "$VER_NUM" "assistant-models" 0 "$ASSISTANT_BIN"
}

exec_models() {
    section "models"
    if [[ ! -x "$ASSISTANT_BIN" ]] && [[ ! -d "$SHARE_DIR/assistant" ]]; then
        warn "core/CLI is not installed; cannot pull models. Run with the core step enabled."
        return 0
    fi
    local key src
    local -a keys=()
    IFS=, read -ra keys <<<"$MODELS_YES"
    for key in "${keys[@]}"; do
        [[ -n "$key" ]] || continue
        case "$key" in
            stt)      src="${UTTER_MODEL_STT:-}" ;;
            decision) src="${UTTER_MODEL_DECISION:-}" ;;
            vision)   src="${UTTER_MODEL_VISION:-}" ;;
            *)        src="" ;;
        esac
        if [[ -n "$src" ]]; then
            run_f "pull {1} model ({2})" "$key" "$src" "$ASSISTANT_BIN" models pull "$src"
        else
            note_f "no source configured for the {1} tier; pull it later with:" "$key"
            say "        assistant models pull <hf:org/repo[:file] | https://… | file://…>"
        fi
    done
    reset_record
    D_KEEP=1
    record_component models "Models" "$VER_NUM" "assistant-models" 0 "$ASSISTANT_BIN"
}

exec_gui() {
    section_f "install GUI ({1})" "$MODE"
    if (( ! GUI_AVAILABLE )); then
        note_f "no GUI assets are published for {1} yet (x86_64 only); skipping the GUI." "$ARCH"
        return 0
    fi
    choose_gui_asset
    fetch_gui
    if [[ "$MODE" == "appimage" ]]; then
        run "create $BIN_DIR" mkdir -p "$BIN_DIR"
        if (( DRY_RUN )); then
            say_f "  [dry-run] install {1} -> {2} (chmod +x)" "$GUI_ASSET" "$GUI_BIN"
            say_f "  [dry-run] install icons -> {1}" "$ICON_THEME_DIR"
            say_f "  [dry-run] write {1}" "$DESKTOP_FILE"
        else
            install -m 0755 "$TMP/$GUI_ASSET" "$GUI_BIN"
            ok_f "installed {1}" "$GUI_BIN"
            if [[ -d "$SHARE_DIR/assets/icons" ]]; then
                for pair in "utter-32.png:32x32" "utter-64.png:64x64" "utter-128.png:128x128" "utter-256.png:256x256"; do
                    mkdir -p "$ICON_THEME_DIR/${pair##*:}/apps"
                    install -m 0644 "$SHARE_DIR/assets/icons/${pair%%:*}" \
                        "$ICON_THEME_DIR/${pair##*:}/apps/$ICON_NAME.png"
                done
                if [[ -f "$SHARE_DIR/assets/icons/utter.svg" ]]; then
                    mkdir -p "$ICON_THEME_DIR/scalable/apps"
                    install -m 0644 "$SHARE_DIR/assets/icons/utter.svg" \
                        "$ICON_THEME_DIR/scalable/apps/$ICON_NAME.svg"
                fi
                ok_f "installed icons ({1})" "$ICON_NAME"
                command -v gtk-update-icon-cache >/dev/null 2>&1 && \
                    gtk-update-icon-cache -f -t "$ICON_THEME_DIR" >/dev/null 2>&1 || true
            else
                note "no bundled icons; the desktop entry falls back to a system icon"
            fi
            mkdir -p "$APPS_DIR"
            cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=utter Settings
GenericName=Voice Assistant Settings
Comment=Configure the utter voice → desktop-action assistant
Exec=$GUI_BIN
TryExec=$GUI_BIN
Icon=$ICON_NAME
Terminal=false
Categories=Settings;
Keywords=utter;voice;assistant;settings;stt;llm;
StartupNotify=true
StartupWMClass=utter
DESKTOP
            ok_f "wrote {1}" "$DESKTOP_FILE"
            command -v update-desktop-database >/dev/null 2>&1 && \
                update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
        fi
        local symlink=""
        if [[ ":$PATH:" != *":$BIN_DIR:"* && "$BIN_DIR" != "$HOME/.local/bin" ]] && command -v noctalia >/dev/null 2>&1; then
            run_f "create {1}" "$HOME/.local/bin" mkdir -p "$HOME/.local/bin"
            run_f "symlink {1} -> {2} (Noctalia left-click)" "$SYMLINK_PATH" "$GUI_BIN" ln -sf "$GUI_BIN" "$SYMLINK_PATH"
            symlink="$SYMLINK_PATH"
        fi
        reset_record
        D_FILES=("$GUI_BIN" "$DESKTOP_FILE" "${ICON_FILES[@]}")
        [[ -n "$symlink" ]] && D_FILES+=("$symlink")
        record_component gui "GUI ($MODE)" "$VER_NUM" "$MODE" 0 "$ASSISTANT_BIN"
    else
        local PKG_CMD=()
        case "$PKG_MGR" in
            apt)    PKG_CMD=(sudo apt-get install -y "$TMP/$GUI_ASSET") ;;
            dnf)    PKG_CMD=(sudo dnf install -y "$TMP/$GUI_ASSET") ;;
            zypper) PKG_CMD=(sudo zypper --non-interactive install "$TMP/$GUI_ASSET") ;;
            pacman) PKG_CMD=(sudo pacman -U --noconfirm "$TMP/$GUI_ASSET") ;;
        esac
        if (( ${#PKG_CMD[@]} )); then
            if (( DRY_RUN )); then
                run "install package" "${PKG_CMD[@]}"
            elif sudo -n true 2>/dev/null; then
                run "install package" "${PKG_CMD[@]}"
            else
                warn "no passwordless sudo; print the command instead:"
                say "            \$ ${PKG_CMD[*]}"
            fi
        else
            warn "$(t "no package manager command for '{1}'; install {2} manually" "$PKG_MGR" "$GUI_ASSET")"
        fi
        reset_record
        D_PACKAGES=("utter-gui")
        record_component gui "GUI (package)" "$VER_NUM" "package" 1 "$ASSISTANT_BIN"
    fi
}

exec_stt() {
    section "STT backend"
    found_stt
    say "  To enable voice, install one of:"
    say "    - python3 -m pip install --user faster-whisper (local whisper)"
    say "    - a whisper.cpp build (whisper-cli) and set stt.backend = \"whisper_cpp\""
    reset_record
    record_component stt "STT backend" "$VER_NUM" "advisory" 0 "$ASSISTANT_BIN"
}

exec_perception() {
    section "perception (vision server deps)"
    found_perception
    say "  Vision grounding is optional; the assistant works with a11y-only context."
    say "  To enable it: serve UI-TARS with vLLM and point [vision].base_url at it."
    say "  See docs/INSTALL.md and scripts/serve_*.sh in the extracted core tree."
    reset_record
    record_component perception "Perception deps" "$VER_NUM" "advisory" 0 "$ASSISTANT_BIN"
}

exec_noctalia() {
    section "Noctalia widget (optional)"
    if (( ! NOCTALIA_PRESENT )); then
        note "Noctalia not detected; skipping."
        return 0
    fi
    ensure_core_context
    local script="$CORE_CONTEXT/widgets/noctalia/install.sh"
    if [[ -f "$script" ]] || (( DRY_RUN )); then
        run "install the Noctalia widget" bash "$script" --yes
        reset_record
        D_DIRS=("$NOCTALIA_DEST")
        record_component noctalia "Noctalia widget" "$VER_NUM" "widgets/noctalia" 0 "$ASSISTANT_BIN"
    else
        warn "widgets/noctalia/install.sh not found in the core tree; skipping"
    fi
}

# toml_escape <string> — minimal TOML basic-string escaping (backslash + quote).
toml_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

# set_config_value <file> <section> <key> <value> [<section> <key> <value> ...]
# Edits `key = "value"` in-place inside [section]. This is the same
# line-preserving pattern used elsewhere; nothing is hand-parsed beyond the
# section/key assignment it was asked to change.
set_config_value() {
    local file="$1"; shift
    if (( DRY_RUN )); then
        say_f "  [dry-run] edit {1}" "$file"
        return 0
    fi
    local section key value
    while [[ $# -ge 3 ]]; do
        section="$1"; key="$2"; value="$3"; shift 3
        _toml_set_one "$file" "$section" "$key" "$value"
    done
}

_toml_set_one() {
    local file="$1" section="$2" key="$3" value="$4"
    local escaped; escaped="$(toml_escape "$value")"
    local produced
    if ! produced="$(awk -v sec="$section" -v k="$key" -v val="$escaped" '
        BEGIN { cur=""; found=0; sec_end=0 }
        {
            line=$0
            if (match(line, /^[[:space:]]*\[[^]]+\]([[:space:]]*(#.*)?)?$/)) {
                if (cur==sec && sec_end==0) sec_end=NR
                h=line
                sub(/^[[:space:]]*\[/, "", h)
                sub(/\].*$/, "", h)
                cur=h
                if (cur==sec) { sec_start=NR }
            }
            if (cur==sec && line ~ ("^[[:space:]]*" k "[[:space:]]*=")) {
                if (!found) { print k " = \"" val "\""; found=1 }
                next
            }
            print line
        }
        END {
            if (!found) {
                if (sec_start) {
                    # insertion after the section marker is handled by a rewrite
                    # pass below; flag it for the caller
                    print "__UTTER_NEED_INSERT__" > "/dev/stderr"
                } else {
                    print "__UTTER_NEED_SECTION__" > "/dev/stderr"
                }
            }
        }
    ' "$file" 2>"$TMP/_toml_hint")"; then
        return 1
    fi
    local hint=""
    [[ -f "$TMP/_toml_hint" ]] && hint="$(cat "$TMP/_toml_hint")"
    if [[ "$hint" == *NEED_INSERT* ]]; then
        _toml_insert_after_section "$file" "$section" "$key" "$value"
        return 0
    fi
    if [[ "$hint" == *NEED_SECTION* ]]; then
        [[ -s "$file" ]] && printf '\n' >> "$file"
        printf '[%s]\n%s = "%s"\n' "$section" "$key" "$escaped" >> "$file"
        return 0
    fi
    printf '%s\n' "$produced" > "$file"
    return 0
}

_toml_insert_after_section() {
    local file="$1" section="$2" key="$3" value="$4"
    local escaped; escaped="$(toml_escape "$value")"
    awk -v sec="$section" -v k="$key" -v val="$escaped" '
        BEGIN { cur=""; inserted=0 }
        {
            print
            if (match($0, /^[[:space:]]*\[[^]]+\]([[:space:]]*(#.*)?)?$/)) {
                h=$0
                sub(/^[[:space:]]*\[/, "", h)
                sub(/\].*$/, "", h)
                cur=h
                if (cur==sec && !inserted) { print k " = \"" val "\""; inserted=1 }
            }
        }
    ' "$file" > "$file._tmp" && mv "$file._tmp" "$file"
}

exec_config() {
    section "config"
    ensure_core_context
    local src="$CORE_CONTEXT/config.default.toml"
    if [[ -f "$CONFIG_FILE" ]] && (( ! OVERWRITE_CONFIG )); then
        note_f "keeping existing {1} (not overwritten)" "$CONFIG_FILE"
        return 0
    fi
    if [[ -f "$src" ]] || (( DRY_RUN )); then
        run_f "create {1}" "$CONFIG_DIR" mkdir -p "$CONFIG_DIR"
        run_f "write {1} from default" "$CONFIG_FILE" cp "$src" "$CONFIG_FILE"
        if [[ -n "$LANG_CODE" ]]; then
            if (( DRY_RUN )); then
                say_f "  [dry-run] set [stt] language = \"{1}\" in {2}" "$LANG_CODE" "$CONFIG_FILE"
                say_f "  [dry-run] set [tts] language = \"{1}\" in {2}" "$LANG_CODE" "$CONFIG_FILE"
                [[ -n "$LANG_TTS_VOICE" ]] && \
                    say_f "  [dry-run] set [tts] voice = \"{1}\" in {2}" "$LANG_TTS_VOICE" "$CONFIG_FILE"
            else
                set_config_value "$CONFIG_FILE" stt language "$LANG_CODE" \
                    tts language "$LANG_CODE" tts voice "$LANG_TTS_VOICE"
                ok_f "wrote language {1} to {2}" "$LANG_CODE" "$CONFIG_FILE"
            fi
        fi
        reset_record
        D_KEEP=1
        record_component config "Config" "$VER_NUM" "default" 0 "$ASSISTANT_BIN"
    else
        warn "no config.default.toml found in the core tree; skipping config"
    fi
}

run_component() {
    case "$1" in
        deps)       exec_deps ;;
        core)       exec_core ;;
        lang)       exec_lang ;;
        units)      exec_units ;;
        models)     exec_models ;;
        gui)        exec_gui ;;
        stt)        exec_stt ;;
        perception) exec_perception ;;
        noctalia)   exec_noctalia ;;
        config)     exec_config ;;
    esac
}

section "install"
run_install_phase

rebuild_install_json

# --------------------------------------------------------------------------- #
# section: summary + next steps
# --------------------------------------------------------------------------- #
section "done"
if (( DRY_RUN )); then
    say_f "Dry-run complete. Re-run without --dry-run to apply."
else
    if ui_unicode_ok; then
        printf '  %s%s%s Installed utter %s into %s\n' \
            "$C_OK" "$TASK_DONE" "$C_RESET" "$VER" "$PREFIX"
    else
        say_f "Installed utter {1} into {2}" "$VER" "$PREFIX"
    fi
    say ""
    if [[ -n "$LANG_CODE" ]]; then
        say_f "Language: {1}" "$LANG_CODE"
    else
        say "Language: English (default; English ships inline, no downloads)"
        say_f "  to add a language later: edit [stt]/[tts] language in {1}" "$CONFIG_FILE"
        say "  then: assistant models pull <hf:org/repo[:file]>"
    fi
    say ""
    say "Next steps:"
    say "  1. Start the runner:   systemctl --user enable --now utter-runner.service"
    say_f "  2. Check the install:  {1} doctor --json" "$ASSISTANT_BIN"
    if (( GUI_AVAILABLE )); then
        say "  3. Launch the GUI:     ${GUI_BIN}"
        say "  4. Uninstall:          curl -fsSL <install.sh-url> | bash -s -- --uninstall"
    else
        say "  3. Uninstall:          curl -fsSL <install.sh-url> | bash -s -- --uninstall"
    fi
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        say ""
        note_f "{1} is not on your PATH; add it: export PATH=\"{1}:\$PATH\"" "$BIN_DIR"
    fi
    if ui_unicode_ok; then
        printf '\n  %sutter%s\n' "$C_FAINT" "$C_RESET"
    fi
fi
