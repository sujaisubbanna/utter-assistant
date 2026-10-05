#!/usr/bin/env bash
# utter-daemon-ready.sh — discover the graphical session, then exec the daemon.
#
# systemd user services do not inherit the compositor's environment, so this
# wrapper waits (briefly) for WAYLAND_DISPLAY / DBUS_SESSION_BUS_ADDRESS /
# NIRI_SOCKET / XDG_RUNTIME_DIR to appear, then execs `python -m utter.daemon`.
set -euo pipefail

log() { printf '[daemon-ready] %s\n' "$*" >&2; }
die() { printf '[daemon-ready] ERROR: %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${UTTER_REPO:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"

if [[ -n "${UTTER_PYTHON:-}" ]]; then
    PY="$UTTER_PYTHON"
elif [[ -x "$REPO/.venv-agent/bin/python" ]]; then
    PY="$REPO/.venv-agent/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    die "no python interpreter found (set UTTER_PYTHON)"
fi

TIMEOUT="${UTTER_READY_TIMEOUT:-30}"
deadline=$(( $(date +%s) + TIMEOUT ))

if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
export XDG_RUNTIME_DIR

wait_for() {
    local name="$1"; shift
    while ! "$@" >/dev/null 2>&1; do
        if (( $(date +%s) >= deadline )); then
            log "timed out waiting for $name"
            return 1
        fi
        sleep 0.5
    done
    return 0
}

log "repo=$REPO"
log "python=$PY"
log "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    for candidate in wayland-1 wayland-0; do
        if [[ -S "$XDG_RUNTIME_DIR/$candidate" ]]; then
            WAYLAND_DISPLAY="$candidate"
            break
        fi
    done
fi
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    wait_for "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" test -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" \
        || log "continuing without a confirmed Wayland socket"
    export WAYLAND_DISPLAY
    log "WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
else
    log "WAYLAND_DISPLAY not found yet; continuing"
fi

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "$XDG_RUNTIME_DIR/bus" ]]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
if [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    export DBUS_SESSION_BUS_ADDRESS
    log "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
else
    log "DBUS_SESSION_BUS_ADDRESS not found; continuing"
fi

if [[ -z "${NIRI_SOCKET:-}" ]]; then
    for sock in "$XDG_RUNTIME_DIR"/niri.*.sock; do
        if [[ -S "$sock" ]]; then
            NIRI_SOCKET="$sock"
            break
        fi
    done
fi
if [[ -n "${NIRI_SOCKET:-}" ]]; then
    export NIRI_SOCKET
    log "NIRI_SOCKET=$NIRI_SOCKET"
else
    log "NIRI_SOCKET not found (not a niri session?); continuing"
fi

cd "$REPO"
log "exec: $PY -m utter.daemon"
exec "$PY" -m utter.daemon
