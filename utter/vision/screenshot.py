"""Screenshot capture for the vision tier.

Uses `grim` (wlroots) against the running niri compositor and reads monitor
geometry from `niri msg --json`. Dependency-free: only the standard library plus
subprocess calls to `niri` and `grim`.

Contract (DESIGN.md):
    capture() -> (path, Rect total_geometry)
    capture_output(output_name) -> (path, Rect)

The returned ``Rect`` is in niri *logical* coordinates (the same coordinate
space absolute pointers use), for the output that was captured. The PNG itself
is written at the output's physical resolution; because grounding works on
normalized coordinates the scale factor cancels out when the caller passes
``rect.w`` / ``rect.h`` to :func:`utter.vision.client.ground`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from utter import platform
from utter.types import Rect

# Stable directory so repeated captures overwrite instead of leaking files.
_SHOT_DIR = Path(os.environ.get("UTTER_SHOT_DIR", tempfile.gettempdir())) / "utter-vision"

_NIRI = shutil.which("niri") or "niri"
_GRIM = shutil.which("grim") or "grim"


def _run_json(cmd: list[str]) -> dict:
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out or "{}")


def list_outputs() -> dict:
    """Return the raw ``niri msg --json outputs`` mapping (name -> output)."""
    return _run_json([_NIRI, "msg", "--json", "outputs"])


def focused_output_name() -> str | None:
    """Name of the focused output, or ``None`` if niri did not report one."""
    try:
        data = _run_json([_NIRI, "msg", "--json", "focused-output"])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    name = data.get("name")
    return name or None


def _logical_rect(output: dict) -> Rect:
    """Extract the logical geometry of a niri output as a :class:`Rect`."""
    logical = output.get("logical") or {}
    if not logical:
        # Fall back to the current mode's physical size when logical is missing.
        modes = output.get("modes") or []
        idx = output.get("current_mode")
        mode = modes[idx] if isinstance(idx, int) and 0 <= idx < len(modes) else (modes[0] if modes else {})
        return Rect(0, 0, int(mode.get("width", 0)), int(mode.get("height", 0)))
    return Rect(
        int(logical.get("x", 0)),
        int(logical.get("y", 0)),
        int(logical.get("width", 0)),
        int(logical.get("height", 0)),
    )


def _capture_to(path: Path, output_name: str | None = None) -> None:
    """Run grim and write a PNG to ``path``.

    ``grim -o <name>`` captures a single output; with no ``-o`` grim captures
    every output composited into one image.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_GRIM]
    if output_name:
        cmd += ["-o", output_name]
    cmd += [str(path)]
    subprocess.run(cmd, check=True)


def capture_output(output_name: str) -> tuple[str, Rect]:
    """Capture one named niri output.

    Returns ``(png_path, logical_rect)``.
    """
    outputs = list_outputs()
    output = outputs.get(output_name)
    if output is None:
        raise KeyError(f"unknown niri output: {output_name!r} (have {sorted(outputs)})")
    path = _SHOT_DIR / f"shot-{output_name}.png"
    _capture_to(path, output_name)
    return str(path), _logical_rect(output)


def capture() -> tuple[str, Rect]:
    """Capture the focused output (v1: single monitor).

    Returns ``(png_path, logical_rect)`` for the focused output. On niri this is
    :func:`capture_niri` (``grim``, unchanged). On macOS the capture is delegated
    to :mod:`utter.macos.screenshot` (``screencapture``). On Windows it is
    delegated to :mod:`utter.win32.screenshot` (``mss``). On any other compositor
    the active backend's ``screenshot()`` is used (KWin: spectacle -> portal ->
    grim), which raises :class:`utter.context.compositor.CompositorUnsupported`
    when nothing works.
    """
    if platform.is_windows():
        from utter.win32 import screenshot as _win

        return _win.capture()
    if platform.is_macos():
        from utter.macos import screenshot as _mac

        return _mac.capture()
    from utter.context import compositor

    backend = compositor.active()
    if getattr(backend, "NAME", compositor.NIRI) != compositor.NIRI:
        return backend.screenshot()
    return capture_niri()


def capture_niri() -> tuple[str, Rect]:
    """The original niri path: focused output via ``niri msg``, pixels via ``grim``.

    Falls back to the first reported output when niri has no focused output.
    """
    outputs = list_outputs()
    name = focused_output_name()
    if not name or name not in outputs:
        if not outputs:
            raise RuntimeError("niri reported no outputs")
        name = next(iter(outputs))
    return capture_output(name)


def total_geometry() -> Rect:
    """Bounding box covering all outputs in logical coordinates.

    Useful for multi-monitor callers; not required by v1.
    """
    rects = [_logical_rect(o) for o in list_outputs().values()]
    if not rects:
        return Rect(0, 0, 0, 0)
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)
