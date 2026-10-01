#!/usr/bin/env bash
# macos/setup.sh — set up the utter voice daemon on macOS (experimental).
#
#   macos/setup.sh            # create .venv-macos, install deps, write the launchd agent
#   macos/setup.sh --no-agent # only the virtualenv + config
#   macos/setup.sh --uninstall
#
# This is deliberately small. It does NOT install the settings app (use the
# .dmg from the release page) and it does not touch anything outside:
#   <repo>/.venv-macos, ~/.config/utter/config.toml,
#   ~/Library/LaunchAgents/com.utter.assistant.plist, ~/Library/Logs/utter/
#
# Everything here is untested on real hardware by the author of this script
# (it was written on Linux); see docs/MACOS.md for the status matrix.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "macos/setup.sh: this script is for macOS only (uname -s = $(uname -s))" >&2
    exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO/.venv-macos"
LABEL="com.utter.assistant"
RUNNER_LABEL="com.utter.runner"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNNER_AGENT="$HOME/Library/LaunchAgents/$RUNNER_LABEL.plist"
LOGDIR="$HOME/Library/Logs/utter"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/utter"
WITH_AGENT=1

for arg in "$@"; do
    case "$arg" in
        --no-agent) WITH_AGENT=0 ;;
        --uninstall)
            launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
            launchctl bootout "gui/$(id -u)/$RUNNER_LABEL" 2>/dev/null || true
            rm -f "$AGENT" "$RUNNER_AGENT"
            echo "removed launchd agents ($AGENT, $RUNNER_AGENT). The virtualenv at $VENV and your config were kept."
            exit 0 ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

PY="${UTTER_PYTHON:-$(command -v python3.12 || command -v python3 || true)}"
[[ -n "$PY" ]] || { echo "python3 (>= 3.12) not found; brew install python@3.12" >&2; exit 1; }
echo "python: $PY ($("$PY" --version 2>&1))"

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "creating $VENV"
    "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
echo "installing utter[macos] (PyObjC, sounddevice, numpy, pywhispercpp)"
"$VENV/bin/python" -m pip install -e "$REPO[macos]"

# Let the packaged settings app (utter.app) find this checkout and its venv.
APP_SUPPORT="$HOME/Library/Application Support/utter"
mkdir -p "$APP_SUPPORT"
ln -sfn "$REPO" "$APP_SUPPORT/core"
echo "linked $APP_SUPPORT/core -> $REPO (the settings app looks there)"

mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
    cp "$REPO/config.default.toml" "$CONFIG_DIR/config.toml"
    echo "wrote $CONFIG_DIR/config.toml (edit the [macos] section to taste)"
fi

if [[ "$WITH_AGENT" == "1" ]]; then
    mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"
    sed -e "s|@PYTHON@|$VENV/bin/python|g" \
        -e "s|@REPO@|$REPO|g" \
        -e "s|@LOGDIR@|$LOGDIR|g" \
        "$SCRIPT_DIR/$LABEL.plist" > "$AGENT"
    sed -e "s|@PYTHON@|$VENV/bin/python|g" \
        -e "s|@REPO@|$REPO|g" \
        -e "s|@LOGDIR@|$LOGDIR|g" \
        "$SCRIPT_DIR/$RUNNER_LABEL.plist" > "$RUNNER_AGENT"
    for label in "$RUNNER_LABEL" "$LABEL"; do
        launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    done
    launchctl bootstrap "gui/$(id -u)" "$RUNNER_AGENT"
    launchctl bootstrap "gui/$(id -u)" "$AGENT"
    echo "launchd agents installed: $RUNNER_AGENT, $AGENT (logs: $LOGDIR/)"
    # Ask for the privacy permissions from the daemon's python so the prompts
    # attach to that binary (the settings app's Setup page does the same).
    "$VENV/bin/python" -m assistant macos-permissions --request all || true
fi

cat <<EOF

Next, grant permissions in System Settings -> Privacy & Security for
  $VENV/bin/python
(Microphone, Speech Recognition, Accessibility, Input Monitoring, Screen Recording),
then hold the assistant key (Right Command by default) and speak.

Try it without the agent first:
  $VENV/bin/python -m utter.daemon --text "open youtube" --dry-run
  $VENV/bin/python -m utter.daemon
EOF
