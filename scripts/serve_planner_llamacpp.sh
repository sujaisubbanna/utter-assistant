#!/usr/bin/env bash
# Serve the small text planner LLM (Qwen3-4B-Instruct-2507, GGUF Q4_K_M) with
# llama.cpp's llama-server OpenAI-compatible API.
#
# This is the macOS/Windows counterpart to scripts/serve_planner.sh (which uses
# vLLM + AWQ on Linux). Endpoint and model name are identical so the router and
# the settings UI do not care which backend is running:
#
#   Endpoint: http://127.0.0.1:8001/v1  (model name: qwen3-4b)
#
# Usage:
#   scripts/serve_planner_llamacpp.sh
#   setsid bash -c 'scripts/serve_planner_llamacpp.sh > /tmp/llamacpp-planner.log 2>&1 &'
#
# Env overrides:
#   UTTER_PLANNER_PORT         (default 8001)
#   UTTER_PLANNER_SERVED_NAME  (default qwen3-4b)
#   UTTER_PLANNER_MODEL_PATH   (GGUF file; default
#                               models/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf)
#   UTTER_LLAMACPP_SERVER      (llama-server path; default models/llama.cpp/llama-server, else PATH)
#   UTTER_PLANNER_CTX          (context size; default 4096)
#   UTTER_LLAMACPP_NGL         (GPU layers; default auto)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${UTTER_PLANNER_PORT:-8001}"
SERVED_NAME="${UTTER_PLANNER_SERVED_NAME:-qwen3-4b}"
CTX="${UTTER_PLANNER_CTX:-4096}"
NGL="${UTTER_LLAMACPP_NGL:-auto}"
GGUF_FILE="Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
MODEL="${UTTER_PLANNER_MODEL_PATH:-$REPO_ROOT/models/Qwen3-4B-Instruct-2507-GGUF/$GGUF_FILE}"

SERVER="${UTTER_LLAMACPP_SERVER:-}"
if [[ -z "$SERVER" ]]; then
    if [[ -x "$REPO_ROOT/models/llama.cpp/llama-server" ]]; then
        SERVER="$REPO_ROOT/models/llama.cpp/llama-server"
    elif [[ -x "$REPO_ROOT/models/llama.cpp/llama-server.exe" ]]; then
        SERVER="$REPO_ROOT/models/llama.cpp/llama-server.exe"
    else
        SERVER="$(command -v llama-server || true)"
    fi
fi
if [[ -z "$SERVER" || ! -x "$SERVER" ]]; then
    echo "[serve_planner_llamacpp] error: llama-server not found. Run" >&2
    echo "  python -m assistant inference install" >&2
    echo "or set UTTER_LLAMACPP_SERVER." >&2
    exit 1
fi
if [[ ! -f "$MODEL" ]]; then
    echo "[serve_planner_llamacpp] error: GGUF model not found at $MODEL. Run" >&2
    echo "  python -m assistant inference install" >&2
    echo "or set UTTER_PLANNER_MODEL_PATH." >&2
    exit 1
fi

# --reasoning off is mandatory: Qwen3-4B-Instruct-2507 is frequently
# misdetected as a thinking model and would otherwise emit reasoning tokens.
# --jinja enables the tool-calling chat template.
exec "$SERVER" \
    --model "$MODEL" \
    --alias "$SERVED_NAME" \
    --host 127.0.0.1 \
    --port "$PORT" \
    -c "$CTX" \
    -ngl "$NGL" \
    -fa auto \
    --jinja \
    --reasoning off \
    -np 1 \
    --no-webui
