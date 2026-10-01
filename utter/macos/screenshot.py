"""Screen capture on macOS via ``screencapture``.

``capture()`` returns ``(png_path, Rect)`` exactly like the Linux grim backend:
the PNG of the main (or focused) display plus its geometry in global points.
Retina displays write the PNG at physical pixels while the Rect is in points;
grounding works in normalised coordinates so the factor cancels out, and
:mod:`utter.macos.pointer` clicks in points.

Needs the Screen Recording permission for the hosting process.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from utter.types import Rect

_SHOT_DIR = Path(os.environ.get("UTTER_SHOT_DIR", tempfile.gettempdir())) / "utter-vision"
_TIMEOUT = 15.0


def screencapture_argv(path: str, display_index: int | None = None) -> list[str]:
    """Command line for a silent, cursor-less PNG capture (pure; unit-tested)."""
    argv = ["screencapture", "-x", "-t", "png"]
    if display_index is not None:
        argv += ["-D", str(int(display_index) + 1)]  # screencapture numbers displays from 1
    argv.append(str(path))
    return argv


def _displays() -> list[Rect]:
    try:
        from utter.macos.desktop import list_monitors

        return [m.geometry for m in list_monitors() if m.geometry is not None]
    except Exception:  # noqa: BLE001
        return []


def backing_scale_factor() -> float:
    """Logical points to physical pixels ratio (e.g. 2.0 on Retina, 1.0 standard)."""
    try:
        import AppKit  # type: ignore[import-not-found]
        main = AppKit.NSScreen.mainScreen()
        if main is not None:
            return float(main.backingScaleFactor())
    except Exception:  # noqa: BLE001
        pass
    return 1.0


def capture_output(display_index: int) -> tuple[str, Rect]:
    rects = _displays()
    if not rects:
        raise RuntimeError("no displays reported by NSScreen")
    if not 0 <= display_index < len(rects):
        raise KeyError(f"unknown display index {display_index} (have {len(rects)})")
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = _SHOT_DIR / f"shot-display-{display_index}.png"
    try:
        subprocess.run(screencapture_argv(str(path), display_index), check=True, timeout=_TIMEOUT)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"screencapture failed (exit code {exc.returncode}); check Screen Recording "
            "permission under System Settings -> Privacy & Security -> Screen Recording"
        ) from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(
            "screencapture produced an empty file; check Screen Recording permission "
            "under System Settings -> Privacy & Security -> Screen Recording"
        )
    return str(path), rects[display_index]


def capture() -> tuple[str, Rect]:
    """Capture the main display (index 0)."""
    rects = _displays()
    if not rects:
        # Even without monitor geometry from AppKit we can still grab the main
        # display; geometry then comes from the PNG itself (adjusted for Retina).
        _SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = _SHOT_DIR / "shot-display-0.png"
        try:
            subprocess.run(screencapture_argv(str(path), 0), check=True, timeout=_TIMEOUT)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"screencapture failed (exit code {exc.returncode}); check Screen Recording "
                "permission under System Settings -> Privacy & Security -> Screen Recording"
            ) from exc
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(
                "screencapture produced an empty file; check Screen Recording permission "
                "under System Settings -> Privacy & Security -> Screen Recording"
            )
        return str(path), _png_rect(path)
    return capture_output(0)


def _png_rect(path: Path) -> Rect:
    import struct

    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        w, h = struct.unpack(">II", head[16:24])
        scale = backing_scale_factor()
        if scale > 0 and scale != 1.0:
            w, h = int(w / scale), int(h / scale)
        return Rect(0, 0, int(w), int(h))
    except (OSError, struct.error):
        return Rect(0, 0, 0, 0)


def total_geometry() -> Rect:
    rects = _displays()
    if not rects:
        return Rect(0, 0, 0, 0)
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


__all__ = ["capture", "capture_output", "total_geometry", "screencapture_argv", "backing_scale_factor"]
