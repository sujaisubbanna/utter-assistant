"""niri backend: a thin wrapper over :mod:`utter.context.niri` (unchanged).

The niri module stays the real implementation (and the provider that
``utter.context.desktop`` hands out when niri is active), so existing niri
behaviour and tests are untouched. This module only adds the uniform extras
every backend must have: capability reporting, window actions by id, workspace
switching, screenshots (``grim``) and the raw ``niri msg action`` runner that
used to live inline in the executor.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from utter import platform
from utter.context import niri as _niri
from utter.context.compositor import (
    CAPABILITIES,
    CAP_COMPOSITOR_ACTION,
    Outcome,
)

NAME = "niri"
_TIMEOUT = 5.0
_DRY_RUN_ENV = "UTTER_DRY_RUN"

# Unchanged provider surface (same objects as utter.context.niri).
focused_window = _niri.focused_window
list_windows = _niri.list_windows
find_windows = _niri.find_windows
list_monitors = _niri.list_monitors
focus_window = _niri.focus_window
focus_window_on_workspace = _niri.focus_window_on_workspace
build_context = _niri.build_context
workspace_for_window = _niri.workspace_for_window
outputs = _niri.outputs
windows = _niri.windows
workspaces = _niri.workspaces
focused_output_name = _niri.focused_output_name


def available() -> bool:
    return platform.which("niri") is not None


def tools() -> dict[str, Optional[str]]:
    return {name: platform.which(name) for name in ("niri", "grim", "wl-paste", "wtype", "ydotool")}


def capabilities() -> dict[str, bool]:
    return {cap: True for cap in CAPABILITIES}


def action_argv(command: str, args=()) -> list[str]:
    """``niri msg action <command> [args...]`` — byte-identical to the old executor path."""
    return ["niri", "msg", "action", str(command), *[str(a) for a in (args or [])]]


def _dry_run() -> bool:
    return (os.environ.get(_DRY_RUN_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


def _run(argv: list[str], capability: str) -> Outcome:
    if _dry_run():
        return Outcome(True, f"niri {argv[3]} (dry-run)", [argv], backend=NAME, capability=capability)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - mirrors the old executor behaviour
        return Outcome(False, f"niri error: {e}", [argv], backend=NAME, capability=capability)
    ok = r.returncode == 0
    detail = f"niri {argv[3]}" if len(argv) > 3 else "niri"
    if not ok:
        detail += f" failed: {(r.stderr or '').strip()}"
    return Outcome(ok, detail, [argv], backend=NAME, capability=capability)


def run_action(command: str, args=()) -> Outcome:
    return _run(action_argv(command, args), CAP_COMPOSITOR_ACTION)


def plan_action(command: str, args=()) -> list[list[str]]:
    return [action_argv(command, args)]


def _id_flag(window_id: Optional[int]) -> list[str]:
    if window_id is None:
        return []
    return ["--id", str(int(window_id))]


def close_window(window_id: Optional[int] = None) -> Outcome:
    return _run(action_argv("close-window", _id_flag(window_id)), "close")


def minimize_window(window_id: Optional[int] = None) -> Outcome:
    return _run(action_argv("minimize-window", _id_flag(window_id)), "minimize")


def maximize_window(window_id: Optional[int] = None) -> Outcome:
    """``maximize-column`` acts on the focused column, so focus the window first."""
    ran: list[list[str]] = []
    if window_id is not None:
        first = _run(action_argv("focus-window", _id_flag(window_id)), "activate")
        ran += first.argv
        if not first.ok:
            return Outcome(False, first.detail, ran, backend=NAME, capability="maximize")
    out = _run(action_argv("maximize-column"), "maximize")
    out.argv = ran + out.argv
    return out


def move_window_to_workspace(workspace, window_id: Optional[int] = None) -> Outcome:
    args: list[str] = []
    if window_id is not None:
        args += ["--window-id", str(int(window_id))]
    args.append(str(workspace))
    return _run(action_argv("move-window-to-workspace", args), "move_to_workspace")


def switch_workspace(workspace) -> Outcome:
    return _run(action_argv("focus-workspace", [str(workspace)]), "switch_workspace")


def screenshot(path: Optional[str] = None, output: Optional[str] = None):
    """``grim`` capture with niri logical geometry (the pre-existing vision path)."""
    from utter.vision import screenshot as shot

    if output:
        return shot.capture_output(output)
    return shot.capture_niri()


def plan() -> dict:
    return {
        "activate": [action_argv("focus-window", ["--id", "<id>"])],
        "close": [action_argv("close-window", ["--id", "<id>"])],
        "minimize": [action_argv("minimize-window", ["--id", "<id>"])],
        "maximize": [action_argv("focus-window", ["--id", "<id>"]), action_argv("maximize-column")],
        "move_to_workspace": [action_argv("move-window-to-workspace", ["--window-id", "<id>", "<n>"])],
        "switch_workspace": [action_argv("focus-workspace", ["<n>"])],
        "screenshot": [["grim", "-o", "<output>", "<png>"]],
        "compositor_action": [action_argv("<command>", ["<args>"])],
        "list_windows": [["niri", "msg", "--json", "windows"]],
        "focused_window": [["niri", "msg", "--json", "focused-window"]],
    }


__all__ = [
    "NAME", "available", "tools", "capabilities", "action_argv", "run_action", "plan_action",
    "focused_window", "list_windows", "find_windows", "list_monitors", "focus_window",
    "focus_window_on_workspace", "build_context", "close_window", "minimize_window",
    "maximize_window", "move_window_to_workspace", "switch_workspace", "screenshot", "plan",
]
