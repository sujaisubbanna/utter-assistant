"""Platform-aware runtime and inference service resolution.

Resolves external AI runtime backends (LLM, Vision, STT, TTS, GPU/Metal) per platform.
On macOS (Apple Silicon):
  - Never assumes CUDA or NVIDIA/AMD GPUs.
  - Relies on ready-made Metal-native tools:
      * LLM: Ollama (primary, http://127.0.0.1:11434/v1), LM Studio, llama.cpp
      * Vision: local VLM (e.g. llama3.2-vision, qwen2.5-vl) served by Ollama/LM Studio
      * STT: Apple Speech.framework on-device, whisper.cpp (Metal), or VocaMac (app CLI)
      * TTS: macOS `say` command
On Linux:
  - Preserves CUDA/ROCm endpoints (vLLM on ports 8001/8000, faster-whisper, espeak-ng).
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from utter import platform
from utter.hardware import gpu_info, probe_macos_gpu

# Default macOS endpoints and models for ready-made tools
DEFAULT_MACOS_LLM_PROVIDER = "ollama"
DEFAULT_MACOS_LLM_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MACOS_LLM_MODEL = "qwen2.5:3b"

DEFAULT_MACOS_VISION_PROVIDER = "ollama"
DEFAULT_MACOS_VISION_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MACOS_VISION_MODEL = "llama3.2-vision:11b"

# VocaMac known binary locations on macOS
VOCAMAC_BINARIES = (
    "/Applications/VocaMac.app/Contents/MacOS/VocaMac",
    "~/Applications/VocaMac.app/Contents/MacOS/VocaMac",
)


def probe_http_models(base_url: str, timeout: float = 0.5) -> tuple[bool, list[str], Optional[str]]:
    """Probe an OpenAI-compatible /v1/models endpoint for connectivity and pulled models.

    Returns (running, model_ids, error_message).
    """
    clean_url = base_url.rstrip("/")
    probe_url = f"{clean_url}/models"
    req = urllib.request.Request(probe_url, headers={"Accept": "application/json", "User-Agent": "utter/runtime"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                models: list[str] = []
                for item in data.get("data", []):
                    mid = item.get("id") or item.get("name")
                    if mid:
                        models.append(str(mid))
                return True, models, None
    except Exception as exc:  # noqa: BLE001
        # If /v1/models failed, and it's Ollama default port 11434, try Ollama's native /api/tags
        if ":11434" in clean_url:
            tags_url = f"{clean_url.split(':11434')[0]}:11434/api/tags"
            try:
                t_req = urllib.request.Request(tags_url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(t_req, timeout=timeout) as t_resp:
                    if t_resp.status == 200:
                        raw = t_resp.read().decode("utf-8", errors="replace")
                        t_data = json.loads(raw)
                        models = [m.get("name") for m in t_data.get("models", []) if m.get("name")]
                        return True, models, None
            except Exception:  # noqa: BLE001
                pass
        return False, [], str(exc)

    return False, [], "Non-200 status code"


def probe_ollama(base_url: str = DEFAULT_MACOS_LLM_URL, timeout: float = 0.5) -> dict[str, Any]:
    """Check if Ollama is installed and running."""
    installed = bool(shutil.which("ollama"))
    running, models, err = probe_http_models(base_url, timeout=timeout)
    status = "ready" if running else ("stopped" if installed else "not_installed")
    return {
        "installed": installed,
        "running": running,
        "endpoint": base_url,
        "models": models,
        "status": status,
        "error": err if not running else None,
    }


def probe_vocamac() -> dict[str, Any]:
    """Check if VocaMac.app is installed on macOS."""
    bin_path = None
    for cand in VOCAMAC_BINARIES:
        p = Path(cand).expanduser()
        if p.is_file():
            bin_path = str(p)
            break
    if not bin_path:
        bin_path = shutil.which("VocaMac")

    installed = bool(bin_path)
    return {
        "installed": installed,
        "path": bin_path,
        "kind": "menu_bar_app",
        "headless_cli": "--transcribe-file <path> --json",
        "status": "installed" if installed else "not_installed",
    }


def probe_runtime(cfg=None, platform_name: Optional[str] = None) -> dict[str, Any]:
    """Produce a structured status report of the platform runtime tools."""
    plat = platform_name or platform.name()
    if cfg is None:
        try:
            from utter.config import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001
            from utter.config import Config
            cfg = Config()

    if plat == platform.MACOS:
        return _probe_runtime_macos(cfg)
    return _probe_runtime_linux(cfg)


def _probe_runtime_macos(cfg) -> dict[str, Any]:
    """macOS (Metal-native) runtime report: Ollama LLM/Vision, Apple Speech, say."""
    gpu = probe_macos_gpu()

    # LLM
    mac_rt = getattr(cfg.macos, "runtime", None)
    llm_provider = getattr(mac_rt, "llm_provider", getattr(cfg.macos, "llm_provider", DEFAULT_MACOS_LLM_PROVIDER))
    llm_base = getattr(mac_rt, "llm_base_url", getattr(cfg.macos, "llm_base_url", DEFAULT_MACOS_LLM_URL))
    llm_model = getattr(mac_rt, "llm_model", getattr(cfg.macos, "llm_model", DEFAULT_MACOS_LLM_MODEL))

    ollama_info = probe_ollama(llm_base)
    llm_avail = False
    llm_models = ollama_info["models"]

    if ollama_info["running"]:
        # Check model presence (exact match or tag match e.g. "qwen2.5:3b" vs "qwen2.5:3b-instruct")
        target_stem = llm_model.split(":")[0].lower()
        model_found = any(m.lower() == llm_model.lower() or m.lower().startswith(target_stem) for m in llm_models)
        if model_found or not llm_models:
            llm_status = "ready"
            llm_avail = True
            llm_msg = f"Ollama running on Metal ({len(llm_models)} model(s) available)"
        else:
            llm_status = "model_missing"
            llm_avail = False
            llm_msg = f"Ollama running on Metal, but model '{llm_model}' not pulled (run 'ollama pull {llm_model}')"
    else:
        llm_avail = False
        if ollama_info["installed"]:
            llm_status = "stopped"
            llm_msg = f"Ollama is installed but not running at {llm_base} (start with 'brew services start ollama' or 'ollama serve')"
        else:
            llm_status = "not_installed"
            llm_msg = "Ollama is not installed (install with 'brew install ollama')"

    llm_role = {
        "provider": llm_provider,
        "endpoint": llm_base,
        "model": llm_model,
        "installed": ollama_info["installed"],
        "running": ollama_info["running"],
        "available": llm_avail,
        "models": llm_models,
        "status": llm_status,
        "message": llm_msg,
    }

    # Vision
    vis_provider = getattr(mac_rt, "vision_provider", getattr(cfg.macos, "vision_provider", DEFAULT_MACOS_VISION_PROVIDER))
    vis_base = getattr(mac_rt, "vision_base_url", getattr(cfg.macos, "vision_base_url", DEFAULT_MACOS_VISION_URL))
    vis_model = getattr(mac_rt, "vision_model", getattr(cfg.macos, "vision_model", DEFAULT_MACOS_VISION_MODEL))

    vis_avail = False
    if ollama_info["running"]:
        v_stem = vis_model.split(":")[0].lower()
        vis_found = any(m.lower() == vis_model.lower() or m.lower().startswith(v_stem) for m in llm_models)
        if vis_found or not llm_models:
            vis_status = "ready"
            vis_avail = True
            vis_msg = f"VLM server running on Metal, model '{vis_model}' ready"
        else:
            vis_status = "model_missing"
            vis_avail = False
            vis_msg = f"VLM server running, but vision model '{vis_model}' not pulled (run 'ollama pull {vis_model}')"
    else:
        vis_avail = False
        vis_status = ollama_info["status"]
        vis_msg = llm_msg

    vision_role = {
        "provider": vis_provider,
        "endpoint": vis_base,
        "model": vis_model,
        "installed": ollama_info["installed"],
        "running": ollama_info["running"],
        "available": vis_avail,
        "models": llm_models,
        "status": vis_status,
        "message": vis_msg,
    }

    # STT
    stt_primary = getattr(cfg.macos, "stt_backend", "whisper_cpp")
    stt_fallback = getattr(cfg.macos, "stt_fallback", "apple_speech")
    apple_avail = platform.has_module("Speech") and platform.has_module("Foundation")
    whisper_avail = platform.has_module("pywhispercpp") or bool(shutil.which("whisper-cli"))
    vocamac_info = probe_vocamac()

    stt_avail = apple_avail or whisper_avail or vocamac_info["installed"]
    if apple_avail:
        stt_status = "ready"
        stt_msg = "Apple Speech.framework on-device active"
    elif whisper_avail:
        stt_status = "ready"
        stt_msg = "whisper.cpp (Metal) active (Apple Speech unavailable)"
    elif vocamac_info["installed"]:
        stt_status = "ready"
        stt_msg = "VocaMac file transcription CLI available"
    else:
        stt_status = "unavailable"
        # VocaMac is never required: the default chain is whisper.cpp ->
        # Apple Speech, so the guidance only names those.
        stt_msg = ("No STT backend available: install pywhispercpp for "
                   "whisper.cpp, or grant Speech.framework access")

    stt_role = {
        "primary": stt_primary,
        "fallback": stt_fallback,
        "apple_speech_available": apple_avail,
        "whisper_cpp_available": whisper_avail,
        "vocamac_installed": vocamac_info["installed"],
        "available": stt_avail,
        "status": stt_status,
        "message": stt_msg,
    }

    # TTS
    tts_engine = getattr(cfg.macos, "tts_backend", "say")
    say_path = shutil.which("say")
    tts_avail = bool(say_path) or tts_engine == "avspeech"
    tts_role = {
        "engine": tts_engine,
        "path": say_path,
        "available": tts_avail,
        "status": "ready" if tts_avail else "unavailable",
        "message": "macOS system say command" if say_path else "say command not found",
    }

    return {
        "platform": "darwin",
        "device": "metal",
        "gpu": gpu,
        "llm": llm_role,
        "vision": vision_role,
        "stt": stt_role,
        "tts": tts_role,
    }


def _probe_runtime_linux(cfg) -> dict[str, Any]:
    """Linux runtime report: CUDA/ROCm GPU, vLLM LLM/Vision, faster-whisper, espeak-ng."""
    gpu = gpu_info()
    tts_engine = shutil.which("espeak-ng") or shutil.which("espeak")
    return {
        "platform": "linux",
        "device": "cuda" if gpu.get("runtime") == "cuda" else ("rocm" if gpu.get("runtime") == "rocm" else "cpu"),
        "gpu": gpu,
        "llm": {
            "provider": "vllm",
            "endpoint": getattr(cfg.router, "llm_base_url", "http://127.0.0.1:8001/v1"),
            "model": getattr(cfg.router, "llm_model", "qwen3-4b"),
            "status": "configured",
            "available": True,
        },
        "vision": {
            "provider": "vllm",
            "endpoint": getattr(cfg.vision, "base_url", "http://127.0.0.1:8000/v1"),
            "model": getattr(cfg.vision, "model", "uitars"),
            "status": "configured",
            "available": getattr(cfg.vision, "enabled", True),
        },
        "stt": {
            "primary": getattr(cfg.stt, "backend", "faster_whisper"),
            "device": getattr(cfg.stt, "device", "cuda"),
            "model": getattr(cfg.stt, "model", "distil-small.en"),
            "status": "configured",
            "available": True,
        },
        "tts": {
            "engine": Path(tts_engine).name if tts_engine else "none",
            "available": bool(tts_engine),
            "status": "ready" if tts_engine else "unavailable",
        },
    }


def resolve_router(cfg=None, platform_name: Optional[str] = None):
    """Resolve the effective RouterConfig for the current platform.

    On macOS, defaults to the Metal-native runtime (Ollama) unless explicitly
    overridden. On Linux, returns cfg.router unchanged.
    """
    plat = platform_name or platform.name()
    if cfg is None:
        try:
            from utter.config import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001
            from utter.config import Config
            cfg = Config()

    # Accept a RouterConfig directly (e.g. the planner passes cfg.router): there
    # is nothing to resolve then. This must run before the Linux branch, which
    # otherwise reads ``cfg.router`` on a RouterConfig and raises.
    from utter.config import RouterConfig
    if isinstance(cfg, RouterConfig):
        return cfg

    if plat != platform.MACOS:
        return cfg.router

    # Build a resolved RouterConfig for macOS
    mac_rt = getattr(cfg.macos, "runtime", None)
    base_url = getattr(mac_rt, "llm_base_url", getattr(cfg.macos, "llm_base_url", DEFAULT_MACOS_LLM_URL))
    model = getattr(mac_rt, "llm_model", getattr(cfg.macos, "llm_model", DEFAULT_MACOS_LLM_MODEL))

    return RouterConfig(
        llm_fallback=getattr(cfg.router, "llm_fallback", True),
        llm_base_url=base_url,
        llm_model=model,
        decision_head_enabled=getattr(cfg.router, "decision_head_enabled", True),
        decide_threshold=getattr(cfg.router, "decide_threshold", 0.5),
    )


def resolve_vision(cfg=None, platform_name: Optional[str] = None):
    """Resolve the effective VisionConfig for the current platform.

    On macOS, defaults to the Metal-native VLM endpoint (Ollama) and ignores CUDA.
    On Linux, returns cfg.vision unchanged.
    """
    plat = platform_name or platform.name()
    if cfg is None:
        try:
            from utter.config import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001
            from utter.config import Config
            cfg = Config()

    from utter.config import VisionConfig
    if isinstance(cfg, VisionConfig):
        return cfg

    if plat != platform.MACOS:
        return cfg.vision

    mac_rt = getattr(cfg.macos, "runtime", None)
    base_url = getattr(mac_rt, "vision_base_url", getattr(cfg.macos, "vision_base_url", DEFAULT_MACOS_VISION_URL))
    model = getattr(mac_rt, "vision_model", getattr(cfg.macos, "vision_model", DEFAULT_MACOS_VISION_MODEL))

    return VisionConfig(
        enabled=getattr(cfg.vision, "enabled", True),
        base_url=base_url,
        model=model,
        target_width=getattr(cfg.vision, "target_width", 1344),
        cuda_visible_devices="",  # Never set or use CUDA on macOS
    )
