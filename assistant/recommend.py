"""Hardware-aware profile recommendations (PLAN.md §10). Never installs anything."""
from __future__ import annotations

import os
from typing import Any

from utter.hardware import (
    cpu_info as _cpu_info,
    lspci_gpus as _lspci_gpus,
    macos_cpu_info as _macos_cpu_info,
    macos_ram_gb as _macos_ram_gb,
    nvidia_gpus as _nvidia_gpus,
    ram_gb as _ram_gb,
)

from . import util


# --------------------------------------------------------------------------- #
# pullable sources
# --------------------------------------------------------------------------- #
#: Ready-to-pull store sources for recommendation tiers. Only real, documented
#: repos with a single default file go here; a tier with no known Hugging Face
#: source simply omits it (the settings app mirrors this in
#: gui-tauri/src/lib/links.ts PULL_SOURCES). The UI-TARS vision repos and the
#: AWQ planner are sharded safetensors, so they cannot be store-pulled; those
#: tiers carry a ``provision`` script instead (see INSTALL_INFERENCE below).
PULL_SOURCES: dict[str, str] = {}

#: The provisioner for the non-pullable vLLM tiers (vision + decision/planner):
#: it creates .venv, installs vLLM, and downloads the complete repo directories.
INSTALL_INFERENCE = "scripts/install_inference.sh"

#: The documented Hugging Face repo for the 4-bit AWQ planner.
PLANNER_HF_REPO = "cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit"

#: whisper.cpp publishes the ggml checkpoints used by the CPU/Vulkan tiers.
WHISPER_CPP_REPO = "hf:ggerganov/whisper.cpp"


def _whisper_cpp_source(model: str) -> str | None:
    name = (model or "").strip()
    if not name or name == "none":
        return None
    return f"{WHISPER_CPP_REPO}:ggml-{name}.bin"


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #
def _vulkan_present() -> bool:
    return bool(util.which("vulkaninfo"))


def _accel_devices() -> list[str]:
    try:
        return sorted(p for p in os.listdir("/dev/accel") if p.startswith("accel"))
    except OSError:
        return []


def probe_hardware() -> dict[str, Any]:
    from utter import platform
    if platform.is_macos():
        ram = _macos_ram_gb()
        return {
            "cpu": _macos_cpu_info(),
            "ram_gb": ram,
            "gpus": [{"name": "Apple Silicon (Metal)", "vendor": "apple", "vram_gb": ram}],
            "vulkan": False,
            "accel_devices": [],
            "session": "aqua",
        }
    gpus = _nvidia_gpus()
    if not gpus:
        gpus = _lspci_gpus()
    return {
        "cpu": _cpu_info(),
        "ram_gb": _ram_gb(),
        "gpus": gpus,
        "vulkan": _vulkan_present(),
        "accel_devices": _accel_devices(),
        "session": os.environ.get("XDG_SESSION_TYPE", "") or "unknown",
    }


# --------------------------------------------------------------------------- #
# suggestions (PLAN.md §10)
# --------------------------------------------------------------------------- #
def _max_vram(hw: dict[str, Any]) -> float:
    return max((g.get("vram_gb") or 0.0 for g in hw.get("gpus", [])), default=0.0)


def _has_vendor(hw: dict[str, Any], vendor: str) -> bool:
    return any(g.get("vendor") == vendor for g in hw.get("gpus", []))


