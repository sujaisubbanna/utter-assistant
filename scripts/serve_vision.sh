#!/usr/bin/env bash
# Serve the UI-TARS-2B-SFT grounding model with vLLM's OpenAI-compatible API.
#
#   GPU 1 is used; GPU 0 is left alone.
#   Endpoint: http://127.0.0.1:8000/v1  (model name: uitars)
#
# Usage:
#   scripts/serve_vision.sh
#   setsid bash -c 'scripts/serve_vision.sh > /tmp/vllm-serve.log 2>&1 &'
#
# Env overrides:
#   UTTER_CUDA_VISIBLE_DEVICES (default 1; the outer shell may have
#                                   CUDA_VISIBLE_DEVICES=0,1 exported, so we
#                                   deliberately do NOT inherit it)
#   UTTER_VISION_MODEL_PATH    (default models/UI-TARS-2B-SFT)
#   UTTER_VISION_PORT          (default 8000)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pin to GPU 1. Override the outer CUDA_VISIBLE_DEVICES entirely so a
# globally-exported `0,1` cannot leak GPU 0 (5090) into this process.
export CUDA_VISIBLE_DEVICES="${UTTER_CUDA_VISIBLE_DEVICES:-1}"
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"

MODEL="${UTTER_VISION_MODEL_PATH:-models/UI-TARS-2B-SFT}"
PORT="${UTTER_VISION_PORT:-8000}"

# models/UI-TARS-2B-SFT is Qwen2VLForConditionalGeneration (qwen2_vl), which
# vLLM supports natively, so --trust-remote-code is NOT required for this
# checkpoint. If a future UI-TARS build ships custom modeling code, add
#   --trust-remote-code
# to the exec line below (and to scripts/serve_vision_transformers.py).

exec .venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name uitars \
    --port "$PORT" \
    --max-model-len 8192 \
    --limit-mm-per-prompt '{"image":1}' \
    --gpu-memory-utilization "${UTTER_VISION_GPU_MEM_UTIL:-0.55}" \
    --dtype bfloat16
