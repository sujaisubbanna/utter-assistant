"""Hardware-aware profile recommendations (PLAN.md §10). Never installs anything."""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from . import util


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #
def _cpu_info() -> dict[str, Any]:
    model = ""
    cores = 0
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not model and line.lower().startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                if line.lower().startswith("processor"):
                    cores += 1
    except OSError:
        pass
    return {"model": model or "unknown", "cores": cores or os.cpu_count() or 0}


def _ram_gb() -> float:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    match = re.search(r"(\d+)", line)
                    if match:
                        return round(int(match.group(1)) / 1024 / 1024, 1)
    except (OSError, AttributeError, ValueError):
        pass
    return 0.0


def _nvidia_gpus() -> list[dict[str, Any]]:
    if not util.which("nvidia-smi"):
        return []
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            vram = round(int(parts[1]) / 1024, 1)
        except ValueError:
            vram = 0.0
        gpus.append({"name": parts[0], "vendor": "nvidia", "vram_gb": vram})
    return gpus


def _lspci_gpus() -> list[dict[str, Any]]:
    if not util.which("lspci"):
        return []
    try:
        proc = subprocess.run(["lspci", "-nnk"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        low = line.lower()
        if "vga compatible controller" not in low and "3d controller" not in low:
            continue
        vendor = "unknown"
        if "nvidia" in low:
            vendor = "nvidia"
        elif "amd" in low or "advanced micro devices" in low or "ati" in low:
            vendor = "amd"
        elif "intel" in low:
            vendor = "intel"
        gpus.append({"name": line.split(":", 2)[-1].strip(), "vendor": vendor, "vram_gb": 0.0})
    return gpus


def _vulkan_present() -> bool:
    return bool(util.which("vulkaninfo"))


def _accel_devices() -> list[str]:
    try:
        return sorted(p for p in os.listdir("/dev/accel") if p.startswith("accel"))
    except OSError:
        return []


def _macos_cpu_info() -> dict[str, Any]:
    model = "Apple Silicon"
    sysctl = util.which("sysctl")
    if sysctl:
        try:
            proc = subprocess.run([sysctl, "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            out = proc.stdout.strip()
            if out:
                model = out
        except (OSError, subprocess.SubprocessError):
            pass
    return {"model": model, "cores": os.cpu_count() or 8}


def _macos_ram_gb() -> float:
    sysctl = util.which("sysctl")
    if sysctl:
        try:
            proc = subprocess.run([sysctl, "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
            return round(int(proc.stdout.strip()) / (1024 ** 3), 1)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return 16.0


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
               "est_vram_gb": 1.0, "reason": "Vulkan-capable GPU (AMD/Intel)"}
    else:
        stt = {"backend": "whisper.cpp", "model": "base.en", "device": "cpu",
               "est_ram_gb": 1.0, "reason": "no usable GPU; CPU int8"}

    if vram >= 24:
        llm = {"model": "7-8B", "quant": "awq", "est_vram_gb": 6.0,
               "reason": f"{vram:.0f} GB VRAM (>=24 GB)"}
    elif vram >= 8:
        llm = {"model": "4B", "quant": "awq", "est_vram_gb": 3.0,
               "reason": f"{vram:.0f} GB VRAM (8-16 GB)"}
    else:
        llm = {"model": "1.5-3B", "quant": "q4", "device": "cpu", "est_ram_gb": 3.0,
               "reason": "<=8 GB VRAM; small CPU model or an existing endpoint"}

    if vram >= 16:
        vision = {"model": "UI-TARS-7B", "est_vram_gb": 8.0,
                  "reason": f"{vram:.0f} GB VRAM (>=16 GB)"}
    elif vram >= 6:
        vision = {"model": "UI-TARS-2B", "est_vram_gb": 4.0,
                  "reason": f"{vram:.0f} GB VRAM (>=6 GB)"}
    else:
        vision = {"model": "none", "mode": "a11y-only",
                  "reason": "no GPU with >=6 GB VRAM; accessibility-only"}

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
    lines += [
        "",
        "Suggested profile (nothing is installed automatically):",
        f"  STT:          {s['stt']['backend']} / {s['stt']['model']} ({s['stt']['device']})"
        f" — {s['stt']['reason']}",
        f"  Decision LLM: {s['decision_llm']['model']} {s['decision_llm'].get('quant','')}"
        f" — {s['decision_llm']['reason']}",
        f"  Planner LLM:  {s['planner_llm']['model']} {s['planner_llm'].get('quant','')}"
        f" — {s['planner_llm']['reason']}",
        f"  Vision:       {s['vision']['model']} — {s['vision']['reason']}",
        "",
        "  Zero-model mode is always available (rules + context + a11y).",
    ]
    return "\n".join(lines)
