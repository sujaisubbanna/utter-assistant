#!/usr/bin/env bash
# utter bootstrap installer — interactive step-by-step wizard + curl | bash.
#
#   curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash
#   curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --yes
#
# In a terminal this is an interactive wizard: it walks every component and asks
# whether you want it (showing what it is, its size, whether sudo is needed, and
# what was detected on this machine). With --yes it accepts the recommended
# defaults non-interactively. Piped with no --yes it prints the plan and exits
# without changing anything.
#
# Every download is verified against sha256sums.txt from the GitHub Release.
#
# Environment:
#   UTTER_REPO      GitHub repo "owner/name" (default: sujaisubbanna/utter-assistant)
#   UTTER_VERSION   release tag (default: latest)
#   UTTER_BASE_URL  override the download base (default: GitHub Releases;
#                       set to http://127.0.0.1:PORT for local testing)
#   PREFIX              install prefix (default: $HOME/.local)
#   UTTER_PYTHON    python interpreter baked into the assistant wrapper
#   UTTER_MODEL_STT / _DECISION / _VISION
#                       optional model source for a tier (hf:org/repo[:file],
#                       https://… or file://…); pulled only if that tier is chosen
#
# Flags:
#   --appimage         install the AppImage (no sudo; default)
#   --package          install the .deb/.rpm via the package manager (sudo)
#   --only <csv>       only offer these components (core,gui,units,models,…)
#   --skip <csv>       never offer these components
#   --with-noctalia    mark the optional Noctalia widget as recommended
#   --dry-run          run the walk, print the plan, change nothing
#   --uninstall        menu of installed components (per-component install-state)
#   --yes, -y          accept all recommended defaults, no prompts
#   -h, --help
set -euo pipefail

# --------------------------------------------------------------------------- #
# defaults + args
# --------------------------------------------------------------------------- #
UTTER_REPO="${UTTER_REPO:-sujaisubbanna/utter-assistant}"
UTTER_VERSION="${UTTER_VERSION:-latest}"
UTTER_BASE_URL="${UTTER_BASE_URL:-}"
PREFIX="${PREFIX:-$HOME/.local}"

MODE="appimage"        # appimage | package
DRY_RUN=0
UNINSTALL=0
ASSUME_YES=0
ONLY_CSV=""
SKIP_CSV=""
WITH_NOCTALIA=0

usage() {
    cat <<'USAGE'
utter bootstrap installer — interactive step-by-step wizard + curl | bash.

  curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash
  curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --yes

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
  UTTER_PYTHON    python interpreter baked into the assistant wrapper
  UTTER_MODEL_STT / _DECISION / _VISION
                      optional source per model tier (hf:org/repo[:file],
                      https://… or file://…); pulled only if that tier is chosen

Flags:
  --appimage         install the AppImage (no sudo; default)
  --package          install the .deb/.rpm via the package manager (sudo)
  --only <csv>       only offer these components (core,gui,units,models,…)
  --skip <csv>       never offer these components
  --with-noctalia    mark the optional Noctalia widget as recommended
  --dry-run          run the walk, print the plan, change nothing
  --uninstall        menu of installed components (per-component install-state)
  --yes, -y          accept all recommended defaults, no prompts
  -h, --help         show this help
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
        --yes|-y)         ASSUME_YES=1 ;;
        -h|--help)        usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
