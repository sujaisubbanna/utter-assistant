#!/usr/bin/env bash
# utter-wayland-ready.sh — discover the graphical session, then exec the runner.
#
# systemd user services do not inherit the compositor's environment, so this
# wrapper waits (briefly) for WAYLAND_DISPLAY / DBUS_SESSION_BUS_ADDRESS /
# NIRI_SOCKET / XDG_RUNTIME_DIR to appear, validates the runner socket dir, and
# then execs the modular runner.
#
# Config resolution (first match wins):
#   1. $UTTER_CONFIG
#   2. <repo>/config.runner.toml        (production)
#   3. <repo>/config.m3.toml            (M3 verification / tests)
#   4. <repo>/runner/config.example.toml
#
# Environment overrides:
#   UTTER_REPO      repo root (default: parent of this script's dir)
#   UTTER_PYTHON    python interpreter (default: <repo>/.venv-agent/bin/python, else python3)
#   UTTER_CONFIG    runner config path
#   UTTER_READY_TIMEOUT  seconds to wait for the session (default 30)
set -euo pipefail

log() { printf '[wayland-ready] %s\n' "$*" >&2; }
die() { printf '[wayland-ready] ERROR: %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${UTTER_REPO:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"

# --- interpreter ----------------------------------------------------------- #
if [[ -n "${UTTER_PYTHON:-}" ]]; then
    PY="$UTTER_PYTHON"
elif [[ -x "$REPO/.venv-agent/bin/python" ]]; then
    PY="$REPO/.venv-agent/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    die "no python interpreter found (set UTTER_PYTHON)"
fi

# --- config ---------------------------------------------------------------- #
if [[ -n "${UTTER_CONFIG:-}" ]]; then
    CONFIG="$UTTER_CONFIG"
elif [[ -f "$REPO/config.runner.toml" ]]; then
    CONFIG="$REPO/config.runner.toml"
elif [[ -f "$REPO/config.m3.toml" ]]; then
    CONFIG="$REPO/config.m3.toml"
elif [[ -f "$REPO/runner/config.example.toml" ]]; then
    CONFIG="$REPO/runner/config.example.toml"
else
    die "no runner config found (set UTTER_CONFIG)"
fi
[[ -f "$CONFIG" ]] || die "config not found: $CONFIG"

# --- session discovery ----------------------------------------------------- #
TIMEOUT="${UTTER_READY_TIMEOUT:-30}"
deadline=$(( $(date +%s) + TIMEOUT ))

# XDG_RUNTIME_DIR: prefer the environment, else the standard per-uid path.
if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
export XDG_RUNTIME_DIR

wait_for() {
    # wait_for <name> <test-command...>
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
log "config=$CONFIG"
log "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

# WAYLAND_DISPLAY: a socket under XDG_RUNTIME_DIR (e.g. wayland-1).
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
    log "WAYLAND_DISPLAY not found yet; continuing (runner may still start)"
fi

# DBUS_SESSION_BUS_ADDRESS: the session bus socket.
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    if [[ -S "$XDG_RUNTIME_DIR/bus" ]]; then
        DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    fi
fi
if [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    export DBUS_SESSION_BUS_ADDRESS
    log "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
else
    log "DBUS_SESSION_BUS_ADDRESS not found; continuing"
fi

# NIRI_SOCKET: the niri IPC socket (optional; only for niri users).
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

# --- runner socket dir ----------------------------------------------------- #
SOCK_DIR="$XDG_RUNTIME_DIR/utter"
if [[ ! -d "$SOCK_DIR" ]]; then
    mkdir -p "$SOCK_DIR" || die "cannot create $SOCK_DIR"
fi
chmod 0700 "$SOCK_DIR" 2>/dev/null || true
[[ -d "$SOCK_DIR" ]] || die "runner socket dir missing: $SOCK_DIR"
log "runner socket dir ready: $SOCK_DIR"

# --- exec ------------------------------------------------------------------ #
cd "$REPO"
log "exec: $PY -m runner --config $CONFIG"
exec "$PY" -m runner --config "$CONFIG"
