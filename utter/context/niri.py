"""niri compositor context via `niri msg --json` (wlroots / Wayland).

Real output shapes (niri):
  focused-window -> {"id","title","app_id","pid","workspace_id","is_focused",
                     "is_floating","is_fullscreen", ...} or null
  outputs        -> {name: {"name","logical":{"x","y","width","height",
                     "scale","transform"}, "workspaces":[ids]}, ...}
  workspaces     -> [{"id","idx","name","output","is_active","is_focused",
                     "active_window_id"}, ...]
  windows        -> [{"id","app_id","title","pid","workspace_id",...}, ...]

Coordinates in `logical` are logical desktop pixels (physical / scale).
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Optional

from utter.types import Context, FocusedWindow, Monitor, Rect, WindowInfo

NIRI = "niri"
_TIMEOUT = 5.0


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NIRI, "msg", *args],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )


def _run_json(*args: str) -> Any:
    """Run `niri msg --json <args>` and parse stdout. Returns None on failure."""
    try:
        proc = _run("--json", *args)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def outputs() -> dict[str, dict]:
    """Raw output table keyed by connector name (empty dict on failure)."""
    data = _run_json("outputs")
    return data if isinstance(data, dict) else {}


def windows() -> list[dict]:
    data = _run_json("windows")
    return data if isinstance(data, list) else []


def workspaces() -> list[dict]:
    data = _run_json("workspaces")
    return data if isinstance(data, list) else []


def list_windows() -> list[WindowInfo]:
    """All niri windows as WindowInfo records (empty list on failure).

    Missing or malformed keys fall back to dataclass defaults; a single bad
    entry never aborts the whole list.
    """
    out: list[WindowInfo] = []
    for w in windows():
        if not isinstance(w, dict):
            continue
        try:
            out.append(
                WindowInfo(
                    id=int(w.get("id") or 0),
                    app_id=str(w.get("app_id") or ""),
                    title=str(w.get("title") or ""),
                    workspace_id=int(w.get("workspace_id") or 0),
                    pid=int(w.get("pid") or 0),
                    is_focused=bool(w.get("is_focused", False)),
                    is_floating=bool(w.get("is_floating", False)),
                    is_fullscreen=bool(w.get("is_fullscreen", False)),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def find_windows(
    app_id: Optional[str] = None,
    title_contains: Optional[str] = None,
) -> list[WindowInfo]:
    """Windows matching case-insensitive substring filters.

    ``app_id`` matches when the window's app_id *contains* the argument, so
    ``"zen"`` matches ``"zen"``. Both filters are ANDed when supplied.
    """
    app_needle = app_id.lower() if app_id else None
    title_needle = title_contains.lower() if title_contains else None
    result: list[WindowInfo] = []
    for w in list_windows():
        if app_needle is not None and app_needle not in w.app_id.lower():
            continue
        if title_needle is not None and title_needle not in w.title.lower():
            continue
        result.append(w)
    return result


def workspace_for_window(window_id: int) -> Optional[int]:
    """Workspace id owning ``window_id``, or None if unknown."""
    try:
        target = int(window_id)
    except (TypeError, ValueError):
        return None
    for w in list_windows():
        if w.id == target:
            return w.workspace_id
    return None


def _workspace_index(workspace_id: int) -> Optional[int]:
    """Map a niri workspace *id* to its per-output *idx*.

    ``niri msg action focus-workspace`` only accepts a workspace index (or
    name), not the globally-unique workspace id.
    """
    for ws in workspaces():
        if not isinstance(ws, dict):
            continue
        try:
            if int(ws.get("id") or 0) == int(workspace_id):
                return int(ws.get("idx") or 0)
        except (TypeError, ValueError):
            continue
    return None


def _rect_from_logical(logical: Optional[dict]) -> Optional[Rect]:
    if not isinstance(logical, dict):
        return None
    try:
        return Rect(
            x=int(logical.get("x", 0)),
            y=int(logical.get("y", 0)),
            w=int(logical.get("width", 0)),
            h=int(logical.get("height", 0)),
        )
    except (TypeError, ValueError):
        return None


def focused_window() -> Optional[FocusedWindow]:
    """Currently focused window, or None if no window is focused."""
    data = _run_json("focused-window")
    if not isinstance(data, dict) or not data:
        return None
    return FocusedWindow(
        app_id=str(data.get("app_id") or ""),
        title=str(data.get("title") or ""),
        pid=int(data.get("pid") or 0),
        window_id=int(data.get("id") or 0),
        workspace_id=int(data.get("workspace_id") or 0),
        is_floating=bool(data.get("is_floating", False)),
        is_fullscreen=bool(data.get("is_fullscreen", False)),
    )


def list_monitors() -> list[Monitor]:
    """Connected outputs as Monitor records with logical geometry."""
    outs = outputs()
    wss = workspaces()
    by_output: dict[str, list[dict]] = {}
    for ws in wss:
        by_output.setdefault(str(ws.get("output") or ""), []).append(ws)

    monitors: list[Monitor] = []
    for idx, (name, out) in enumerate(outs.items()):
        if not isinstance(out, dict):
            continue
        mine = by_output.get(name, [])
        active = next((w for w in mine if w.get("is_active")), None)
        focused = next((w for w in mine if w.get("is_focused")), None)
        active_window_id = None
        if active is not None and active.get("active_window_id") is not None:
            active_window_id = int(active["active_window_id"])
        monitors.append(
            Monitor(
                id=idx,
                output=name,
                active_workspace_id=int((active or {}).get("id") or 0),
                active_window_id=active_window_id,
                is_focused=focused is not None,
                geometry=_rect_from_logical(out.get("logical")),
            )
        )
    return monitors


def focused_output_name() -> Optional[str]:
    data = _run_json("focused-output")
    if isinstance(data, dict):
        return data.get("name") or None
    return None


def focus_window(window_id: int) -> bool:
    """Focus a window by niri window id. True if the compositor accepted it."""
    try:
        proc = _run("action", "focus-window", "--id", str(int(window_id)))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def focus_window_on_workspace(window_id: int) -> bool:
    """Switch to the window's workspace, then focus the window.

    niri's ``focus-window`` does not cross workspaces, so the workspace is
    focused first. Note ``focus-workspace`` takes the workspace *index*
    (``idx``), not the workspace id, so the id is resolved via
    :func:`_workspace_index`.
    """
    try:
        wid = int(window_id)
    except (TypeError, ValueError):
        return False
    ws_id = workspace_for_window(wid)
    if ws_id is None:
        return False
    idx = _workspace_index(ws_id)
    if idx is None:
        return False
    try:
        proc = _run("action", "focus-workspace", str(idx))
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return focus_window(wid)


def build_context(with_a11y: bool = False) -> Context:
    """Cheap always-on snapshot. Set with_a11y for the T1 accessibility tree."""
    from utter.context.clipboard import get_clipboard

    focused = focused_window()
    ctx = Context(
        focused=focused,
        monitors=list_monitors(),
        windows=list_windows(),
        clipboard=get_clipboard(),
    )
    if with_a11y:
        try:
            from utter.context import atspi

            app_id = focused.app_id if focused else None
            ctx.a11y = atspi.dump_tree(app_id)
        except Exception:  # noqa: BLE001 - a11y must never break context
            ctx.a11y = None
    return ctx


__all__ = [
    "focused_window",
    "list_monitors",
    "list_windows",
    "find_windows",
    "workspace_for_window",
    "focus_window",
    "focus_window_on_workspace",
    "build_context",
    "outputs",
    "windows",
    "workspaces",
    "focused_output_name",
]