say()    { printf '%s\n' "$*"; }
step()   { printf '\n== %s ==\n' "$*"; }
note()   { printf '  note: %s\n' "$*"; }
warn()   { printf '  WARNING: %s\n' "$*" >&2; }
die()    { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
heading() { printf '\n[%s/%s] %s\n' "$1" "$2" "$3"; }
run() {
    local desc="$1"; shift
    if (( DRY_RUN )); then
        printf '  [dry-run] %s\n' "$desc"
        printf '            $ %s\n' "$*"
    else
        printf '  [run] %s\n' "$desc"
        "$@"
    fi
}

is_tty() { [[ -t 0 ]]; }

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
BIN_DIR="$PREFIX/bin"
SHARE_DIR="$PREFIX/share/utter"
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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --------------------------------------------------------------------------- #
# arch + distro
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
# system-dependency probe (used by the deps step)
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
        pacman:gtk4)         echo "gtk4" ;;
        pacman:libadwaita)   echo "libadwaita" ;;
        pacman:keyd)         echo "keyd" ;;
        apt:wtype)           echo "wtype" ;;
        apt:ydotool)         echo "ydotool" ;;
        apt:grim)            echo "grim" ;;
        apt:wl-clipboard)    echo "wl-clipboard" ;;
        apt:pipewire)        echo "pipewire" ;;
        apt:gtk4)            echo "libgtk-4-1" ;;
        apt:libadwaita)      echo "libadwaita-1-0" ;;
        apt:keyd)            echo "" ;;
        dnf:wtype)           echo "wtype" ;;
        dnf:ydotool)         echo "ydotool" ;;
        dnf:grim)            echo "grim" ;;
        dnf:wl-clipboard)    echo "wl-clipboard" ;;
        dnf:pipewire)        echo "pipewire" ;;
        dnf:gtk4)            echo "gtk4" ;;
        dnf:libadwaita)      echo "libadwaita" ;;
        dnf:keyd)            echo "" ;;
        zypper:wtype)        echo "wtype" ;;
        zypper:ydotool)      echo "ydotool" ;;
        zypper:grim)         echo "grim" ;;
        zypper:wl-clipboard) echo "wl-clipboard" ;;
        zypper:pipewire)     echo "pipewire" ;;
        zypper:gtk4)         echo "gtk4-devel" ;;
        zypper:libadwaita)   echo "libadwaita-1-0" ;;
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
        gtk4)         lib_present "gtk4" "libgtk-4" ;;
        libadwaita)   lib_present "libadwaita-1" "libadwaita-1" ;;
        systemd-user) _systemd_user_ok ;;
        keyd)         command -v keyd >/dev/null 2>&1 ;;
        *)            false ;;
    esac
}

_systemd_user_ok() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

DEP_REQUIRED=(wtype ydotool grim wl-clipboard pipewire gtk4 libadwaita)
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

missing_logical() {
    local out=() logical
    for logical in "${DEP_REQUIRED[@]}"; do
        dep_present "$logical" || out+=("$logical")
    done
    printf '%s\n' "${out[@]:-}"
}

# --------------------------------------------------------------------------- #
# per-component detection
# --------------------------------------------------------------------------- #
command -v noctalia >/dev/null 2>&1 && NOCTALIA_PRESENT=1 || NOCTALIA_PRESENT=0
[[ -d "${XDG_DATA_HOME:-$HOME/.local/share}/noctalia" ]] && NOCTALIA_PRESENT=1

found_core() {
    if [[ -x "$ASSISTANT_BIN" || -d "$SHARE_DIR" ]]; then
        say "  found:   already present at $SHARE_DIR"
    else
        say "  found:   not installed"
    fi
}

found_units() {
    if [[ -f "$RUNNER_UNIT" ]]; then
        say "  found:   unit installed ($RUNNER_UNIT)"
    elif _systemd_user_ok; then
        say "  found:   systemd --user available, no unit yet"
    else
        say "  found:   systemd --user unavailable"
    fi
}

found_gui() {
    if [[ -x "$GUI_BIN" ]]; then
        say "  found:   installed at $GUI_BIN"
    elif [[ -x "$SYMLINK_PATH" ]]; then
        say "  found:   installed at $SYMLINK_PATH"
    else
        say "  found:   not installed"
    fi
}

found_models() {
    local root="${UTTER_MODELS:-${XDG_DATA_HOME:-$HOME/.local/share}/utter/models}"
    local n=0
    if [[ -d "$root/manifests" ]]; then
        n="$(find "$root/manifests" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
    fi
    say "  found:   $n model manifest(s) under $root"
}

found_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        say "  found:   exists ($CONFIG_FILE)"
    else
        say "  found:   not present"
    fi
}

