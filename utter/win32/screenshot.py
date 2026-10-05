"""Screen capture on Windows via ``mss``.

``capture()`` returns ``(png_path, Rect)`` exactly like the Linux grim and macOS
screencapture backends: the PNG of the primary monitor plus its geometry as an
:class:`utter.types.Rect`.

DPI awareness is handled best-effort by :func:`utter.win32.dpi.ensure_dpi_aware`,
which is invoked before the first capture: it makes the process per-monitor
DPI-aware so the ``mss`` physical-pixel bounds and the pointer APIs share one
coordinate space on scaled displays. Off Windows (or on an old Windows without
the API) the call is a no-op, so the module still imports and the tests still
run on Linux/macOS.

``mss`` is imported lazily, so this module imports on Linux/macOS too.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from utter.types import Rect
from utter.win32.dpi import ensure_dpi_aware as _ensure_dpi_aware

# Stable directory so repeated captures overwrite instead of leaking files.
_SHOT_DIR = Path(os.environ.get("UTTER_SHOT_DIR", tempfile.gettempdir())) / "utter-vision"


def _monitors() -> list[dict]:
    """Raw ``mss`` monitor list; index 0 is the virtual bounding box."""
    import mss  # type: ignore[import-not-found]

    with mss.mss() as sct:
        return [dict(m) for m in sct.monitors]


def monitor_rect(monitor: dict) -> Rect:
    """Convert an ``mss`` monitor dict into a :class:`Rect`."""
    return Rect(
        int(monitor.get("left", 0)),
        int(monitor.get("top", 0)),
        int(monitor.get("width", 0)),
        int(monitor.get("height", 0)),
    )


def _grab_to(path: Path, monitor: dict) -> None:
    import mss  # type: ignore[import-not-found]
    import mss.tools  # type: ignore[import-not-found]

    with mss.mss() as sct:
        shot = sct.grab(monitor)
        # mss >=10 makes ``output`` keyword-only (older versions accept it
        # positionally too, so the keyword form is portable).
        mss.tools.to_png(shot.rgb, shot.size, output=str(path))


def capture_output(monitor_index: int) -> tuple[str, Rect]:
    """Capture a single monitor by index (0 = primary).

    ``mss.monitors[0]`` is the union of all monitors, so the real monitors start
    at index 1; the caller-facing index is therefore offset by one.
    """
    # Per-monitor DPI awareness before mss reports monitor rectangles, so the
    # returned Rect is in the same physical pixel space as the pointer APIs.
    _ensure_dpi_aware()
    monitors = _monitors()
    if monitor_index < 0 or monitor_index + 1 >= len(monitors):
        raise KeyError(
            f"unknown monitor index {monitor_index} (have {max(0, len(monitors) - 1)})"
        )
    monitor = monitors[monitor_index + 1]
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = _SHOT_DIR / f"shot-monitor-{monitor_index}.png"
    _grab_to(path, monitor)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("mss produced an empty screenshot")
    return str(path), monitor_rect(monitor)


def capture() -> tuple[str, Rect]:
    """Capture the primary monitor (index 0)."""
    return capture_output(0)


def total_geometry() -> Rect:
    """Bounding box covering all real monitors."""
    _ensure_dpi_aware()
    rects = [monitor_rect(m) for m in _monitors()[1:]]
    if not rects:
        return Rect(0, 0, 0, 0)
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


__all__ = ["capture", "capture_output", "total_geometry", "monitor_rect"]
