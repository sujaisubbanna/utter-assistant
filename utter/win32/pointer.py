"""Mouse movement, clicks and scrolling on Windows.

Coordinates are global screen pixels (the same space ``GetCursorPos`` and
``EnumDisplayMonitors`` report, origin top-left of the primary display), which
is what the Windows screenshot backend returns as geometry, so vision
grounding needs no scale factor here.

Movement uses ``SetCursorPos``; button/wheel events use ``mouse_event``. Both
are simple, widely-available Win32 entry points; ``ctypes.windll`` is touched
only inside the helpers, never at import time.
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

from ..types import Action, ActionResult, Tier

# MOUSEEVENTF_* flags.
_MOVE = 0x0001
_LEFTDOWN, _LEFTUP = 0x0002, 0x0004
_RIGHTDOWN, _RIGHTUP = 0x0008, 0x0010
_MIDDLEDOWN, _MIDDLEUP = 0x0020, 0x0040
_WHEEL, _HWHEEL = 0x0800, 0x1000
_WHEEL_DELTA = 120

#: Button name -> (down flag, up flag).
_BUTTONS = {
    "left": (_LEFTDOWN, _LEFTUP), "1": (_LEFTDOWN, _LEFTUP),
    "right": (_RIGHTDOWN, _RIGHTUP), "3": (_RIGHTDOWN, _RIGHTUP),
    "middle": (_MIDDLEDOWN, _MIDDLEUP), "2": (_MIDDLEDOWN, _MIDDLEUP),
}

#: Direction -> (horizontal notches, vertical notches); +x right, +y up.
_SCROLL_DIR = {
    "up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0),
}


def _user32():
    import ctypes

    return ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]


def _mouse_event(user32, flags: int, data: int = 0) -> None:
    user32.mouse_event(int(flags) & 0xFFFFFFFF, 0, 0, int(data), 0)


def _set_cursor(user32, x: int, y: int) -> None:
    if not user32.SetCursorPos(int(x), int(y)):
        raise OSError("SetCursorPos failed")


def move_to(x: int, y: int) -> ActionResult:
    """Move the pointer to screen (x, y) without clicking (useful for hover)."""
    t0 = time.perf_counter()
    try:
        _set_cursor(_user32(), int(x), int(y))
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD,
                            f"win32 move failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.CLICK_POINT, Tier.KEYBOARD, f"move {x},{y}",
                        (time.perf_counter() - t0) * 1000)


def click_point(x: int, y: int, button: str = "left") -> ActionResult:
    """Move the pointer to screen (x, y) and click ``button``."""
    t0 = time.perf_counter()
    flags: Optional[Tuple[int, int]] = _BUTTONS.get(str(button).strip().casefold())
    if flags is None:
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD,
                            f"unknown button {button!r}",
                            (time.perf_counter() - t0) * 1000)
    down, up = flags
    try:
        user32 = _user32()
        _set_cursor(user32, int(x), int(y))
        time.sleep(0.02)
        _mouse_event(user32, down)
        time.sleep(0.04)
        _mouse_event(user32, up)
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD,
                            f"win32 click failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.CLICK_POINT, Tier.KEYBOARD,
                        f"click {button} @({x},{y})",
                        (time.perf_counter() - t0) * 1000)


def scroll(direction: str, amount: int = 3) -> ActionResult:
    """Scroll the wheel: direction in up/down/left/right, ``amount`` notches."""
    t0 = time.perf_counter()
    vec = _SCROLL_DIR.get(str(direction).strip().casefold())
    if vec is None:
        return ActionResult(False, Action.SCROLL, Tier.KEYBOARD,
                            f"unknown direction {direction!r}",
                            (time.perf_counter() - t0) * 1000)
    try:
        steps = max(1, int(amount))
    except (TypeError, ValueError):
        steps = 3
    try:
        user32 = _user32()
        dx, dy = vec[0] * steps, vec[1] * steps
        if dy:
            _mouse_event(user32, _WHEEL, dy * _WHEEL_DELTA)
        if dx:
            _mouse_event(user32, _HWHEEL, dx * _WHEEL_DELTA)
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.SCROLL, Tier.KEYBOARD,
                            f"win32 scroll failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.SCROLL, Tier.KEYBOARD,
                        f"wheel {direction} x{steps}",
                        (time.perf_counter() - t0) * 1000)


__all__ = ["click_point", "move_to", "scroll"]
