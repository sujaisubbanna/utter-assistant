#!/usr/bin/env bash
# utter installer (M5) — cross-distro, dry-run by default.
#
#   install/install.sh                 # dry-run: print exactly what it would do
#   install/install.sh --yes           # perform: install deps + enable the unit
#   install/install.sh --yes --no-deps # skip distro packages, only wire the service
#   install/install.sh --yes --no-service  # deps only, don't touch systemd
#
# It never silently changes groups and never removes packages. If it lacks
# root/passwordless sudo it prints the commands instead of failing.
set -euo pipefail

# --------------------------------------------------------------------------- #
# args
# --------------------------------------------------------------------------- #
DRY_RUN=1
ASSUME_YES=0
DO_DEPS=1
DO_SERVICE=1
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --yes|-y) DRY_RUN=0; ASSUME_YES=1 ;;
        --no-deps) DO_DEPS=0 ;;
        --no-service) DO_SERVICE=0 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
UNIT_SRC="$SCRIPT_DIR/utter-runner.service"
UNIT_DST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_DST="$UNIT_DST_DIR/utter-runner.service"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/utter"
STATE_FILE="$STATE_DIR/install.json"

# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
run() {
    # run <description> <command...>
    local desc="$1"; shift
    if (( DRY_RUN )); then
        printf '  [dry-run] %s\n' "$desc"
        printf '            $ %s\n' "$*"
    else
        printf '  [run] %s\n' "$desc"
        "$@"
    fi
}
note() { printf '  note: %s\n' "$*"; }
warn() { printf '  WARNING: %s\n' "$*" >&2; }

say "utter installer (M5)"
if (( DRY_RUN )); then
    say "mode: DRY-RUN (default) — nothing will be changed. Re-run with --yes to apply."
else
    say "mode: APPLY (--yes)"
fi

# --------------------------------------------------------------------------- #
# 1. distro detection
# --------------------------------------------------------------------------- #
step "1. distro detection"
OS_ID=""; OS_LIKE=""
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-}"; OS_LIKE="${ID_LIKE:-}"
fi
say "  /etc/os-release: ID=${OS_ID:-?} ID_LIKE=${OS_LIKE:-?}"

PKG_MGR=""
case " $OS_ID $OS_LIKE " in
    *" arch "*|*" cachyos "*|*" manjaro "*|*" endeavouros "*) PKG_MGR="pacman" ;;
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*) PKG_MGR="apt" ;;
    *" fedora "*|*" rhel "*|*" centos "*|*" nobara "*) PKG_MGR="dnf" ;;
    *" opensuse "*|*" suse "*|*" sles "*) PKG_MGR="zypper" ;;
esac
if [[ -z "$PKG_MGR" ]]; then
    for cand in pacman apt-get dnf zypper; do
        if command -v "$cand" >/dev/null 2>&1; then PKG_MGR="$cand"; break; fi
    done
fi
[[ -n "$PKG_MGR" ]] || { warn "could not detect a package manager"; PKG_MGR="unknown"; }
say "  package manager: $PKG_MGR"

