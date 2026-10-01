"""KWin window enumeration and addressing.

Part of the KWin backend, split out of :mod:`utter.context.backends.kwin`.
Window queries and per-window actions use, in order of preference:

1. ``kdotool`` (when installed) — ``search``, ``getactivewindow``,
   ``windowactivate``, ...
2. a tiny KWin script loaded through ``org.kde.kwin.Scripting``; query results
   come back through ``callDBus`` to a bus name owned by
   :class:`utter.context.backends.dbus.LiteBus`.

KWin identifies windows by UUID; the rest of utter uses ``int`` ids, so UUIDs
are mapped to stable per-process ints (:func:`window_int` /
:func:`window_uuid`). This module also owns the provider surface used by
``compositor.active()``: ``list_windows``, ``find_windows``,
``focused_window``, monitor enumeration, focus and ``build_context``.

Config and the cached window-source decision live in the ``kwin`` facade;
this module reaches back to them lazily so a single writer owns each piece of
state.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from utter import platform
from utter.context.backends import dbus
from utter.context.backends.kwin_dbus import (
    NAME,
    RESULT_IFACE,
    RESULT_MEMBER,
    _TIMEOUT,
    _dbus,
    call_current_desktop,
    call_load_script,
    call_run_script,
    call_unload_script,
    call_vdm_prop,
)
from utter.context.compositor import Outcome
from utter.types import Context, FocusedWindow, Monitor, Rect, WindowInfo


def _facade():
    """The ``kwin`` facade module (config + cached window source live there)."""
    from utter.context.backends import kwin

    return kwin


# --------------------------------------------------------------------------- #
# window ids: KWin UUID <-> utter int
# --------------------------------------------------------------------------- #
_UUID_TO_INT: dict[str, int] = {}
_INT_TO_UUID: dict[int, str] = {}


def window_int(uuid: str) -> int:
    u = str(uuid).strip()
    if u not in _UUID_TO_INT:
        n = len(_UUID_TO_INT) + 1
        _UUID_TO_INT[u] = n
        _INT_TO_UUID[n] = u
    return _UUID_TO_INT[u]


def window_uuid(window_id: int) -> Optional[str]:
    try:
        return _INT_TO_UUID.get(int(window_id))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# subprocess helper
# --------------------------------------------------------------------------- #
def _run(argv: list[str], timeout: float = _TIMEOUT) -> tuple[bool, str, str]:
    if dbus.dry_run():
        return True, "", "dry-run"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", str(exc)
    return proc.returncode == 0, proc.stdout, (proc.stderr or "").strip()


# --------------------------------------------------------------------------- #
# kdotool path
# --------------------------------------------------------------------------- #
def kdotool_argv(*args: str) -> list[str]:
    return ["kdotool", *args]


def _kdotool_lines(*args: str) -> list[str]:
    ok, out, _ = _run(kdotool_argv(*args))
    if not ok:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _kdotool_windows() -> list[WindowInfo]:
    ids = _kdotool_lines("search", "")
    active = _kdotool_lines("getactivewindow")
    active_id = active[0] if active else ""
    out: list[WindowInfo] = []
    for uuid in ids:
        title = " ".join(_kdotool_lines("getwindowname", uuid))
        klass = " ".join(_kdotool_lines("getwindowclassname", uuid))
        pid_s = _kdotool_lines("getwindowpid", uuid)
        desk_s = _kdotool_lines("get_desktop_for_window", uuid)
        out.append(WindowInfo(
            id=window_int(uuid), app_id=klass, title=title,
            workspace_id=_int_or(desk_s[0] if desk_s else 0),
            pid=_int_or(pid_s[0] if pid_s else 0),
            is_focused=(uuid == active_id),
        ))
    return out


def _int_or(v, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# KWin script path
# --------------------------------------------------------------------------- #
_SCRIPT_COUNTER = 0

_QUERY_JS = """(function () {
  var isNew = typeof workspace.windowList === "function";
  var list = isNew ? workspace.windowList() : workspace.clientList();
  var active = isNew ? workspace.activeWindow : workspace.activeClient;
  var out = [];
  for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (!w) continue;
    if (w.skipTaskbar && !w.active) continue;
    if (!(w.normalWindow || w.dialog)) continue;
    var desk = 0;
    if (isNew) {
      var ds = w.desktops || [];
      desk = ds.length ? Number(ds[0].x11DesktopNumber || 0) : 0;
    } else {
      desk = Number(w.desktop || 0);
    }
    out.push({
      id: String(w.internalId),
      app_id: String(w.resourceClass || w.resourceName || ""),
      title: String(w.caption || ""),
      pid: Number(w.pid || 0),
      workspace_id: desk,
      is_focused: (active === w),
      is_fullscreen: !!w.fullScreen,
      minimized: !!w.minimized
    });
  }
  callDBus(%(bus)s, "/", %(iface)s, %(member)s, JSON.stringify({windows: out}));
})();
"""

_ACTION_JS = """(function () {
  var isNew = typeof workspace.windowList === "function";
  var list = isNew ? workspace.windowList() : workspace.clientList();
  var target = %(target)s;
  for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (!w || String(w.internalId) !== target) continue;
    %(action)s
    break;
  }
})();
"""

_JS_ACTIONS = {
    "activate": "if (isNew) { workspace.activeWindow = w; } else { workspace.activeClient = w; }",
    "close": "w.closeWindow();",
    "minimize": "w.minimized = true;",
    "move_to_desktop": ("if (isNew) { var d = workspace.desktops[%(n)d - 1]; if (d) { w.desktops = [d]; } }"
                        " else { w.desktop = %(n)d; }"),
}


def query_script(bus_name: str) -> str:
    return _QUERY_JS % {"bus": json.dumps(bus_name), "iface": json.dumps(RESULT_IFACE),
                        "member": json.dumps(RESULT_MEMBER)}


def action_script(uuid: str, action: str, n: int = 0) -> str:
    body = _JS_ACTIONS[action]
    if "%(n)d" in body:
        body = body % {"n": int(n)}
    return _ACTION_JS % {"target": json.dumps(str(uuid)), "action": body}


def _script_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    d = Path(base) / "utter"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_script(source: str) -> tuple[Path, str]:
    global _SCRIPT_COUNTER
    _SCRIPT_COUNTER += 1
    name = f"utter-kwin-{os.getpid()}-{_SCRIPT_COUNTER}"
    path = _script_dir() / f"{name}.js"
    path.write_text(source, encoding="utf-8")
    return path, name


def _load_and_run(path: Path, plugin_name: str) -> tuple[bool, list[list[str]], str]:
    """loadScript -> run (Plasma 6 path, then Plasma 5 path) -> unloadScript."""
    ran: list[list[str]] = []
    r = _dbus(call_load_script(str(path), plugin_name))
    if r.argv:
        ran.append(r.argv)
    if not r.ok:
        return False, ran, f"loadScript failed: {r.error}"
    sid = _int_or(r.value, -1) if not dbus.dry_run() else 0
    if sid < 0:
        return False, ran, "loadScript returned -1 (script rejected or plugin name in use)"
    ok = False
    err = ""
    for plasma6 in (True, False):
        rr = _dbus(call_run_script(sid, plasma6))
        if rr.argv:
            ran.append(rr.argv)
        if rr.ok:
            ok = True
            break
        err = rr.error
    ru = _dbus(call_unload_script(plugin_name))
    if ru.argv:
        ran.append(ru.argv)
    return ok, ran, ("" if ok else f"run failed: {err}")


def _script_windows() -> list[WindowInfo]:
    timeout = float(_facade()._opt("script_timeout_s") or 3.0)
    try:
        bus = dbus.LiteBus(timeout=timeout).connect()
    except (OSError, TimeoutError):
        return []
    try:
        name = f"org.utter.kwin.p{os.getpid()}"
        if not bus.request_name(name):
            return []
        path, plugin = _write_script(query_script(name))
        try:
            ok, _, _ = _load_and_run(path, plugin)
            if not ok:
                return []
            args = bus.wait_for_call(RESULT_MEMBER, timeout=timeout)
        finally:
            try:
                path.unlink()
            except OSError:
                pass
    finally:
        bus.close()
    if not args:
        return []
    return parse_windows_json(str(args[0]))


def parse_windows_json(text: str) -> list[WindowInfo]:
    """Turn the script's JSON payload into WindowInfo records (bad entries skipped)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data.get("windows") if isinstance(data, dict) else data
    out: list[WindowInfo] = []
    for w in items or []:
        if not isinstance(w, dict) or not w.get("id"):
            continue
        try:
            out.append(WindowInfo(
                id=window_int(str(w["id"])),
                app_id=str(w.get("app_id") or ""),
                title=str(w.get("title") or ""),
                workspace_id=int(w.get("workspace_id") or 0),
                pid=int(w.get("pid") or 0),
                is_focused=bool(w.get("is_focused", False)),
                is_floating=False,
                is_fullscreen=bool(w.get("is_fullscreen", False)),
            ))
        except (TypeError, ValueError):
            continue
    return out


