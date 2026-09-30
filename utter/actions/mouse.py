"""Mouse injection via ydotool (requires ydotoold; see systemd/ydotoold.service).

Coordinate handling
-------------------
Callers (vision grounding, AT-SPI) supply *niri logical* coordinates. On this
niri/wayland build `ydotool mousemove --absolute` does **not** use logical
pixels: measured with a native GTK pointer probe on a 3072x1728 (scale 1.25)
output, a ydotool value of N places the compositor pointer at logical 2*N, i.e.

    ydotool_value = logical * 0.5

so the default factor here is 0.5. `UTTER_MOUSE_SCALE` overrides it if the
mapping changes (e.g. after toggling the configured 1x/2x output scale, or on
another compositor). `UTTER_MOUSE_DIVISOR` is also honoured as a
convenience (`factor = 1 / divisor`). For v1 this targets single-output
absolute coordinates; non-zero logical origins across monitors are best-effort.

No shell is used.
"""
from __future__ import annotations

import os
import subprocess
import time

from utter.types import Action, ActionResult, Tier

_TIMEOUT = 5.0

# Measured ydotool-absolute -> compositor-logical mapping on this host:
# logical = 2 * ydotool, hence factor 0.5 for logical -> ydotool.
_DEFAULT_ABS_FACTOR = 0.5

_BUTTONS = {
    "left": 0xC0, "1": 0xC0,
    "right": 0xC1, "3": 0xC1,
    "middle": 0xC2, "2": 0xC2,
    "side": 0xC3,
    "forward": 0xC5,
    "back": 0xC6,
}

_SCROLL_DIR = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def _ydotool_env() -> dict:
    env = os.environ.copy()
    runtime = env.get("XDG_RUNTIME_DIR")
    if runtime and "YDOTOOL_SOCKET" not in env:
        env["YDOTOOL_SOCKET"] = f"{runtime}/.ydotool_socket"
    return env


def _output_scale() -> float:
    """Focused output scale from niri (diagnostic only; see module docstring)."""
    try:
        from utter.context import niri

        outs = niri.outputs()
        if not outs:
            return 1.0
        name = niri.focused_output_name()
        out = outs.get(name) if name else None
        if out is None and len(outs) == 1:
            out = next(iter(outs.values()))
        if isinstance(out, dict):
            scale = float((out.get("logical") or {}).get("scale", 1.0) or 1.0)
            return scale if scale > 0 else 1.0
    except Exception:  # noqa: BLE001
        pass
    return 1.0


def _abs_factor() -> float:
    """Multiplier from logical input coords to ydotool absolute values."""
    override = os.environ.get("UTTER_MOUSE_SCALE")
    if override:
        try:
            value = float(override)
            if value > 0:
                return value
        except ValueError:
            pass
    divisor = os.environ.get("UTTER_MOUSE_DIVISOR")
    if divisor:
        try:
            value = float(divisor)
            if value > 0:
                return 1.0 / value
        except ValueError:
            pass
    return _DEFAULT_ABS_FACTOR


def _run(argv: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=_TIMEOUT, env=_ydotool_env()
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
    return True, ""


def _abs_xy(x: int, y: int) -> tuple[int, int, float]:
    factor = _abs_factor()
    return int(round(int(x) * factor)), int(round(int(y) * factor)), factor


def move_to(x: int, y: int) -> ActionResult:
    """Move the pointer to logical (x, y) without clicking (useful for hover)."""
    t0 = time.perf_counter()
    px, py, factor = _abs_xy(x, y)
    ok, err = _run(["ydotool", "mousemove", "--absolute", "-x", str(px), "-y", str(py)])
    detail = (f"mousemove abs {px},{py} (logical {x},{y}, factor {factor:g}, "
              f"output scale {_output_scale():g})") if ok else err
    return ActionResult(ok, Action.CLICK_POINT, Tier.KEYBOARD, detail,
                        (time.perf_counter() - t0) * 1000)


def click_point(x: int, y: int, button: str = "left") -> ActionResult:
    """Move the pointer to logical (x, y) and click `button`."""
    t0 = time.perf_counter()
    code = _BUTTONS.get(str(button).strip().casefold())
    if code is None:
        return ActionResult(False, Action.CLICK_POINT, Tier.KEYBOARD,
                            f"unknown button {button!r}",
                            (time.perf_counter() - t0) * 1000)

    px, py, factor = _abs_xy(x, y)
    move = ["ydotool", "mousemove", "--absolute", "-x", str(px), "-y", str(py)]
    click = ["ydotool", "click", hex(code)]

    ok, err = _run(move)
    if ok:
        ok, err = _run(click)
    detail = (f"mousemove abs {px},{py} (logical {x},{y}, factor {factor:g}); "
              f"click {hex(code)}") if ok else err
    return ActionResult(ok, Action.CLICK_POINT, Tier.KEYBOARD, detail,
                        (time.perf_counter() - t0) * 1000)


def scroll(direction: str, amount: int = 3) -> ActionResult:
    """Scroll the wheel: direction in up/down/left/right, `amount` steps."""
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
    dx, dy = vec[0] * steps, vec[1] * steps
    argv = ["ydotool", "mousemove", "--wheel", "-x", str(dx), "-y", str(dy)]
    ok, err = _run(argv)
    detail = f"wheel {direction} x{steps} ({dx},{dy})" if ok else err
    return ActionResult(ok, Action.SCROLL, Tier.KEYBOARD, detail,
                        (time.perf_counter() - t0) * 1000)


__all__ = ["click_point", "move_to", "scroll"]
