"""KWin actions and screenshots.

Part of the KWin backend, split out of :mod:`utter.context.backends.kwin`.
Actions on *the focused window* (close/minimize/maximize/fullscreen, workspace
moves) go through ``kglobalaccel`` shortcuts, which exist on Plasma 5 and 6
alike; when a concrete window id is given the kdotool or KWin-script path is
used instead (see :mod:`utter.context.backends.kwin_windows`).

Where KWin has no counterpart for a niri action the backend returns
``Outcome(unsupported=True)`` so the router can fall back to the next tier.

Screenshots: ``spectacle -b -n -o <png>`` first, the XDG screenshot portal
second, ``grim`` last (it is unreliable on KWin). Which path is used is
recorded in the facade's ``last_screenshot_method``.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from utter import platform
from utter.context.backends import dbus
from utter.context.backends.kwin_dbus import (
    ACTION_MAP,
    NAME,
    PORTAL,
    _dbus,
    call_portal_screenshot,
    call_set_current_desktop,
    call_shortcut,
    shortcut_for,
)
from utter.context.backends.kwin_windows import (
    _facade,
    _int_or,
    _logical_rect,
    _run,
    _script_action,
    focus_window,
    kdotool_argv,
    kscreen_outputs,
    window_uuid,
)
from utter.context.compositor import (
    CAP_CLOSE,
    CAP_COMPOSITOR_ACTION,
    CAP_MAXIMIZE,
    CAP_MINIMIZE,
    CAP_MOVE_TO_WORKSPACE,
    CAP_SCREENSHOT,
    CAP_SWITCH_WORKSPACE,
    CompositorUnsupported,
    Outcome,
)
from utter.types import Rect


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def _outcome_from_reply(r: dbus.Reply, detail: str, capability: str) -> Outcome:
    argv = [r.argv] if r.argv else []
    if r.ok:
        return Outcome(True, detail, argv, backend=NAME, capability=capability)
    return Outcome(False, f"{detail} failed: {r.error}", argv, backend=NAME, capability=capability)


def _per_window(window_id: Optional[int], action: str, capability: str, shortcut: str,
                kdotool_cmd: Optional[str], n: int = 0) -> Outcome:
    if _facade().dbus_tool() is None and _facade().window_source() is None:
        return Outcome.unsupported_for(NAME, capability, "no D-Bus CLI tool and no kdotool")
    if window_id is None:
        if _facade().dbus_tool() is None:
            return Outcome.unsupported_for(NAME, capability, "no D-Bus CLI tool for kglobalaccel")
        return _outcome_from_reply(_dbus(call_shortcut(shortcut)), f"kglobalaccel {shortcut}", capability)
    uuid = window_uuid(window_id)
    if uuid is None:
        return Outcome(False, f"unknown window id {window_id}", [], backend=NAME, capability=capability)
    src = _facade().window_source()
    if src == "kdotool" and kdotool_cmd:
        argv = kdotool_argv(kdotool_cmd, uuid, *([str(n)] if n else []))
        ok, _, err = _run(argv)
        return Outcome(ok, f"kdotool {kdotool_cmd}" + ("" if ok else f" failed: {err}"), [argv],
                       backend=NAME, capability=capability)
    if src == "script":
        return _script_action(uuid, action, n)
    return Outcome.unsupported_for(NAME, capability, "no window source (install kdotool)")


def close_window(window_id: Optional[int] = None) -> Outcome:
    return _per_window(window_id, "close", CAP_CLOSE, "Window Close", "windowclose")


def minimize_window(window_id: Optional[int] = None) -> Outcome:
    return _per_window(window_id, "minimize", CAP_MINIMIZE, "Window Minimize", "windowminimize")


def maximize_window(window_id: Optional[int] = None) -> Outcome:
    """Activate the target first (when given), then the ``Window Maximize`` shortcut."""
    if _facade().dbus_tool() is None:
        return Outcome.unsupported_for(NAME, CAP_MAXIMIZE, "no D-Bus CLI tool for kglobalaccel")
    ran: list[list[str]] = []
    if window_id is not None:
        if not focus_window(window_id):
            return Outcome(False, f"could not activate window {window_id}", ran, backend=NAME, capability=CAP_MAXIMIZE)
    out = _outcome_from_reply(_dbus(call_shortcut("Window Maximize")), "kglobalaccel Window Maximize", CAP_MAXIMIZE)
    out.argv = ran + out.argv
    return out


def move_window_to_workspace(workspace, window_id: Optional[int] = None) -> Outcome:
    n = _int_or(workspace, 0)
    if n <= 0:
        return Outcome(False, f"bad desktop number {workspace!r}", [], backend=NAME, capability=CAP_MOVE_TO_WORKSPACE)
    return _per_window(window_id, "move_to_desktop", CAP_MOVE_TO_WORKSPACE, f"Window to Desktop {n}",
                       "set_desktop_for_window", n)


def switch_workspace(workspace) -> Outcome:
    if _facade().dbus_tool() is None:
        return Outcome.unsupported_for(NAME, CAP_SWITCH_WORKSPACE, "no D-Bus CLI tool")
    n = _int_or(workspace, 0)
    if n <= 0:
        return Outcome(False, f"bad desktop number {workspace!r}", [], backend=NAME, capability=CAP_SWITCH_WORKSPACE)
    return _outcome_from_reply(_dbus(call_set_current_desktop(n)), f"KWin setCurrentDesktop {n}", CAP_SWITCH_WORKSPACE)


def run_action(command: str, args=()) -> Outcome:
    """Run a niri-style action name on KWin via the mapping table."""
    if _facade().dbus_tool() is None:
        return Outcome.unsupported_for(NAME, CAP_COMPOSITOR_ACTION, "no D-Bus CLI tool")
    c = shortcut_for(command, args)
    if c is None:
        reason = "no KWin equivalent" if command in ACTION_MAP else "unknown action"
        if command in ACTION_MAP and ACTION_MAP[command] and ACTION_MAP[command][0] == "desktop":
            reason = "needs a desktop number"
        return Outcome.unsupported_for(NAME, CAP_COMPOSITOR_ACTION, f"{command}: {reason}")
    return _outcome_from_reply(_dbus(c), f"kwin {command} -> {c.describe()}", CAP_COMPOSITOR_ACTION)


def plan_action(command: str, args=()) -> list[list[str]]:
    c = shortcut_for(command, args)
    tool = _facade().dbus_tool() or "gdbus"
    return [c.argv(tool)] if c is not None else []


# --------------------------------------------------------------------------- #
# screenshots
# --------------------------------------------------------------------------- #
def spectacle_argv(path: str) -> list[str]:
    return ["spectacle", "-b", "-n", "-f", "-o", str(path)]


def _shot_path(path: Optional[str]) -> Path:
    if path:
        return Path(path)
    base = Path(os.environ.get("UTTER_SHOT_DIR", tempfile.gettempdir())) / "utter-vision"
    return base / "shot-kwin.png"


def total_geometry() -> Optional[Rect]:
    rects = [r for r in (_logical_rect(o) for o in kscreen_outputs() if o.get("enabled", True)) if r]
    if not rects:
        return None
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _rect_for(path: Path) -> Rect:
    from utter.context.backends.fallback import png_size

    geom = total_geometry()
    if geom is not None and geom.w > 0 and geom.h > 0:
        return geom
    return png_size(str(path))


def _portal_screenshot(target: Path, timeout: float = 15.0) -> Optional[str]:
    """XDG portal screenshot via ``gdbus``: start a signal monitor, call, wait for Response."""
    gd = platform.which("gdbus")
    if gd is None:
        return None
    token = f"utter{int(time.time() * 1000) % 1000000}"
    monitor = subprocess.Popen([gd, "monitor", "--session", "--dest", PORTAL],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        time.sleep(0.2)
        r = _dbus(call_portal_screenshot(token))
        if not r.ok:
            return None
        deadline = time.monotonic() + timeout
        assert monitor.stdout is not None
        while time.monotonic() < deadline:
            line = monitor.stdout.readline()
            if not line:
                break
            if ".Response" in line and token in line and "'uri'" in line:
                start = line.find("'uri'")
                frag = line[start:]
                q1 = frag.find("<'")
                q2 = frag.find("'>", q1 + 2)
                if q1 >= 0 and q2 > q1:
                    uri = frag[q1 + 2:q2]
                    if uri.startswith("file://"):
                        src = Path(uri[len("file://"):])
                        if src.exists():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            src.replace(target)
                            return str(target)
                    return None
    finally:
        monitor.kill()
    return None


def screenshot(path: Optional[str] = None, output: Optional[str] = None):
    """Capture every output into one PNG; returns ``(png_path, logical_rect)``."""
    target = _shot_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    method = _facade().screenshot_method()
    errors: list[str] = []
    order = [method] if str(_facade()._opt("screenshot") or "auto").lower() != "auto" and method else \
        [m for m in ("spectacle", "portal", "grim") if m == method or platform.which({"portal": "gdbus"}.get(m, m))]
    for m in order:
        if m == "spectacle":
            ok, _, err = _run(spectacle_argv(str(target)), timeout=20.0)
            if ok and target.exists():
                _facade().last_screenshot_method = "spectacle"
                return str(target), _rect_for(target)
            errors.append(f"spectacle: {err or 'no file written'}")
        elif m == "portal":
            got = _portal_screenshot(target)
            if got:
                _facade().last_screenshot_method = "portal"
                return got, _rect_for(target)
            errors.append("portal: no response or denied")
        elif m == "grim":
            argv = ["grim"] + (["-o", output] if output else []) + [str(target)]
            ok, _, err = _run(argv, timeout=10.0)
            if ok and target.exists():
                _facade().last_screenshot_method = "grim"
                return str(target), _rect_for(target)
            errors.append(f"grim: {err}")
    _facade().last_screenshot_method = None
    raise CompositorUnsupported(NAME, CAP_SCREENSHOT, "; ".join(errors) or "no screenshot tool")


__all__ = [
    "close_window", "minimize_window", "maximize_window", "move_window_to_workspace", "switch_workspace",
    "run_action", "plan_action", "spectacle_argv", "total_geometry", "screenshot",
]
