#!/usr/bin/env bash
# Idempotent setup for the inference lane.
#
# Creates .venv (Python 3.12) if missing, installs vLLM and the Hugging Face
# CLI, and downloads UI-TARS-2B-SFT into models/UI-TARS-2B-SFT.
#
# Usage:
#   scripts/install_inference.sh
#   setsid bash -c 'scripts/install_inference.sh > /tmp/vllm-install.log 2>&1; echo EXIT=$? >> /tmp/vllm-install.log' &
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODEL_ID="${UTTER_VISION_MODEL_ID:-ByteDance-Seed/UI-TARS-2B-SFT}"
MODEL_DIR="${UTTER_VISION_MODEL_PATH:-models/UI-TARS-2B-SFT}"
UV="${UV:-uv}"

echo "[install_inference] repo=$REPO_ROOT"

if [ ! -x .venv/bin/python ]; then
    echo "[install_inference] creating .venv (python 3.12)"
    "$UV" venv --python 3.12 .venv
else
    echo "[install_inference] .venv already exists: $(.venv/bin/python --version 2>&1)"
fi

echo "[install_inference] installing vllm"
"$UV" pip install --python .venv/bin/python "vllm>=0.10"

echo "[install_inference] installing huggingface_hub[cli]"
"$UV" pip install --python .venv/bin/python "huggingface_hub[cli]"

# Pull requests/Pillow explicitly: client.py uses requests, and prepare_image()
# uses Pillow to downscale screenshots before upload. vLLM usually brings both,
# but make the contract explicit.
"$UV" pip install --python .venv/bin/python "requests>=2.31" "Pillow>=10"

if [ -f "$MODEL_DIR/model.safetensors.index.json" ] || ls "$MODEL_DIR"/model-*.safetensors >/dev/null 2>&1; then
    echo "[install_inference] model already present in $MODEL_DIR"
else
    echo "[install_inference] downloading $MODEL_ID -> $MODEL_DIR"
    mkdir -p "$MODEL_DIR"
    .venv/bin/hf download "$MODEL_ID" --local-dir "$MODEL_DIR"
fi

echo "[install_inference] done"
