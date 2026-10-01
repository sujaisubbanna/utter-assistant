"""Mouse clicks and scrolling on macOS via Quartz events.

Coordinates are global screen points (the same space ``NSScreen`` and
``CGWindowListCopyWindowInfo`` report, origin top-left of the main display),
which is what :mod:`utter.macos.screenshot` returns as geometry, so vision
grounding needs no scale factor here.
"""
from __future__ import annotations

import time

from utter.types import Action, ActionResult, Tier

_BUTTONS = {"left": 0, "1": 0, "right": 1, "3": 1, "middle": 2, "2": 2}
_SCROLL_DIR = {"up": (0, 1), "down": (0, -1), "left": (1, 0), "right": (-1, 0)}


def _events(button: int):
    import Quartz  # type: ignore[import-not-found]

    if button == 0:
        return Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft
    if button == 1:
        return Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight
    return Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter


def move_to(x: int, y: int) -> ActionResult:
    t0 = time.perf_counter()
    try:
        import Quartz  # type: ignore[import-not-found]

        ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved,
                                            (float(x), float(y)), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD, f"quartz move failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.CLICK_POINT, Tier.KEYBOARD, f"move {x},{y}",
                        (time.perf_counter() - t0) * 1000)


def click_point(x: int, y: int, button: str = "left") -> ActionResult:
    t0 = time.perf_counter()
    code = _BUTTONS.get(str(button).strip().casefold())
    if code is None:
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD, f"unknown button {button!r}",
                            (time.perf_counter() - t0) * 1000)
    try:
        import Quartz  # type: ignore[import-not-found]

        down, up, btn = _events(code)
        pt = (float(x), float(y))
        move = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, pt, btn)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
        time.sleep(0.02)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, down, pt, btn))
        time.sleep(0.04)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, up, pt, btn))
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD, f"quartz click failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.CLICK_POINT, Tier.KEYBOARD, f"click {button} @({x},{y})",
                        (time.perf_counter() - t0) * 1000)


def scroll(direction: str, amount: int = 3) -> ActionResult:
    t0 = time.perf_counter()
    vec = _SCROLL_DIR.get(str(direction).strip().casefold())
    if vec is None:
        return ActionResult(False, Action.SCROLL, Tier.KEYBOARD, f"unknown direction {direction!r}",
                            (time.perf_counter() - t0) * 1000)
    try:
        steps = max(1, int(amount))
    except (TypeError, ValueError):
        steps = 3
    try:
        import Quartz  # type: ignore[import-not-found]

        # Line-based wheel event: (vertical, horizontal) in lines.
        ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2,
                                                  vec[1] * steps, vec[0] * steps)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.SCROLL, Tier.KEYBOARD, f"quartz scroll failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.SCROLL, Tier.KEYBOARD, f"wheel {direction} x{steps}",
                        (time.perf_counter() - t0) * 1000)


__all__ = ["click_point", "move_to", "scroll"]