def suggest(hw: dict[str, Any]) -> dict[str, Any]:
    if hw.get("session") == "aqua" or any(g.get("vendor") == "apple" for g in hw.get("gpus", [])):
        ram = hw.get("ram_gb", 16.0)
        llm_model = "qwen2.5:7b" if ram >= 32 else "qwen2.5:3b"
        vision_model = "llama3.2-vision:11b" if ram >= 16 else "qwen2.5-vl:7b"
        return {
            "stt": {
                "backend": "apple_speech",
                "model": "on-device",
                "device": "metal",
                "est_vram_gb": 0.5,
                "reason": "Apple Speech.framework on-device (Metal accelerated; whisper.cpp fallback)",
            },
            "decision_llm": {
                "model": llm_model,
                "provider": "ollama",
                "device": "metal",
                "est_vram_gb": 4.5 if ram >= 32 else 2.5,
                "reason": f"Ollama Metal runtime on Apple Silicon ({ram:.0f} GB unified memory)",
            },
            "planner_llm": {
                "model": llm_model,
                "provider": "ollama",
                "device": "metal",
                "est_vram_gb": 4.5 if ram >= 32 else 2.5,
                "reason": f"Ollama Metal runtime on Apple Silicon ({ram:.0f} GB unified memory)",
            },
            "vision": {
                "model": vision_model,
                "provider": "ollama",
                "device": "metal",
                "est_vram_gb": 8.0 if "11b" in vision_model else 4.0,
                "reason": "Ollama Metal vision model",
            },
            "zero_model_mode": True,
            "reason": f"{hw['cpu']['model']} / {ram:.0f} GB Unified Memory (Metal)",
        }

    vram = _max_vram(hw)
    nvidia = _has_vendor(hw, "nvidia")
    amd_intel = _has_vendor(hw, "amd") or _has_vendor(hw, "intel")
    ram = hw.get("ram_gb", 0.0)

    if nvidia and vram >= 8:
        stt = {"backend": "faster-whisper", "model": "large-v3-turbo", "device": "cuda",
               "est_vram_gb": 2.0,
               "reason": f"NVIDIA GPU with {vram:.0f} GB VRAM (>=8 GB)"}
    elif amd_intel or hw.get("vulkan"):
        stt = {"backend": "whisper.cpp", "model": "small", "device": "vulkan",
               "est_vram_gb": 1.0, "reason": "Vulkan-capable GPU (AMD/Intel)",
               "source": _whisper_cpp_source("small")}
    else:
        stt = {"backend": "whisper.cpp", "model": "base.en", "device": "cpu",
               "est_ram_gb": 1.0, "reason": "no usable GPU; CPU int8",
               "source": _whisper_cpp_source("base.en")}

    if vram >= 24:
        llm = {"model": "7-8B", "quant": "awq", "est_vram_gb": 6.0,
               "reason": f"{vram:.0f} GB VRAM (>=24 GB)",
               "provision": INSTALL_INFERENCE, "hf_repo": PLANNER_HF_REPO}
    elif vram >= 8:
        llm = {"model": "4B", "quant": "awq", "est_vram_gb": 3.0,
               "reason": f"{vram:.0f} GB VRAM (8-16 GB)",
               "provision": INSTALL_INFERENCE, "hf_repo": PLANNER_HF_REPO}
    else:
        llm = {"model": "1.5-3B", "quant": "q4", "device": "cpu", "est_ram_gb": 3.0,
               "reason": "<=8 GB VRAM; small CPU model or an existing endpoint"}

    if vram >= 16:
        vision = {"model": "UI-TARS-7B", "est_vram_gb": 8.0,
                  "reason": f"{vram:.0f} GB VRAM (>=16 GB)",
                  "provision": INSTALL_INFERENCE}
    elif vram >= 6:
        vision = {"model": "UI-TARS-2B", "est_vram_gb": 4.0,
                  "reason": f"{vram:.0f} GB VRAM (>=6 GB)",
                  "provision": INSTALL_INFERENCE,
                  "hf_repo": "ByteDance-Seed/UI-TARS-2B-SFT"}
    else:
        vision = {"model": "none", "mode": "a11y-only",
                  "reason": "no GPU with >=6 GB VRAM; accessibility-only"}
    if vision["model"] in PULL_SOURCES:
        vision["source"] = PULL_SOURCES[vision["model"]]

    return {
        "stt": stt,
        "decision_llm": dict(llm),
        "planner_llm": dict(llm),
        "vision": vision,
        "zero_model_mode": True,
        "reason": (
            f"{hw['cpu']['model']} / {ram:.0f} GB RAM / "
            + (", ".join(f"{g['name']} ({g['vram_gb']:.0f} GB)" for g in hw.get("gpus", []))
               or "no GPU detected")
        ),
    }


def recommend() -> dict[str, Any]:
    hw = probe_hardware()
    return {"hardware": hw, "suggestions": suggest(hw)}


def human(report: dict[str, Any]) -> str:
    hw = report["hardware"]
    s = report["suggestions"]
    lines = [
        "Hardware:",
        f"  CPU:     {hw['cpu']['model']} ({hw['cpu']['cores']} cores)",
        f"  RAM:     {hw['ram_gb']:.0f} GB",
        f"  Session: {hw['session']}",
    ]
    if hw.get("gpus"):
        for g in hw["gpus"]:
            lines.append(f"  GPU:     {g['name']} ({g['vram_gb']:.0f} GB, {g['vendor']})")
    else:
        lines.append("  GPU:     none detected")

    def get(entry: dict[str, Any]) -> str:
        source = entry.get("source")
        if source:
            return f"\n              install: assistant models pull {source}"
        provision = entry.get("provision")
        if provision:
            repo = entry.get("hf_repo")
            return f"\n              provision: {provision}" + (f" ({repo})" if repo else "")
        return ""

    lines += [
        "",
        "Suggested profile (nothing is installed automatically):",
        f"  STT:          {s['stt']['backend']} / {s['stt']['model']} ({s['stt']['device']})"
        f" — {s['stt']['reason']}{get(s['stt'])}",
        f"  Decision LLM: {s['decision_llm']['model']} {s['decision_llm'].get('quant','')}"
        f" — {s['decision_llm']['reason']}{get(s['decision_llm'])}",
        f"  Planner LLM:  {s['planner_llm']['model']} {s['planner_llm'].get('quant','')}"
        f" — {s['planner_llm']['reason']}{get(s['planner_llm'])}",
        f"  Vision:       {s['vision']['model']} — {s['vision']['reason']}{get(s['vision'])}",
        "",
        "  Zero-model mode is always available (rules + context + a11y).",
    ]
    return "\n".join(lines)
