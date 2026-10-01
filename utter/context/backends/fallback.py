"""Fallback backend for compositors utter does not know.

Reports every window capability as unsupported (structured, never a crash),
still builds a Context (clipboard only) and tries ``grim`` for screenshots,
which works on wlroots-style compositors (sway, river, Hyprland, ...).
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from utter import platform
from utter.context.compositor import (
    CAPABILITIES,
    CAP_SCREENSHOT,
    CompositorUnsupported,
    Outcome,
)
from utter.types import Context, Rect

NAME = "unknown"
_TIMEOUT = 8.0


def available() -> bool:
    return True  # it is always possible to degrade


def tools() -> dict[str, Optional[str]]:
    return {name: platform.which(name) for name in ("grim", "wl-paste", "wtype", "ydotool")}


def capabilities() -> dict[str, bool]:
    caps = {cap: False for cap in CAPABILITIES}
    caps[CAP_SCREENSHOT] = platform.which("grim") is not None
    return caps


def focused_window():
    return None


def list_windows() -> list:
    return []


def find_windows(app_id=None, title_contains=None) -> list:
    return []


def list_monitors() -> list:
    return []


def focus_window(window_id) -> bool:
    return False


def focus_window_on_workspace(window_id) -> bool:
    return False


def build_context(with_a11y: bool = False) -> Context:
    from utter.context.clipboard import get_clipboard

    return Context(focused=None, monitors=[], windows=[], clipboard=get_clipboard())


def _unsupported(capability: str) -> Outcome:
    return Outcome.unsupported_for(NAME, capability, "compositor not recognised")


def close_window(window_id=None) -> Outcome:
    return _unsupported("close")


def minimize_window(window_id=None) -> Outcome:
    return _unsupported("minimize")


def maximize_window(window_id=None) -> Outcome:
    return _unsupported("maximize")


def move_window_to_workspace(workspace, window_id=None) -> Outcome:
    return _unsupported("move_to_workspace")


def switch_workspace(workspace) -> Outcome:
    return _unsupported("switch_workspace")


def run_action(command: str, args=()) -> Outcome:
    return Outcome.unsupported_for(NAME, "compositor_action", f"{command}: compositor not recognised")


def plan_action(command: str, args=()) -> list[list[str]]:
    return []


def png_size(path: str) -> Rect:
    """Width/height from a PNG's IHDR chunk (no image libraries needed)."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"not a PNG: {path}")
    w, h = struct.unpack(">II", head[16:24])
    return Rect(0, 0, int(w), int(h))


def screenshot(path: Optional[str] = None, output: Optional[str] = None):
    grim = platform.which("grim")
    if grim is None:
        raise CompositorUnsupported(NAME, CAP_SCREENSHOT, "no grim and no known compositor API")
    target = Path(path) if path else Path(
        os.environ.get("UTTER_SHOT_DIR", tempfile.gettempdir())) / "utter-vision" / "shot-fallback.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    argv = [grim] + (["-o", output] if output else []) + [str(target)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompositorUnsupported(NAME, CAP_SCREENSHOT, f"grim failed: {exc}") from exc
    if proc.returncode != 0:
        raise CompositorUnsupported(NAME, CAP_SCREENSHOT, f"grim failed: {(proc.stderr or '').strip()}")
    return str(target), png_size(str(target))


def plan() -> dict:
    return {"screenshot": [["grim", "<png>"]]}


__all__ = ["NAME", "available", "tools", "capabilities", "focused_window", "list_windows", "find_windows",
           "list_monitors", "focus_window", "focus_window_on_workspace", "build_context", "close_window",
           "minimize_window", "maximize_window", "move_window_to_workspace", "switch_workspace",
           "run_action", "plan_action", "screenshot", "png_size", "plan"]