found_stt() {
    local parts=()
    command -v vocalinux >/dev/null 2>&1 && parts+=("vocalinux:$(command -v vocalinux)")
    command -v whisper-cli >/dev/null 2>&1 && parts+=("whisper-cli")
    command -v whisper-cpp >/dev/null 2>&1 && parts+=("whisper-cpp")
    command -v whisper >/dev/null 2>&1 && parts+=("whisper")
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import faster_whisper' >/dev/null 2>&1; then
        parts+=("faster-whisper (python)")
    fi
    if (( ${#parts[@]} )); then
        say "  found:   ${parts[*]}"
    else
        say "  found:   no STT backend detected"
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
        say "  found:   ${parts[*]}"
    else
        say "  found:   no perception/vision server deps detected"
    fi
}

found_noctalia() {
    if (( NOCTALIA_PRESENT )); then
        say "  found:   Noctalia detected"
        [[ -d "$NOCTALIA_DEST" ]] && say "           widget already at $NOCTALIA_DEST"
    else
        say "  found:   Noctalia not detected"
    fi
}

found_deps() {
    local present=() miss=() logical
    for logical in "${DEP_REQUIRED[@]}"; do
        if dep_present "$logical"; then present+=("$logical"); else miss+=("$logical"); fi
    done
    say "  found:   present: ${present[*]:-none}"
    say "           missing: ${miss[*]:-none}"
}

run_dep_probe() {
    case "$1" in
        deps)        found_deps ;;
        core)        found_core ;;
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
# component registry
# --------------------------------------------------------------------------- #
COMP_IDS=(deps core units models gui stt perception noctalia config)
COMP_LABELS=(
    "System deps"
    "Core runner + CLI"
    "systemd user units"
    "Models"
    "GUI"
    "STT backend (vocalinux bridge)"
    "Perception (vision server deps)"
    "Noctalia widget (optional)"
    "Config"
)
COMP_WHAT=(
    "Wayland/input/audio tools and libs (wtype, ydotool, grim, wl-clipboard, pipewire, gtk4, libadwaita)"
    "protocol + reference runner + assistant CLI + bundled plugins"
    "utter-runner.service user unit (+ optional enable & start)"
    "recommended STT / decision-head / vision models (always the user's choice)"
    "Tauri settings window (AppImage to \$PREFIX/bin, .desktop entry)"
    "speech-to-text backend (reuse an existing vocalinux install or a whisper backend)"
    "vision grounding server deps (UI-TARS via vLLM / transformers)"
    "optional bar widget, attention panel and OSD for the Noctalia shell"
    "~/.config/utter/config.toml from the shipped default"
)
COMP_SIZE=(
    "varies (distro packages)"
    "~6 MB download"
    "<10 KB"
    "several GB per accepted tier"
    "release AppImage (tens of MB)"
    "varies (existing install or your own)"
    "varies (vLLM/transformers stack)"
    "<100 KB"
    "<10 KB"
)
COMP_SUDO=(1 0 0 0 0 0 0 0 0)

TOTAL=9
DECISION=()      # yes | no | skip
REC=()           # recommended default: yes | no
ENABLE_UNITS=0
OVERWRITE_CONFIG=0
MODELS_YES=""    # csv of accepted tier keys

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
# resolve release
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
                say "  querying: $api"
                VER="$(curl -fsSL "$api" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
                [[ -n "$VER" ]] || die "could not resolve the latest release for $UTTER_REPO"
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
# download + verify
# --------------------------------------------------------------------------- #
SUMS_FETCHED=0
CORE_FETCHED=0
CORE_VERIFIED=0
GUI_FETCHED=0
GUI_ASSET=""

fetch() {
    # fetch <asset> — download to $TMP/<asset>
    local asset="$1"
    local url="$BASE_URL/$asset"
    if (( DRY_RUN )); then
        printf '  [dry-run] download %s\n' "$url"
        return 0
    fi
    printf '  [get] %s\n' "$url"
    curl -fsSL --retry 3 --retry-delay 2 -o "$TMP/$asset" "$url" \
        || die "download failed: $url"
}

verify() {
    # verify <asset> — check against sha256sums.txt
    local asset="$1"
    if (( DRY_RUN )); then
        printf '  [dry-run] verify sha256 of %s against %s\n' "$asset" "$SUMS"
        return 0
    fi
    [[ -f "$TMP/$SUMS" ]] || die "missing $SUMS (cannot verify $asset)"
    local want got
    want="$(awk -v a="$asset" '$2==a || $2=="*"a {print $1}' "$TMP/$SUMS" | head -1)"
    [[ -n "$want" ]] || die "$asset not listed in $SUMS"
    got="$(sha256sum "$TMP/$asset" | awk '{print $1}')"
    if [[ "$want" != "$got" ]]; then
        die "sha256 mismatch for $asset: want $want got $got"
    fi
    printf '  [ok] sha256 %s %s\n' "${got:0:16}…" "$asset"
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
    CORE_VERIFIED=1
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
    [[ -n "$CORE_TMP_ROOT" ]] && return 0
    fetch_core
    if (( DRY_RUN )); then
        CORE_TMP_ROOT="$TMP/extract/<core>"
        return 0
    fi
    mkdir -p "$TMP/extract"
    tar -xzf "$TMP/$CORE_TARBALL" -C "$TMP/extract"
    CORE_TMP_ROOT="$(find "$TMP/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [[ -n "$CORE_TMP_ROOT" ]] || die "core tarball has no top-level directory"
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
# prompts
# --------------------------------------------------------------------------- #
ALL_YES=0
ALL_SKIP=0
QUIT=0

ask_yn() {
    # ask_yn <default y|n> <prompt> ; return 0 = yes, 1 = no; sets QUIT/ALL_*
    local def="$1" prompt="$2"
    local hint="[Y/n]"; [[ "$def" == "n" ]] && hint="[y/N]"
    local ans=""
    if (( ALL_YES )); then printf '%s %s ' "$prompt" "$hint"; say "y (all remaining)"; return 0; fi
    if (( ALL_SKIP )); then printf '%s %s ' "$prompt" "$hint"; say "n (skip all remaining)"; return 1; fi
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
# install-state (per-component records; marker dirs, no JSON in bash)
# --------------------------------------------------------------------------- #
D_FILES=(); D_DIRS=(); D_UNITS=(); D_PACKAGES=(); D_KEEP=0

reset_record() { D_FILES=(); D_DIRS=(); D_UNITS=(); D_PACKAGES=(); D_KEEP=0; }

record_component() {
    # record_component <id> <label> <version> <method> <sudo 0|1> <assistant>
    local id="$1" label="$2" version="$3" method="$4" sudo="$5" assistant="$6"
    local dir="$COMP_DIR/$id"
    if (( DRY_RUN )); then
        printf '  [dry-run] record component %s -> %s\n' "$id" "$dir"
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
        printf '  [dry-run] write %s\n' "$STATE_FILE"
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
    say "  [ok] wrote $STATE_FILE"
}

# --------------------------------------------------------------------------- #
# plan / banner
# --------------------------------------------------------------------------- #
print_banner() {
    say "utter installer"
    say "  distro   $DISTRO_ID${DISTRO_LIKE:+ (like: $DISTRO_LIKE)}"
    say "  arch     $ARCH"
    say "  prefix   $PREFIX"
    say "  pkg mgr  $PKG_MGR"
    say "  mode     $MODE"
    say "  release  $UTTER_VERSION"
    say "  python   ${UTTER_PYTHON:-auto-detected}"
}

print_component_preview() {
    say ""
    say "Components (this installer will walk them one by one):"
    local i id
    for i in "${!COMP_IDS[@]}"; do
        id="${COMP_IDS[i]}"
        printf '  %d/%d  %-32s %s\n' "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}" "${COMP_WHAT[i]}"
    done
}

print_plan() {
    print_banner
    print_component_preview
    say ""
    say "Recommended defaults: core, systemd units and GUI; models/STT/perception"
    say "are opt-in. Nothing is downloaded or changed until you confirm."
}

# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #
read_component_field() {
    # read_component_field <dir> <field>
    local f="$1/$2"
    [[ -f "$f" ]] && head -1 "$f" || true
}

do_uninstall() {
    step "uninstall"
    say "  prefix: $PREFIX"

    local dirs=()
    if [[ -d "$COMP_DIR" ]]; then
        while IFS= read -r d; do dirs+=("$d"); done \
            < <(find "$COMP_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    fi

    # Legacy state (installed by an older installer): fall back to known paths.
    if (( ${#dirs[@]} == 0 )); then
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

    if (( ! ASSUME_YES )) && ! is_tty && [[ ! -t 0 ]]; then
        say ""
        say "Nothing removed. Re-run with --yes to remove all installed components:"
        say "    curl -fsSL <install.sh-url> | bash -s -- --uninstall --yes"
        return 0
    fi

    local selection=""
    if (( ASSUME_YES )); then
        selection="all"
    else
        printf '\nSelect components to remove [Enter = all except kept, numbers/comma, a = all, q = quit]: '
        IFS= read -r selection || selection=""
    fi
    selection="${selection// /}"

    case "${selection,,}" in
        q|quit) say "Aborted; nothing removed."; return 0 ;;
        ""|all|a) ;;
    esac

    local remove=()
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

    if (( ${#remove[@]} == 0 )); then
        say "No components selected; nothing removed."
        return 0
    fi

    step "removing"
    local d cid
    for d in "${remove[@]}"; do
        cid="$(basename "$d")"
        say "  - $cid"
        remove_component "$d"
        if (( DRY_RUN )); then
            printf '  [dry-run] remove record %s\n' "$d"
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

    step "done"
    say "Uninstalled. User config in $CONFIG_DIR and downloaded models are kept."
}

remove_component() {
    local d="$1"
    local f u pkg line
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        run "remove $line" rm -f "$line"
    done < <(read_component_lines "$d" files)
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        run "remove $line" rm -rf "$line"
    done < <(read_component_lines "$d" dirs)
    while IFS= read -r u; do
        [[ -n "$u" ]] || continue
        if command -v systemctl >/dev/null 2>&1; then
            run "disable --now $u" systemctl --user disable --now "$u" || true
        fi
    done < <(read_component_lines "$d" units)
    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] || continue
        case "$PKG_MGR" in
            pacman) say "  to remove the package: sudo pacman -Rns $pkg" ;;
            apt)    say "  to remove the package: sudo apt-get remove $pkg" ;;
            dnf)    say "  to remove the package: sudo dnf remove $pkg" ;;
            zypper) say "  to remove the package: sudo zypper remove $pkg" ;;
            *)      say "  to remove the package: $pkg" ;;
        esac
    done < <(read_component_lines "$d" packages)
}

read_component_lines() {
    local f="$1/$2"
    [[ -f "$f" ]] && cat "$f" || true
}

do_uninstall_legacy() {
    note "no per-component install-state found; removing the classic bootstrap paths"
    [[ -f "$GUI_BIN" ]] && run "remove $GUI_BIN" rm -f "$GUI_BIN" || note "no GUI binary"
    [[ -L "$SYMLINK_PATH" ]] && run "remove $SYMLINK_PATH" rm -f "$SYMLINK_PATH" || true
    [[ -f "$ASSISTANT_BIN" ]] && run "remove $ASSISTANT_BIN" rm -f "$ASSISTANT_BIN" || note "no assistant wrapper"
    [[ -f "$DESKTOP_FILE" ]] && run "remove $DESKTOP_FILE" rm -f "$DESKTOP_FILE" || note "no desktop file"
    [[ -f "$RUNNER_UNIT" ]] && run "remove $RUNNER_UNIT" rm -f "$RUNNER_UNIT" || note "no runner unit"
    if [[ -d "$SHARE_DIR" ]]; then
        run "remove $SHARE_DIR" rm -rf "$SHARE_DIR"
    else
        note "no core tree at $SHARE_DIR"
    fi
    if command -v systemctl >/dev/null 2>&1; then
        run "reload systemd user manager" systemctl --user daemon-reload || true
    fi
    [[ -f "$STATE_FILE" ]] && run "remove $STATE_FILE" rm -f "$STATE_FILE" || true
    step "done"
    say "Uninstalled. User config in $CONFIG_DIR and models are kept."
}

if (( UNINSTALL )); then
    do_uninstall
    exit 0
fi

# --------------------------------------------------------------------------- #
# non-interactive gate (curl | bash with no --yes): plan only, change nothing
# --------------------------------------------------------------------------- #
if (( ! ASSUME_YES && ! DRY_RUN )) && ! is_tty; then
    step "plan"
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
# resolve release + asset names
# --------------------------------------------------------------------------- #
step "release"
resolve_release
set_asset_names
say "  repo:    $UTTER_REPO"
say "  version: $VER"
say "  base:    $BASE_URL"

# --------------------------------------------------------------------------- #
# interactive wizard
# --------------------------------------------------------------------------- #
print_banner

present_step() {
    local i="$1" id="$2"
    printf '  what:    %s\n' "${COMP_WHAT[i]}"
    printf '  size:    %s\n' "${COMP_SIZE[i]}"
    if (( COMP_SUDO[i] )) || { [[ "$id" == "gui" ]] && [[ "$MODE" == "package" ]]; }; then
        printf '  sudo:    yes (system package manager)\n'
    else
        printf '  sudo:    no\n'
    fi
    run_dep_probe "$id"
}

declare -A REC_BY_ID=()
compute_recommendations() {
    local miss; miss="$(missing_pkgs)"
    [[ -n "$miss" ]] && REC_BY_ID[deps]=y || REC_BY_ID[deps]=n
    REC_BY_ID[core]=y
    REC_BY_ID[units]=y
    REC_BY_ID[models]=n
    REC_BY_ID[gui]=y
    REC_BY_ID[stt]=n
    REC_BY_ID[perception]=n
    REC_BY_ID[noctalia]=n
    (( WITH_NOCTALIA )) && REC_BY_ID[noctalia]=y
    [[ -f "$CONFIG_FILE" ]] && REC_BY_ID[config]=n || REC_BY_ID[config]=y
}
compute_recommendations

recommend_tiers() {
    # echo lines: key|title|size|reason
    local json="" key
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

wizard() {
    local i id rec
    for i in "${!COMP_IDS[@]}"; do
        id="${COMP_IDS[i]}"
        rec="${REC_BY_ID[$id]:-no}"

        # Noctalia: auto-skip when the shell is not present.
        if [[ "$id" == "noctalia" ]] && (( ! NOCTALIA_PRESENT )); then
            heading "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
            note "Noctalia not detected; skipping. Install it with --with-noctalia once Noctalia is present."
            DECISION[i]="skip"
            continue
        fi

        # --only / --skip
        if ! allowed "$id"; then
            heading "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
            note "skipped (not selected by --only/--skip)"
            DECISION[i]="skip"
            continue
        fi

        heading "$((i+1))" "$TOTAL" "${COMP_LABELS[i]}"
        present_step "$i" "$id"

        # Models are handled per tier.
        if [[ "$id" == "models" ]]; then
            if (( ASSUME_YES )); then
                say "  default: no (recommended) — models are opt-in"
                DECISION[i]="skip"
                continue
            fi
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
                if ask_yn "n" "  Download the ${MODEL_TIER_TITLES[idx]} model (${MODEL_TIER_SIZES[idx]})?"; then
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
            if ask_yn "$rec" "  Install ${COMP_LABELS[i]}?"; then
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
if [[ "${DECISION[2]:-skip}" == "yes" ]] && (( ! ASSUME_YES )); then
    if ask_yn "n" "  Enable and start utter-runner.service now?"; then
        ENABLE_UNITS=1
    fi
    (( QUIT )) && { say "Quit before making any changes."; exit 0; }
fi
if [[ "${DECISION[8]:-skip}" == "yes" ]] && [[ -f "$CONFIG_FILE" ]]; then
    if ask_yn "n" "  $CONFIG_FILE exists — overwrite it with the default?"; then
        OVERWRITE_CONFIG=1
    fi
    (( QUIT )) && { say "Quit before making any changes."; exit 0; }
fi

# --------------------------------------------------------------------------- #
# plan review
# --------------------------------------------------------------------------- #
step "plan review"
sudo_used=0
for i in "${!COMP_IDS[@]}"; do
    id="${COMP_IDS[i]}"
    d="${DECISION[i]:-skip}"
    if [[ "$d" == "yes" ]]; then
        if (( COMP_SUDO[i] )) || { [[ "$id" == "gui" ]] && [[ "$MODE" == "package" ]]; }; then
            printf '  %d. %-32s install (sudo)\n' "$((i+1))" "${COMP_LABELS[i]}"
            sudo_used=1
        else
            printf '  %d. %-32s install\n' "$((i+1))" "${COMP_LABELS[i]}"
        fi
    else
        printf '  %d. %-32s skip\n' "$((i+1))" "${COMP_LABELS[i]}"
    fi
done
if (( ENABLE_UNITS )); then say "  units: enable + start utter-runner.service now"; fi
if (( ${#MODELS_YES} )); then say "  models accepted: $MODELS_YES"; fi
if (( sudo_used )); then say "  sudo: required for one or more selected steps"; else say "  sudo: not required"; fi

if (( ! ASSUME_YES )); then
    if ! ask_yn "y" "Proceed with this plan?"; then
        say "Aborted; nothing changed."
        exit 0
    fi
fi

# --------------------------------------------------------------------------- #
# execution
# --------------------------------------------------------------------------- #
asset_names_ready() { [[ -n "$CORE_TARBALL" ]]; }
asset_names_ready || { resolve_release; set_asset_names; }

exec_deps() {
    step "system deps"
    local missing_csv; missing_csv="$(missing_pkgs | paste -sd, - 2>/dev/null || missing_pkgs | tr '\n' ',')"
    if [[ -z "$missing_csv" ]]; then
        say "  all required dependencies are already present"
        return 0
    fi
    say "  missing packages: $missing_csv"
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
        warn "no package manager command for '$PKG_MGR'; install manually: ${PKGS[*]}"
    elif (( DRY_RUN )); then
        run "install system dependencies" "${INSTALL_CMD[@]}"
    elif sudo -n true 2>/dev/null; then
        run "install system dependencies" "${INSTALL_CMD[@]}"
    else
        warn "no passwordless sudo; printing the command instead:"
        printf '            $ %s\n' "${INSTALL_CMD[*]}"
        note "run it yourself, then re-run"
    fi
    reset_record
    D_PACKAGES=("${PKGS[@]}")
    record_component deps "System deps" "$VER_NUM" "$PKG_MGR" 1 "$ASSISTANT_BIN"
}

exec_core() {
    step "install core (runner + assistant CLI)"
    fetch_core
    run "create $SHARE_DIR" mkdir -p "$SHARE_DIR"
    if (( DRY_RUN )); then
        printf '  [dry-run] extract %s -> %s\n' "$CORE_TARBALL" "$SHARE_DIR"
    else
        local extract="$TMP/extract"
        mkdir -p "$extract"
        tar -xzf "$TMP/$CORE_TARBALL" -C "$extract"
        local top; top="$(find "$extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
        [[ -n "$top" ]] || die "core tarball has no top-level directory"
        rm -rf "$SHARE_DIR"
        mv "$top" "$SHARE_DIR"
        printf '  [ok] extracted core -> %s\n' "$SHARE_DIR"
    fi

    run "create $BIN_DIR" mkdir -p "$BIN_DIR"
    if (( DRY_RUN )); then
        printf '  [dry-run] write %s (wrapper for python -m assistant)\n' "$ASSISTANT_BIN"
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
        printf '  [ok] wrote %s\n' "$ASSISTANT_BIN"
    fi
    reset_record
    D_FILES=("$ASSISTANT_BIN")
    D_DIRS=("$SHARE_DIR")
    record_component core "Core runner + CLI" "$VER_NUM" "tarball" 0 "$ASSISTANT_BIN"
}

exec_units() {
    step "install systemd user units"
    local unit_src=""
    if [[ -f "$SHARE_DIR/install/utter-runner.service" ]]; then
        unit_src="$SHARE_DIR/install/utter-runner.service"
    else
        ensure_core_context
        unit_src="$CORE_CONTEXT/install/utter-runner.service"
    fi
    if [[ -f "$unit_src" ]] || (( DRY_RUN )); then
        run "create $UNIT_DIR" mkdir -p "$UNIT_DIR"
        run "install utter-runner.service" cp "$unit_src" "$RUNNER_UNIT"
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

exec_models() {
    step "models"
    if [[ ! -x "$ASSISTANT_BIN" ]] && [[ ! -d "$SHARE_DIR/assistant" ]]; then
        warn "core/CLI is not installed; cannot pull models. Run with the core step enabled."
        return 0
    fi
    local key src
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
            run "pull $key model ($src)" "$ASSISTANT_BIN" models pull "$src"
        else
            note "no source configured for the $key tier; pull it later with:"
            say "        assistant models pull <hf:org/repo[:file] | https://… | file://…>"
        fi
    done
    reset_record
    D_KEEP=1
    record_component models "Models" "$VER_NUM" "assistant-models" 0 "$ASSISTANT_BIN"
}

exec_gui() {
    step "install GUI ($MODE)"
    choose_gui_asset
    fetch_gui
    if [[ "$MODE" == "appimage" ]]; then
        run "create $BIN_DIR" mkdir -p "$BIN_DIR"
        if (( DRY_RUN )); then
            printf '  [dry-run] install %s -> %s (chmod +x)\n' "$GUI_ASSET" "$GUI_BIN"
            printf '  [dry-run] write %s\n' "$DESKTOP_FILE"
        else
            install -m 0755 "$TMP/$GUI_ASSET" "$GUI_BIN"
            printf '  [ok] installed %s\n' "$GUI_BIN"
            mkdir -p "$APPS_DIR"
            cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=utter Settings
GenericName=Voice Assistant Settings
Comment=Configure the utter voice → desktop-action assistant
Exec=$GUI_BIN
TryExec=$GUI_BIN
Icon=preferences-system
Terminal=false
Categories=Settings;
Keywords=utter;voice;assistant;settings;stt;llm;
StartupNotify=true
StartupWMClass=org.utter.Settings
DESKTOP
            printf '  [ok] wrote %s\n' "$DESKTOP_FILE"
            command -v update-desktop-database >/dev/null 2>&1 && \
                update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
        fi
        local symlink=""
        if [[ ":$PATH:" != *":$BIN_DIR:"* && "$BIN_DIR" != "$HOME/.local/bin" ]] && command -v noctalia >/dev/null 2>&1; then
            run "create $HOME/.local/bin" mkdir -p "$HOME/.local/bin"
            run "symlink $SYMLINK_PATH -> $GUI_BIN (Noctalia left-click)" ln -sf "$GUI_BIN" "$SYMLINK_PATH"
            symlink="$SYMLINK_PATH"
        fi
        reset_record
        D_FILES=("$GUI_BIN" "$DESKTOP_FILE")
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
                printf '            $ %s\n' "${PKG_CMD[*]}"
            fi
        else
            warn "no package manager command for '$PKG_MGR'; install $GUI_ASSET manually"
        fi
        reset_record
        D_PACKAGES=("utter-gui")
        record_component gui "GUI (package)" "$VER_NUM" "package" 1 "$ASSISTANT_BIN"
    fi
}

exec_stt() {
    step "STT backend"
    found_stt
    if command -v vocalinux >/dev/null 2>&1; then
        say "  vocalinux found — the bridge can reuse it (set trigger = \"bridge\" in config.toml)"
    else
        say "  To enable voice, install one of:"
        say "    - vocalinux, then use the bridge (trigger = \"bridge\")"
        say "    - python3 -m pip install --user faster-whisper (local whisper)"
        say "    - a whisper.cpp build (whisper-cli) and set stt.backend = \"whisper_cpp\""
    fi
    reset_record
    record_component stt "STT backend" "$VER_NUM" "advisory" 0 "$ASSISTANT_BIN"
}

exec_perception() {
    step "perception (vision server deps)"
    found_perception
    say "  Vision grounding is optional; the assistant works with a11y-only context."
    say "  To enable it: serve UI-TARS with vLLM and point [vision].base_url at it."
    say "  See docs/INSTALL.md and scripts/serve_*.sh in the extracted core tree."
    reset_record
    record_component perception "Perception deps" "$VER_NUM" "advisory" 0 "$ASSISTANT_BIN"
}

exec_noctalia() {
    step "Noctalia widget (optional)"
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

exec_config() {
    step "config"
    ensure_core_context
    local src="$CORE_CONTEXT/config.default.toml"
    if [[ -f "$CONFIG_FILE" ]] && (( ! OVERWRITE_CONFIG )); then
        note "keeping existing $CONFIG_FILE (not overwritten)"
        return 0
    fi
    if [[ -f "$src" ]] || (( DRY_RUN )); then
        run "create $CONFIG_DIR" mkdir -p "$CONFIG_DIR"
        run "write $CONFIG_FILE from default" cp "$src" "$CONFIG_FILE"
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
        units)      exec_units ;;
        models)     exec_models ;;
        gui)        exec_gui ;;
        stt)        exec_stt ;;
        perception) exec_perception ;;
        noctalia)   exec_noctalia ;;
        config)     exec_config ;;
    esac
}

step "install"
for i in "${!COMP_IDS[@]}"; do
    id="${COMP_IDS[i]}"
    if [[ "${DECISION[i]:-skip}" == "yes" ]]; then
        run_component "$id" || die "component failed: $id"
    fi
done

rebuild_install_json

# --------------------------------------------------------------------------- #
# summary / next steps
# --------------------------------------------------------------------------- #
step "done"
if (( DRY_RUN )); then
    say "Dry-run complete. Re-run without --dry-run to apply."
else
    say "Installed utter $VER into $PREFIX"
    say ""
    say "Next steps:"
    say "  1. Start the runner:   systemctl --user enable --now utter-runner.service"
    say "  2. Check the install:  $ASSISTANT_BIN doctor --json"
    say "  3. Launch the GUI:     ${GUI_BIN}"
    say "  4. Uninstall:          curl -fsSL <install.sh-url> | bash -s -- --uninstall"
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        say ""
        note "$BIN_DIR is not on your PATH; add it: export PATH=\"$BIN_DIR:\$PATH\""
    fi
fi
