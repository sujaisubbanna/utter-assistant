"""Shared GPU/hardware probing used by the CLI, runtime resolver and recommender.

This module is the single source of truth for the physical GPU probes that were
previously duplicated across ``utter.cli``, ``utter.runtime`` and
``assistant.recommend``. Every function preserves the exact output shape and
field names of its former home so ``--json`` contracts stay byte-identical.

Probes are intentionally best-effort: any missing tool or unreadable sysfs file
degrades to a structured "unknown"/absent result rather than raising.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from utter import platform


def probe_macos_gpu() -> dict[str, Any]:
    """Report Apple Silicon Metal GPU and unified memory."""
    name = "Apple Silicon (Metal)"
    ram_gb = 16.0

    # Probe brand string and memory via sysctl when available
    sysctl = shutil.which("sysctl")
    if sysctl:
        try:
            proc = subprocess.run([sysctl, "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True, timeout=2)
            brand = proc.stdout.strip()
            if brand and "apple" in brand.lower():
                name = f"{brand} (Metal)"
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            proc_mem = subprocess.run([sysctl, "-n", "hw.memsize"],
                                      capture_output=True, text=True, timeout=2)
            mem_bytes = int(proc_mem.stdout.strip())
            ram_gb = round(mem_bytes / (1024 ** 3), 1)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    return {
        "available": True,
        "name": name,
        "runtime": "metal",
        "unified_memory_gb": ram_gb,
    }


def gpu_info() -> dict[str, Any]:
    """Report physical GPU presence independently from torch availability.

    The returned shape (``available``/``name``/``runtime``) is the contract
    consumed by the CLI capabilities report and the Linux runtime resolver.
    """
    if platform.is_macos():
        return probe_macos_gpu()
    for tool, runtime in (("nvidia-smi", "cuda"), ("rocm-smi", "rocm")):
        path = shutil.which(tool)
        if path:
            try:
                if runtime == "cuda":
                    proc = subprocess.run([path, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=2)
                    name = next((line.strip() for line in proc.stdout.splitlines() if line.strip()), "NVIDIA GPU")
                else:
                    proc = subprocess.run([path, "--showproductname"], capture_output=True, text=True, timeout=2)
                    name = next((line.strip() for line in proc.stdout.splitlines() if "product" in line.casefold()), "AMD GPU")
                if proc.returncode == 0:
                    return {"available": True, "name": name, "runtime": runtime}
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        import torch
        if torch.cuda.is_available():
            runtime = "rocm" if getattr(torch.version, "hip", None) else "cuda"
            return {"available": True, "name": torch.cuda.get_device_name(0), "runtime": runtime}
    except Exception:
        pass
    # DRM vendor ids tell us a GPU is physically enumerated even if its compute
    # runtime is not installed or initialized.
    for device in Path("/sys/class/drm").glob("card[0-9]*/device"):
        try:
            vendor = (device / "vendor").read_text(encoding="ascii").strip().lower()
        except OSError:
            continue
        if vendor in ("0x10de", "0x1002", "0x8086"):
            label = {"0x10de": "NVIDIA GPU", "0x1002": "AMD GPU", "0x8086": "Intel GPU"}[vendor]
            for filename in ("product_name", "product"):
                try:
                    label = (device / filename).read_text(encoding="utf-8").strip() or label
                    break
                except OSError:
                    pass
            return {"available": True, "name": label, "runtime": "unknown"}
    return {"available": False, "name": None, "runtime": "unknown"}


def nvidia_gpus() -> list[dict[str, Any]]:
    """Enumerate NVIDIA GPUs with VRAM via ``nvidia-smi`` (empty when absent)."""
    if not shutil.which("nvidia-smi"):
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


def lspci_gpus() -> list[dict[str, Any]]:
    """Fallback GPU enumeration via ``lspci -nnk`` (vendor + name, no VRAM)."""
    if not shutil.which("lspci"):
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


def macos_ram_gb() -> float:
    """Unified memory in GB via ``sysctl hw.memsize`` (16.0 fallback)."""
    sysctl = shutil.which("sysctl")
    if sysctl:
        try:
            proc = subprocess.run([sysctl, "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
            return round(int(proc.stdout.strip()) / (1024 ** 3), 1)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return 16.0


def macos_cpu_info() -> dict[str, Any]:
    """CPU brand + core count on macOS (``Apple Silicon`` fallback)."""
    model = "Apple Silicon"
    sysctl = shutil.which("sysctl")
    if sysctl:
        try:
            proc = subprocess.run([sysctl, "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            out = proc.stdout.strip()
            if out:
                model = out
        except (OSError, subprocess.SubprocessError):
            pass
    return {"model": model, "cores": os.cpu_count() or 8}


def cpu_info() -> dict[str, Any]:
    """CPU model + logical core count from ``/proc/cpuinfo`` (Linux)."""
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


def ram_gb() -> float:
    """Total system RAM in GB via ``/proc/meminfo`` (0.0 fallback)."""
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
