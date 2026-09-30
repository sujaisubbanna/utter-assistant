#!/bin/bash
# Start ComfyUI in a fresh terminal: cd, git pull, install requirements, run start.sh.
# Mirrors the user's own shell-history workflow.
#   cd ~/ComfyUI
#   git pull
#   ./.venv/bin/python -m pip install -r requirements.txt
#   ./start.sh
set -uo pipefail

COMFY="${COMFY_DIR:-${HOME}/ComfyUI}"

if [ ! -d "$COMFY" ]; then
    echo "ComfyUI directory not found: $COMFY"
    exec bash
fi
cd "$COMFY" || exec bash

echo "=== ComfyUI: git pull ==="
git pull --ff-only || echo "(git pull failed; continuing)"

PY="$COMFY/.venv/bin/python"
if [ -x "$PY" ]; then
    echo "=== ComfyUI: install requirements ==="
    "$PY" -m pip install -r requirements.txt || echo "(pip install failed; continuing)"
else
    echo "(no venv python at $PY; skipping requirements)"
fi

echo "=== ComfyUI: starting ==="
exec ./start.sh
