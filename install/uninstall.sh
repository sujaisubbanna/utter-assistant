#!/usr/bin/env bash
# utter uninstaller (M5) — dry-run by default.
#
#   install/uninstall.sh                 # dry-run: print the reverse actions
#   install/uninstall.sh --yes           # stop/disable units, remove recorded files
#   install/uninstall.sh --yes --purge   # also remove models + config
#
# Package removals are PRINTED, never performed automatically.
set -euo pipefail

DRY_RUN=1
ASSUME_YES=0
PURGE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --yes|-y) DRY_RUN=0; ASSUME_YES=1 ;;
        --purge) PURGE=1 ;;
        -h|--help)
            awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
            exit 0 ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
UNIT_DST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_DST="$UNIT_DST_DIR/utter-runner.service"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/utter"
STATE_FILE="$STATE_DIR/install.json"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/utter"
MODELS_DIR="${UTTER_MODELS:-${XDG_DATA_HOME:-$HOME/.local/share}/utter/models}"

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
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
note() { printf '  note: %s\n' "$*"; }
warn() { printf '  WARNING: %s\n' "$*" >&2; }

say "utter uninstaller (M5)"
if (( DRY_RUN )); then
    say "mode: DRY-RUN (default) — nothing will be changed. Re-run with --yes to apply."
else
    say "mode: APPLY (--yes)$( (( PURGE )) && printf ' + --purge' )"
fi

# --------------------------------------------------------------------------- #
# 1. stop + disable units
# --------------------------------------------------------------------------- #
step "1. stop + disable units"
UNITS=(utter-runner)
# Legacy units are only touched if they exist and were not installed by us.
for u in utter-bridge utter-vision utter-planner utter-audio-defaults; do
    if systemctl --user list-unit-files "${u}.service" 2>/dev/null | grep -q "${u}.service"; then
        UNITS+=("$u")
    fi
done
for u in "${UNITS[@]}"; do
    if systemctl --user list-unit-files "${u}.service" >/dev/null 2>&1 \
       && systemctl --user list-unit-files "${u}.service" 2>/dev/null | grep -q "${u}.service"; then
        run "disable --now ${u}.service" systemctl --user disable --now "${u}.service"
    else
        note "${u}.service not installed; skipping"
    fi
done

# --------------------------------------------------------------------------- #
# 2. remove recorded files
# --------------------------------------------------------------------------- #
step "2. remove installed files"
if [[ -f "$UNIT_DST" ]]; then
    run "remove $UNIT_DST" rm -f "$UNIT_DST"
else
    note "unit not present: $UNIT_DST"
fi
run "reload systemd user manager" systemctl --user daemon-reload

# --------------------------------------------------------------------------- #
# 3. install state
# --------------------------------------------------------------------------- #
step "3. install state"
if [[ -f "$STATE_FILE" ]]; then
    say "  recorded state: $STATE_FILE"
    if command -v python3 >/dev/null 2>&1; then
        run "show recorded state" python3 -m assistant install-state show
    fi
    run "remove $STATE_FILE" rm -f "$STATE_FILE"
else
    note "no install state recorded at $STATE_FILE"
fi

# --------------------------------------------------------------------------- #
# 4. purge (models + config)
# --------------------------------------------------------------------------- #
step "4. purge (models + config)"
if (( PURGE )); then
    if [[ -d "$MODELS_DIR" ]]; then
        run "remove models dir $MODELS_DIR" rm -rf "$MODELS_DIR"
    else
        note "no models dir: $MODELS_DIR"
    fi
    if [[ -d "$CONFIG_DIR" ]]; then
        run "remove config dir $CONFIG_DIR" rm -rf "$CONFIG_DIR"
    else
        note "no config dir: $CONFIG_DIR"
    fi
else
    note "--purge not set: models ($MODELS_DIR) and config ($CONFIG_DIR) are kept"
fi

# --------------------------------------------------------------------------- #
# 5. package removals (printed only)
# --------------------------------------------------------------------------- #
step "5. package removals (printed, never performed)"
say "  The installer does not remove system packages. If you want to, review and run:"
say "      sudo pacman -Rns wtype ydotool grim wl-clipboard pipewire gtk4 libadwaita"
say "      sudo apt-get remove wtype ydotool grim wl-clipboard pipewire libgtk-4-1 libadwaita-1-0"
say "      sudo dnf remove wtype ydotool grim wl-clipboard pipewire gtk4 libadwaita"
say "      sudo zypper remove wtype ydotool grim wl-clipboard pipewire gtk4-devel libadwaita-1-0"
note "pipewire/gtk4/libadwaita are commonly used by other apps — remove with care."

# --------------------------------------------------------------------------- #
# 6. group note
# --------------------------------------------------------------------------- #
step "6. group note"
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx input; then
    say "  user is in the 'input' group (left as-is; remove with: sudo gpasswd -d $(id -un) input)"
else
    say "  user is not in the 'input' group"
fi

step "done"
if (( DRY_RUN )); then
    say "Dry-run complete. Re-run with --yes to apply."
else
    say "Uninstall complete."
fi
