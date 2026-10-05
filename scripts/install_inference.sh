#!/usr/bin/env bash
# Idempotent setup for the inference lane (vision + planner).
#
# Creates .venv if missing, installs vLLM + the Hugging Face CLI, and downloads
# the UI-TARS vision model and the Qwen3-4B AWQ planner into models/. Neither
# model can be store-pulled: they ship as multi-file (sharded safetensors)
# repositories, and the model store fetches a single file. This script downloads
# the complete repo directory instead, which is what vLLM needs.
#
# Python: `uv` is used when it is on PATH; otherwise a plain `python3 -m venv`
# plus pip is used. Set UTTER_INFERENCE_PYTHON to pin the interpreter.
#
# Usage:
#   scripts/install_inference.sh
#   setsid bash -c 'scripts/install_inference.sh > /tmp/vllm-install.log 2>&1; echo EXIT=$? >> /tmp/vllm-install.log' &
#
# Env:
#   UTTER_INFERENCE_PYTHON     interpreter for .venv (default: uv's 3.12, else python3)
#   UTTER_VISION_MODEL_ID      HF repo for vision (default ByteDance-Seed/UI-TARS-2B-SFT)
#   UTTER_VISION_MODEL_PATH    local dir for vision (default models/UI-TARS-2B-SFT)
#   UTTER_PLANNER_MODEL_ID     HF repo for the planner (default cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit)
#   UTTER_PLANNER_MODEL_PATH   local dir for the planner (default models/Qwen3-4B-Instruct-2507-AWQ-4bit)
#   UTTER_INSTALL_PLANNER_MODEL  set 0 to skip the planner download
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV=".venv"
VISION_MODEL_ID="${UTTER_VISION_MODEL_ID:-ByteDance-Seed/UI-TARS-2B-SFT}"
VISION_MODEL_DIR="${UTTER_VISION_MODEL_PATH:-models/UI-TARS-2B-SFT}"
PLANNER_MODEL_ID="${UTTER_PLANNER_MODEL_ID:-cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit}"
PLANNER_MODEL_DIR="${UTTER_PLANNER_MODEL_PATH:-models/Qwen3-4B-Instruct-2507-AWQ-4bit}"
INSTALL_PLANNER="${UTTER_INSTALL_PLANNER_MODEL:-1}"
INFERENCE_PYTHON="${UTTER_INFERENCE_PYTHON:-}"
UV="$(command -v uv 2>/dev/null || true)"

echo "[install_inference] repo=$REPO_ROOT"
if [[ -n "$UV" ]]; then
    echo "[install_inference] using uv: $UV"
else
    echo "[install_inference] uv not found; using python3 -m venv + pip"
fi

# --------------------------------------------------------------------------- #
# virtualenv
# --------------------------------------------------------------------------- #
if [[ -x "$VENV/bin/python" ]]; then
    echo "[install_inference] $VENV already exists: $("$VENV/bin/python" --version 2>&1)"
elif [[ -n "$UV" ]]; then
    echo "[install_inference] creating $VENV (uv, python ${INFERENCE_PYTHON:-3.12})"
    "$UV" venv --python "${INFERENCE_PYTHON:-3.12}" "$VENV"
else
    BASE_PY="${INFERENCE_PYTHON:-$(command -v python3 2>/dev/null || true)}"
    if [[ -z "$BASE_PY" ]]; then
        echo "[install_inference] error: no python3 found; set UTTER_INFERENCE_PYTHON" >&2
        exit 1
    fi
    echo "[install_inference] creating $VENV ($("$BASE_PY" --version 2>&1))"
    "$BASE_PY" -m venv "$VENV"
fi

PIP_BOOTSTRAPPED=0
pip_install() {
    if [[ -n "$UV" ]]; then
        "$UV" pip install --python "$VENV/bin/python" "$@"
    else
        if (( ! PIP_BOOTSTRAPPED )); then
            "$VENV/bin/python" -m pip install --upgrade pip
            PIP_BOOTSTRAPPED=1
        fi
        "$VENV/bin/python" -m pip install "$@"
    fi
}

hf_download() {
    # hf_download <hf_repo_id> <local_dir> — the `hf` CLI, the legacy
    # `huggingface-cli`, or the Python API, whichever is present.
    local repo="$1" dir="$2"
    mkdir -p "$dir"
    if [[ -x "$VENV/bin/hf" ]]; then
        "$VENV/bin/hf" download "$repo" --local-dir "$dir"
    elif [[ -x "$VENV/bin/huggingface-cli" ]]; then
        "$VENV/bin/huggingface-cli" download "$repo" --local-dir "$dir"
    else
        "$VENV/bin/python" -c \
            'import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], local_dir=sys.argv[2])' \
            "$repo" "$dir"
    fi
}

model_present() {
    # model_present <dir> — true when dir looks like a complete vLLM checkpoint:
    # a config and at least one weight file (single or sharded index).
    local dir="$1"
    [[ -d "$dir" && -f "$dir/config.json" ]] || return 1
    ls "$dir"/*.safetensors >/dev/null 2>&1 && return 0
    [[ -f "$dir/model.safetensors.index.json" ]] && return 0
    return 1
}

# --------------------------------------------------------------------------- #
# python packages
# --------------------------------------------------------------------------- #
echo "[install_inference] installing vllm"
pip_install "vllm>=0.10"

echo "[install_inference] installing huggingface_hub[cli]"
pip_install "huggingface_hub[cli]"

# Pull requests/Pillow explicitly: client.py uses requests, and prepare_image()
# uses Pillow to downscale screenshots before upload. vLLM usually brings both,
# but make the contract explicit.
echo "[install_inference] installing requests + Pillow"
pip_install "requests>=2.31" "Pillow>=10"

# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
echo "[install_inference] vision model: $VISION_MODEL_ID"
if model_present "$VISION_MODEL_DIR"; then
    echo "[install_inference] vision model already present in $VISION_MODEL_DIR"
else
    echo "[install_inference] downloading $VISION_MODEL_ID -> $VISION_MODEL_DIR"
    hf_download "$VISION_MODEL_ID" "$VISION_MODEL_DIR"
fi

case "${INSTALL_PLANNER,,}" in
    0|no|false|off|skip)
        echo "[install_inference] skipping the planner model (UTTER_INSTALL_PLANNER_MODEL=$INSTALL_PLANNER)"
        ;;
    *)
        echo "[install_inference] planner model: $PLANNER_MODEL_ID"
        if [[ -z "$PLANNER_MODEL_ID" ]]; then
            echo "[install_inference] no planner model id set; skipping"
        elif model_present "$PLANNER_MODEL_DIR"; then
            echo "[install_inference] planner model already present in $PLANNER_MODEL_DIR"
        else
            echo "[install_inference] downloading $PLANNER_MODEL_ID -> $PLANNER_MODEL_DIR"
            hf_download "$PLANNER_MODEL_ID" "$PLANNER_MODEL_DIR"
        fi
        ;;
esac

echo "[install_inference] done"
echo "[install_inference] next: scripts/serve_vision.sh   # http://127.0.0.1:8000/v1 (uitars)"
echo "[install_inference] next: scripts/serve_planner.sh  # http://127.0.0.1:8001/v1 (qwen3-4b)"