def _script_action(uuid: str, action: str, n: int = 0) -> Outcome:
    path, plugin = _write_script(action_script(uuid, action, n))
    try:
        ok, ran, err = _load_and_run(path, plugin)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return Outcome(ok, f"kwin script {action}" + ("" if ok else f" failed: {err}"), ran, backend=NAME, capability=action)


# --------------------------------------------------------------------------- #
# provider surface
# --------------------------------------------------------------------------- #
def list_windows() -> list[WindowInfo]:
    src = _facade().window_source()
    if src == "kdotool":
        return _kdotool_windows()
    if src == "script":
        return _script_windows()
    return []


def find_windows(app_id: Optional[str] = None, title_contains: Optional[str] = None) -> list[WindowInfo]:
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


def focused_window() -> Optional[FocusedWindow]:
    for w in list_windows():
        if w.is_focused:
            return FocusedWindow(app_id=w.app_id, title=w.title, pid=w.pid, window_id=w.id,
                                 workspace_id=w.workspace_id, is_fullscreen=w.is_fullscreen)
    return None


def current_desktop() -> Optional[int]:
    r = _dbus(call_current_desktop())
    if r.ok and r.value is not None:
        return _int_or(r.value, 0) or None
    return None


def desktops() -> list[dict]:
    """``[{"position", "id", "name"}, ...]`` from VirtualDesktopManager (gdbus only for the struct)."""
    r = _dbus(call_vdm_prop("desktops"))
    out: list[dict] = []
    if r.ok and isinstance(r.value, list):
        for item in r.value:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                out.append({"position": _int_or(item[0]), "id": str(item[1]), "name": str(item[2])})
    return out


