#!/usr/bin/env bash
# Serve the small text planner LLM (Qwen3-4B-Instruct-2507, 4-bit) with vLLM's
# OpenAI-compatible API.
#
#   GPU 1 is shared with the UI-TARS grounding server
#   (scripts/serve_vision.sh, port 8000). GPU 0 is left alone.
#   Endpoint: http://127.0.0.1:8001/v1  (model name: qwen3-4b)
#
# The two servers divide GPU 1's ~24GB via --gpu-memory-utilization:
#   vision  : 0.55  (~13.5GB, UI-TARS-2B bf16 + 8k KV)
#   planner : 0.30  (~7.4GB,  4B W4A16 + 4k KV)
# so they must be launched with the matching fractions above.
#
# Usage:
#   scripts/serve_planner.sh
#   setsid bash -c 'scripts/serve_planner.sh > /tmp/vllm-planner.log 2>&1 &'
#
# Env overrides:
#   UTTER_CUDA_VISIBLE_DEVICES (default 1; the outer shell may have
#                                   CUDA_VISIBLE_DEVICES=0,1 exported, so we
#                                   deliberately do NOT inherit it)
#   UTTER_PLANNER_MODEL_PATH   (a local path or Hugging Face repo id; default:
#                                   the model store, else a models/… checkout)
#   UTTER_PLANNER_PORT         (default 8001)
#   UTTER_PLANNER_SERVED_NAME  (default qwen3-4b)
#   UTTER_PLANNER_GPU_MEM_UTIL (default 0.30)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Resolve the model from the store / checkout. There is no documented single
# Hugging Face source for the AWQ checkpoint, so with neither a store entry nor
# a checkout this errors and names UTTER_PLANNER_MODEL_PATH.
source "$REPO_ROOT/scripts/resolve_model.sh"

# Pin to GPU 1. Override the outer CUDA_VISIBLE_DEVICES entirely so a
# globally-exported `0,1` cannot leak GPU 0 (5090) into this process.
export CUDA_VISIBLE_DEVICES="${UTTER_CUDA_VISIBLE_DEVICES:-1}"
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"

MODEL="$(resolve_model "${UTTER_PLANNER_MODEL_PATH:-}" UTTER_PLANNER_MODEL_PATH \
    Qwen3-4B-Instruct-2507-AWQ-4bit "")"
PORT="${UTTER_PLANNER_PORT:-8001}"
SERVED_NAME="${UTTER_PLANNER_SERVED_NAME:-qwen3-4b}"

# The checkpoint is a compressed-tensors W4A16 (group size 128) quantization of
# Qwen/Qwen3-4B-Instruct-2507. vLLM detects the quant method from config.json,
# but we pin --quantization explicitly so a future config edit cannot silently
# fall back to a bf16 load (~8GB -> OOM).

exec .venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name "$SERVED_NAME" \
    --port "$PORT" \
    --max-model-len 4096 \
    --gpu-memory-utilization "${UTTER_PLANNER_GPU_MEM_UTIL:-0.30}" \
    --quantization compressed-tensors \
    --dtype bfloat16