# --------------------------------------------------------------------------- #
# 2. package map
# --------------------------------------------------------------------------- #
step "2. system dependencies"
# logical name -> per-distro package name ("" = not packaged / varies)
pkg_for() {
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

REQUIRED=(wtype ydotool grim wl-clipboard pipewire gtk4 libadwaita)
OPTIONAL=(keyd)
PKGS=()
for logical in "${REQUIRED[@]}"; do
    p="$(pkg_for "$logical")"
    if [[ -n "$p" ]]; then PKGS+=("$p"); else note "$logical: no package mapping for $PKG_MGR"; fi
done
say "  required packages: ${PKGS[*]:-<none mapped>}"
for logical in "${OPTIONAL[@]}"; do
    p="$(pkg_for "$logical")"
    if [[ -n "$p" ]]; then
        say "  optional: $p ($logical) — availability varies by distro"
    else
        note "$logical: not packaged for $PKG_MGR (optional; skip)"
    fi
done

# ydotoold ships with ydotool on most distros; call it out explicitly.
say "  note: ydotoold is provided by the ydotool package on Arch/Fedora; on Debian/Ubuntu it may be a separate build."

if (( DO_DEPS )); then
    case "$PKG_MGR" in
        pacman) INSTALL_CMD=(sudo pacman -S --needed --noconfirm "${PKGS[@]}") ;;
        apt)    INSTALL_CMD=(sudo apt-get install -y "${PKGS[@]}") ;;
        dnf)    INSTALL_CMD=(sudo dnf install -y "${PKGS[@]}") ;;
        zypper) INSTALL_CMD=(sudo zypper --non-interactive install "${PKGS[@]}") ;;
        *)      INSTALL_CMD=() ;;
    esac
    if (( ${#INSTALL_CMD[@]} )); then
        if (( DRY_RUN )); then
            run "install system dependencies" "${INSTALL_CMD[@]}"
        elif sudo -n true 2>/dev/null; then
            run "install system dependencies" "${INSTALL_CMD[@]}"
        else
            warn "no passwordless sudo; printing the command instead of running it:"
            printf '            $ %s\n' "${INSTALL_CMD[*]}"
            note "run it yourself, then re-run this installer with --yes --no-deps"
        fi
    else
        warn "no package manager command for '$PKG_MGR'; install manually: ${PKGS[*]:-<none>}"
    fi
else
    note "--no-deps: skipping distro packages"
fi

# --------------------------------------------------------------------------- #
# 3. input group + /dev/uinput
# --------------------------------------------------------------------------- #
step "3. input injection (uinput)"
IN_INPUT_GROUP=0
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx input; then
    IN_INPUT_GROUP=1
    say "  user $(id -un) is already in the 'input' group"
else
    warn "user $(id -un) is NOT in the 'input' group"
    say "  to enable ydotool/uinput injection, run (as root):"
    say "      sudo usermod -aG input $(id -un)"
    say "  then LOG OUT and back in (group changes need a new session)."
fi

if [[ -e /dev/uinput ]]; then
    say "  /dev/uinput present: $(ls -l /dev/uinput 2>/dev/null | awk '{print $1, $3, $4}')"
else
    warn "/dev/uinput is missing — load the module: sudo modprobe uinput"
fi

# udev rule for uinput (printed, never written silently)
say "  recommended udev rule (write to /etc/udev/rules.d/99-uinput.rules):"
say '      KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'
say "  then: sudo udevadm control --reload-rules && sudo udevadm trigger"
if (( IN_INPUT_GROUP )); then
    note "group membership OK; a re-login is still needed if you just added it."
fi

# --------------------------------------------------------------------------- #
# 4. runner service
# --------------------------------------------------------------------------- #
step "4. runner user service"
say "  unit source: $UNIT_SRC"
say "  unit target: $UNIT_DST"
if [[ ! -f "$UNIT_SRC" ]]; then
    warn "unit file missing: $UNIT_SRC"
fi

if (( DO_SERVICE )); then
    run "create $UNIT_DST_DIR" mkdir -p "$UNIT_DST_DIR"
    install_unit() { sed "s|@REPO@|$REPO|g" "$UNIT_SRC" > "$UNIT_DST"; }
    run "install utter-runner.service (repo: $REPO)" install_unit
    run "reload systemd user manager" systemctl --user daemon-reload
    if (( DRY_RUN )); then
        run "enable + start the runner" systemctl --user enable --now utter-runner.service
    elif (( ASSUME_YES )); then
        run "enable + start the runner" systemctl --user enable --now utter-runner.service
    else
        note "not enabling (pass --yes to apply)"
    fi
else
    note "--no-service: skipping systemd wiring"
fi

# --------------------------------------------------------------------------- #
# 5. legacy units (opt-in, never disturbed)
# --------------------------------------------------------------------------- #
step "5. legacy units (optional)"
LEGACY=(utter-bridge utter-vision utter-planner utter-audio-defaults)
FOUND_LEGACY=()
for u in "${LEGACY[@]}"; do
    if systemctl --user list-unit-files "${u}.service" >/dev/null 2>&1 \
       && systemctl --user list-unit-files "${u}.service" 2>/dev/null | grep -q "${u}.service"; then
        FOUND_LEGACY+=("$u")
    fi
done
if (( ${#FOUND_LEGACY[@]} )); then
    say "  found existing legacy units: ${FOUND_LEGACY[*]}"
    note "these are left untouched; enable them yourself if you want the legacy daemon:"
    for u in "${FOUND_LEGACY[@]}"; do
        say "      systemctl --user enable --now ${u}.service"
    done
else
    say "  no legacy units installed (nothing to preserve)"
fi

# --------------------------------------------------------------------------- #
# 6. record install state
# --------------------------------------------------------------------------- #
step "5b. catalogue installed apps"
# Every installed .desktop app gets a basic launch profile; machine-specific, so
# it is written to ~/.local/share/utter/, never to the repo.
run "catalogue installed apps" python3 "$REPO/scripts/gen_app_catalog.py"

step "6. record install state"
say "  state file: $STATE_FILE"
if (( DRY_RUN )); then
    run "record install state" python3 -m assistant install-state record
else
    if python3 -m assistant install-state record >/dev/null 2>&1; then
        say "  recorded via 'python -m assistant install-state record'"
    else
        note "'assistant' CLI not available; writing a minimal install.json"
        run "create $STATE_DIR" mkdir -p "$STATE_DIR"
        if (( ! DRY_RUN )); then
            cat > "$STATE_FILE" <<JSON
{
  "version": 1,
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "distro": "${OS_ID:-unknown}",
  "package_manager": "${PKG_MGR}",
  "packages": [$(printf '"%s",' "${PKGS[@]}" | sed 's/,$//')],
  "unit": "utter-runner.service",
  "unit_path": "${UNIT_DST}",
  "repo": "${REPO}"
}
JSON
            say "  wrote $STATE_FILE"
        fi
    fi
fi

# --------------------------------------------------------------------------- #
# 7. verify
# --------------------------------------------------------------------------- #
step "7. verify"
SOCK="${UTTER_RUNNER_SOCK:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/utter/runner.sock}"
if [[ -S "$SOCK" ]]; then
    say "  runner socket is up: $SOCK"
    if (( DRY_RUN )); then
        run "doctor" python3 -m assistant doctor --json
    else
        python3 -m assistant doctor --json || warn "doctor failed"
    fi
else
    say "  runner socket not present yet: $SOCK"
    if (( DRY_RUN )); then
        run "recommend" python3 -m assistant recommend --json
    else
        python3 -m assistant recommend --json || warn "recommend failed"
    fi
fi

step "done"
if (( DRY_RUN )); then
    say "Dry-run complete. Re-run with --yes to apply."
else
    say "Install complete."
    say "  status:  systemctl --user status utter-runner.service"
    say "  logs:    journalctl --user -u utter-runner.service -f"
fi