def kscreen_outputs() -> list[dict]:
    """Outputs from ``kscreen-doctor -j`` (empty when unavailable)."""
    if not platform.which("kscreen-doctor"):
        return []
    ok, out, _ = _run(["kscreen-doctor", "-j"])
    if not ok or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [o for o in (data.get("outputs") or []) if isinstance(o, dict)]


def _logical_rect(output: dict) -> Optional[Rect]:
    try:
        pos = output.get("pos") or {}
        size = output.get("size") or {}
        scale = float(output.get("scale") or 1.0) or 1.0
        w = int(round(int(size.get("width", 0)) / scale))
        h = int(round(int(size.get("height", 0)) / scale))
        return Rect(int(pos.get("x", 0)), int(pos.get("y", 0)), w, h)
    except (TypeError, ValueError):
        return None


def list_monitors() -> list[Monitor]:
    monitors: list[Monitor] = []
    cur = current_desktop() or 0
    for idx, out in enumerate(o for o in kscreen_outputs() if o.get("enabled", True)):
        monitors.append(Monitor(id=idx, output=str(out.get("name") or idx), active_workspace_id=cur,
                                active_window_id=None, is_focused=bool(out.get("priority") == 1),
                                geometry=_logical_rect(out)))
    return monitors


def focus_window(window_id: int) -> bool:
    uuid = window_uuid(window_id)
    if uuid is None:
        return False
    src = _facade().window_source()
    if src == "kdotool":
        ok, _, _ = _run(kdotool_argv("windowactivate", uuid))
        return ok
    if src == "script":
        return _script_action(uuid, "activate").ok
    return False


def focus_window_on_workspace(window_id: int) -> bool:
    """KWin switches desktops when activating a window, so this is plain activation."""
    return focus_window(window_id)


def build_context(with_a11y: bool = False) -> Context:
    from utter.context.clipboard import get_clipboard

    windows = list_windows()
    focused = None
    for w in windows:
        if w.is_focused:
            focused = FocusedWindow(app_id=w.app_id, title=w.title, pid=w.pid, window_id=w.id,
                                    workspace_id=w.workspace_id, is_fullscreen=w.is_fullscreen)
            break
    ctx = Context(focused=focused, monitors=list_monitors(), windows=windows, clipboard=get_clipboard())
    if with_a11y:
        try:
            from utter.context import atspi

            ctx.a11y = atspi.dump_tree(focused.app_id if focused else None)
        except Exception:  # noqa: BLE001 - a11y must never break context
            ctx.a11y = None
    return ctx


__all__ = [
    "window_int", "window_uuid", "_run", "kdotool_argv", "_int_or", "query_script", "action_script",
    "parse_windows_json", "list_windows", "find_windows", "focused_window", "current_desktop", "desktops",
    "kscreen_outputs", "list_monitors", "focus_window", "focus_window_on_workspace", "build_context",
]
