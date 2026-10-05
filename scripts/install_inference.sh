#!/usr/bin/env bash
# Thin wrapper for the inference provisioner.
#
# The real implementation lives in `assistant/inference.py` (single source of
# truth; works on Linux, macOS and Windows). This script is kept so existing
# callers keep working: `install.sh`, the systemd/serve docs and anyone with a
# checkout can still run `scripts/install_inference.sh`.
#
# It honours the same environment overrides as the Python implementation (they
# are inherited by the child process):
#   UTTER_INFERENCE_PYTHON       interpreter for .venv (uv: default 3.12)
#   UTTER_INFERENCE_VENV         virtualenv directory (default .venv)
#   UTTER_VISION_MODEL_ID        HF repo for vision (default ByteDance-Seed/UI-TARS-2B-SFT)
#   UTTER_VISION_MODEL_PATH      local dir for vision (default models/UI-TARS-2B-SFT)
#   UTTER_PLANNER_MODEL_ID       HF repo for the planner (default cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit)
#   UTTER_PLANNER_MODEL_PATH     local dir for the planner (default models/Qwen3-4B-Instruct-2507-AWQ-4bit)
#   UTTER_INSTALL_PLANNER_MODEL  set 0 to skip the planner download
#
# Usage:
#   scripts/install_inference.sh
#   python -m assistant inference install [--json]   # same thing, NDJSON
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# An explicit interpreter wins; otherwise prefer python3, then python (Windows
# Git Bash / MSYS has no python3 shim).
PY="${UTTER_INFERENCE_PYTHON:-}"
if [[ -z "$PY" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PY="python3"
    elif command -v python >/dev/null 2>&1; then
        PY="python"
    else
        echo "[install_inference] error: no python3/python found; set UTTER_INFERENCE_PYTHON" >&2
        exit 1
    fi
fi

exec "$PY" -m assistant inference install "$@"
