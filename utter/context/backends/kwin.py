"""KWin backend for KDE Plasma (Plasma 6 Wayland first; Plasma 5 and X11 best-effort).

Everything goes over the session D-Bus with argv lists (never ``shell=True``):

    org.kde.KWin            /KWin                     org.kde.KWin
        currentDesktop() setCurrentDesktop(i) nextDesktop() previousDesktop()
    org.kde.KWin            /VirtualDesktopManager    org.kde.KWin.VirtualDesktopManager
        properties count / current / desktops (a(uss) position,id,name)
    org.kde.KWin            /Scripting                org.kde.kwin.Scripting
        loadScript(path, pluginName) -> id ; unloadScript(pluginName)
    org.kde.KWin            /Scripting/Script<id>     org.kde.kwin.Script   run()   (Plasma 6)
                            /<id>                                                   (Plasma 5)
    org.kde.kglobalaccel    /component/kwin           org.kde.kglobalaccel.Component
        invokeShortcut(name)   -- "Window Close", "Switch to Desktop 3", ...
    org.kde.klipper         /klipper                  org.kde.klipper.klipper
        getClipboardContents()                        (used by utter.context.clipboard)
    org.freedesktop.portal.Desktop  /org/freedesktop/portal/desktop  org.freedesktop.portal.Screenshot
        Screenshot(parent, {interactive: false, handle_token})   (screenshot fallback)

Window queries and per-window actions use, in order of preference:
    1. ``kdotool`` (when installed) — ``search``, ``getactivewindow``, ``windowactivate``, ...
    2. a tiny KWin script loaded through ``org.kde.kwin.Scripting``; query results come
       back through ``callDBus`` to a bus name owned by :class:`dbus.LiteBus`.
Actions on *the focused window* (close/minimize/maximize/fullscreen, workspace moves)
go through ``kglobalaccel`` shortcuts, which exist on Plasma 5 and 6 alike.

Screenshots: ``spectacle -b -n -o <png>`` first, the XDG screenshot portal second,
``grim`` last (it is unreliable on KWin). Which path is used is recorded in
``last_screenshot_method``.

KWin identifies windows by UUID; the rest of utter uses ``int`` ids, so UUIDs are
mapped to stable per-process ints (``window_uuid`` / ``window_int``).

Where KWin has no counterpart for a niri action the backend returns
``Outcome(unsupported=True)`` so the router can fall back to the next tier.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from utter import platform
from utter.context.backends import dbus
from utter.context.compositor import (
    CAPABILITIES,
    CAP_ACTIVATE,
    CAP_CLOSE,
    CAP_COMPOSITOR_ACTION,
    CAP_FOCUSED_WINDOW,
    CAP_LIST_WINDOWS,
    CAP_MAXIMIZE,
    CAP_MINIMIZE,
    CAP_MOVE_TO_WORKSPACE,
    CAP_SCREENSHOT,
    CAP_SWITCH_WORKSPACE,
    CompositorUnsupported,
    Outcome,
)
from utter.types import Context, FocusedWindow, Monitor, Rect, WindowInfo

NAME = "kwin"
_TIMEOUT = 4.0

KWIN = "org.kde.KWin"
KWIN_PATH = "/KWin"
KWIN_IFACE = "org.kde.KWin"
VDM_PATH = "/VirtualDesktopManager"
VDM_IFACE = "org.kde.KWin.VirtualDesktopManager"
SCRIPTING_PATH = "/Scripting"
SCRIPTING_IFACE = "org.kde.kwin.Scripting"
SCRIPT_IFACE = "org.kde.kwin.Script"
KGA = "org.kde.kglobalaccel"
KGA_IFACE = "org.kde.kglobalaccel.Component"
KGA_KWIN = "/component/kwin"
KGA_SPECTACLE = "/component/org_kde_spectacle_desktop"
KGA_POWERDEVIL = "/component/org_kde_powerdevil"
KLIPPER = "org.kde.klipper"
KLIPPER_PATH = "/klipper"
KLIPPER_IFACE = "org.kde.klipper.klipper"
PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_SHOT_IFACE = "org.freedesktop.portal.Screenshot"

RESULT_IFACE = "org.utter.kwin"
RESULT_MEMBER = "result"

last_screenshot_method: Optional[str] = None


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
class _Defaults:
    screenshot = "auto"        # auto | spectacle | portal | grim
    clipboard = "auto"         # auto | klipper | wl-clipboard
    use_kdotool = True
    use_scripts = True
    script_timeout_s = 3.0
    pointer_abs_factor = 1.0


_CFG: Any = None


def reset_cache() -> None:
    global _CFG, _WINDOW_SOURCE
    _CFG = None
    _WINDOW_SOURCE = None


def cfg() -> Any:
    global _CFG
    if _CFG is None:
        try:
            from utter.config import load_config

            _CFG = getattr(load_config(), "kwin", None) or _Defaults()
        except Exception:  # noqa: BLE001
            _CFG = _Defaults()
    return _CFG


def _opt(name: str) -> Any:
    return getattr(cfg(), name, getattr(_Defaults, name))


# --------------------------------------------------------------------------- #
# D-Bus call table (pure; unit-tested)
# --------------------------------------------------------------------------- #
def call_current_desktop() -> dbus.Call:
    return dbus.Call(KWIN, KWIN_PATH, KWIN_IFACE, "currentDesktop")


def call_set_current_desktop(n: int) -> dbus.Call:
    return dbus.Call(KWIN, KWIN_PATH, KWIN_IFACE, "setCurrentDesktop", (int(n),))


def call_next_desktop() -> dbus.Call:
    return dbus.Call(KWIN, KWIN_PATH, KWIN_IFACE, "nextDesktop")


def call_previous_desktop() -> dbus.Call:
    return dbus.Call(KWIN, KWIN_PATH, KWIN_IFACE, "previousDesktop")


def call_vdm_prop(name: str) -> dbus.Call:
    return dbus.prop_get(KWIN, VDM_PATH, VDM_IFACE, name)


def call_shortcut(name: str, component: str = KGA_KWIN) -> dbus.Call:
    return dbus.Call(KGA, component, KGA_IFACE, "invokeShortcut", (name,))


def call_load_script(path: str, plugin_name: str) -> dbus.Call:
    return dbus.Call(KWIN, SCRIPTING_PATH, SCRIPTING_IFACE, "loadScript", (path, plugin_name))


def call_run_script(script_id: int, plasma6: bool = True) -> dbus.Call:
    path = f"{SCRIPTING_PATH}/Script{int(script_id)}" if plasma6 else f"/{int(script_id)}"
    return dbus.Call(KWIN, path, SCRIPT_IFACE, "run")


def call_unload_script(plugin_name: str) -> dbus.Call:
    return dbus.Call(KWIN, SCRIPTING_PATH, SCRIPTING_IFACE, "unloadScript", (plugin_name,))


def call_klipper_get() -> dbus.Call:
    return dbus.Call(KLIPPER, KLIPPER_PATH, KLIPPER_IFACE, "getClipboardContents")


def call_klipper_set(text: str) -> dbus.Call:
    return dbus.Call(KLIPPER, KLIPPER_PATH, KLIPPER_IFACE, "setClipboardContents", (text,))


def call_portal_screenshot(token: str) -> dbus.Call:
    options = {"interactive": dbus.Variant(False), "handle_token": dbus.Variant(token)}
    return dbus.Call(PORTAL, PORTAL_PATH, PORTAL_SHOT_IFACE, "Screenshot", ("", options))


# niri action name -> KWin equivalent.
#   ("shortcut", <kglobalaccel name>)             component kwin
#   ("shortcut", <name>, <component path>)        other component
#   ("desktop", <kind>)                           virtual desktop call needing the int arg
#   ("fn", <callable name>)                       handled by a backend function
#   None                                          deliberately unsupported
ACTION_MAP: dict[str, Optional[tuple]] = {
    "close-window": ("shortcut", "Window Close"),
    "fullscreen-window": ("shortcut", "Window Fullscreen"),
    "toggle-windowed-fullscreen": ("shortcut", "Window Fullscreen"),
    "maximize-column": ("shortcut", "Window Maximize"),
    "maximize-window-to-edges": ("shortcut", "Window Maximize"),
    "expand-column-to-available-width": ("shortcut", "Window Maximize Horizontal"),
    "minimize-window": ("shortcut", "Window Minimize"),
    "toggle-window-minimized": ("shortcut", "Window Minimize"),
    "unminimize-window": None,
    "center-column": ("shortcut", "Move Window to the Center"),
    "center-window": ("shortcut", "Move Window to the Center"),
    "focus-column-left": ("shortcut", "Switch Window Left"),
    "focus-column-right": ("shortcut", "Switch Window Right"),
    "focus-window-up": ("shortcut", "Switch Window Up"),
    "focus-window-down": ("shortcut", "Switch Window Down"),
    "focus-column-or-monitor-left": ("shortcut", "Switch Window Left"),
    "focus-column-or-monitor-right": ("shortcut", "Switch Window Right"),
    "focus-window-or-monitor-up": ("shortcut", "Switch Window Up"),
    "focus-window-or-monitor-down": ("shortcut", "Switch Window Down"),
    "focus-window-previous": ("shortcut", "Walk Through Windows"),
    "next-window": ("shortcut", "Walk Through Windows"),
    "move-column-left": ("shortcut", "Window Quick Tile Left"),
    "move-column-right": ("shortcut", "Window Quick Tile Right"),
    "move-window-up": ("shortcut", "Window Quick Tile Top"),
    "move-window-down": ("shortcut", "Window Quick Tile Bottom"),
    "focus-workspace-down": ("shortcut", "Switch to Next Desktop"),
    "focus-workspace-up": ("shortcut", "Switch to Previous Desktop"),
    "focus-workspace": ("desktop", "switch"),
    "focus-workspace-previous": None,
    "move-window-to-workspace": ("desktop", "move_window"),
    "move-column-to-workspace": ("desktop", "move_window"),
    "move-window-to-workspace-down": ("shortcut", "Window to Next Desktop"),
    "move-window-to-workspace-up": ("shortcut", "Window to Previous Desktop"),
    "move-column-to-workspace-down": ("shortcut", "Window to Next Desktop"),
    "move-column-to-workspace-up": ("shortcut", "Window to Previous Desktop"),
    "focus-monitor-left": ("shortcut", "Switch to Screen to the Left"),
    "focus-monitor-right": ("shortcut", "Switch to Screen to the Right"),
    "focus-monitor-up": ("shortcut", "Switch to Screen Above"),
    "focus-monitor-down": ("shortcut", "Switch to Screen Below"),
    "focus-monitor-next": ("shortcut", "Switch to Next Screen"),
    "focus-monitor-previous": ("shortcut", "Switch to Previous Screen"),
    "move-window-to-monitor-left": ("shortcut", "Window One Screen to the Left"),
    "move-window-to-monitor-right": ("shortcut", "Window One Screen to the Right"),
    "move-window-to-monitor-up": ("shortcut", "Window One Screen Up"),
    "move-window-to-monitor-down": ("shortcut", "Window One Screen Down"),
    "move-window-to-monitor-next": ("shortcut", "Window to Next Screen"),
    "move-window-to-monitor-previous": ("shortcut", "Window to Previous Screen"),
    "move-column-to-monitor-left": ("shortcut", "Window One Screen to the Left"),
    "move-column-to-monitor-right": ("shortcut", "Window One Screen to the Right"),
    "move-column-to-monitor-up": ("shortcut", "Window One Screen Up"),
    "move-column-to-monitor-down": ("shortcut", "Window One Screen Down"),
    "move-column-to-monitor-next": ("shortcut", "Window to Next Screen"),
    "move-column-to-monitor-previous": ("shortcut", "Window to Previous Screen"),
    "toggle-overview": ("shortcut", "Overview"),
    "open-overview": ("shortcut", "Overview"),
    "close-overview": None,
    "screenshot-screen": ("shortcut", "FullScreenScreenShot", KGA_SPECTACLE),
    "screenshot-window": ("shortcut", "ActiveWindowScreenShot", KGA_SPECTACLE),
    "screenshot": ("shortcut", "RectangularRegionScreenShot", KGA_SPECTACLE),
    "power-off-monitors": ("shortcut", "Turn Off Screen", KGA_POWERDEVIL),
    "power-on-monitors": None,
    "toggle-window-floating": None,
    "move-window-to-floating": None,
    "move-window-to-tiling": None,
    "toggle-column-tabbed-display": None,
    "consume-window-into-column": None,
    "expel-window-from-column": None,
    "quit": None,  # never log a user out from a voice command
    "spawn": None,  # launching is handled by the executor's launch action
}


def shortcut_for(command: str, args=()) -> Optional[dbus.Call]:
    """The single D-Bus call for a niri-style action, or None when unsupported."""
    spec = ACTION_MAP.get(command)
    if spec is None:
        return None
    kind = spec[0]
    if kind == "shortcut":
        component = spec[2] if len(spec) > 2 else KGA_KWIN
        return call_shortcut(spec[1], component)
    if kind == "desktop":
        n = _first_int(args)
        if n is None:
            return None
        if spec[1] == "switch":
            return call_set_current_desktop(n)
        return call_shortcut(f"Window to Desktop {n}")
    return None


def _first_int(args) -> Optional[int]:
    for a in args or ():
        try:
            return int(a)
        except (TypeError, ValueError):
            continue
    return None


# --------------------------------------------------------------------------- #
# tools / capabilities
# --------------------------------------------------------------------------- #
def dbus_tool() -> Optional[str]:
    return dbus.pick_tool()


def tools() -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {name: platform.which(name) for name in (
        "gdbus", "qdbus6", "qdbus", "dbus-send", "kdotool", "spectacle", "kscreen-doctor",
        "ydotool", "wl-paste", "grim")}
    out["dbus_tool"] = dbus_tool()
    out["window_source"] = window_source()
    out["session_bus"] = dbus.session_bus_address()
    out["screenshot_method"] = screenshot_method()
    return out


def available() -> bool:
    return dbus_tool() is not None


_WINDOW_SOURCE: Optional[str] = None


def window_source() -> Optional[str]:
    """``"kdotool"`` | ``"script"`` | None — how windows are listed/addressed."""
    global _WINDOW_SOURCE
    if _WINDOW_SOURCE is not None:
        return _WINDOW_SOURCE or None
    src = ""
    if _opt("use_kdotool") and platform.which("kdotool"):
        src = "kdotool"
    elif _opt("use_scripts") and dbus_tool() and dbus.session_bus_address():
        src = "script"
    _WINDOW_SOURCE = src
    return src or None


def screenshot_method() -> Optional[str]:
    want = str(_opt("screenshot") or "auto").lower()
    if want == "spectacle":
        return "spectacle" if platform.which("spectacle") else None
    if want == "portal":
        return "portal" if platform.which("gdbus") else None
    if want == "grim":
        return "grim" if platform.which("grim") else None
    if platform.which("spectacle"):
        return "spectacle"
    if platform.which("gdbus"):
        return "portal"
    if platform.which("grim"):
        return "grim"
    return None


def capabilities() -> dict[str, bool]:
    tool = dbus_tool() is not None
    windows = window_source() is not None
    return {
        CAP_FOCUSED_WINDOW: windows,
        CAP_LIST_WINDOWS: windows,
        CAP_ACTIVATE: windows,
        CAP_CLOSE: tool,
        CAP_MINIMIZE: tool,
        CAP_MAXIMIZE: tool,
        CAP_MOVE_TO_WORKSPACE: tool,
        CAP_SWITCH_WORKSPACE: tool,
        CAP_SCREENSHOT: screenshot_method() is not None,
        CAP_COMPOSITOR_ACTION: tool,
    }


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


def _dbus(c: dbus.Call) -> dbus.Reply:
    return dbus.call(c, timeout=_TIMEOUT)


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
    timeout = float(_opt("script_timeout_s") or 3.0)
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
    src = window_source()
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
    src = window_source()
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
    if dbus_tool() is None and window_source() is None:
        return Outcome.unsupported_for(NAME, capability, "no D-Bus CLI tool and no kdotool")
    if window_id is None:
        if dbus_tool() is None:
            return Outcome.unsupported_for(NAME, capability, "no D-Bus CLI tool for kglobalaccel")
        return _outcome_from_reply(_dbus(call_shortcut(shortcut)), f"kglobalaccel {shortcut}", capability)
    uuid = window_uuid(window_id)
    if uuid is None:
        return Outcome(False, f"unknown window id {window_id}", [], backend=NAME, capability=capability)
    src = window_source()
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
    if dbus_tool() is None:
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
    if dbus_tool() is None:
        return Outcome.unsupported_for(NAME, CAP_SWITCH_WORKSPACE, "no D-Bus CLI tool")
    n = _int_or(workspace, 0)
    if n <= 0:
        return Outcome(False, f"bad desktop number {workspace!r}", [], backend=NAME, capability=CAP_SWITCH_WORKSPACE)
    return _outcome_from_reply(_dbus(call_set_current_desktop(n)), f"KWin setCurrentDesktop {n}", CAP_SWITCH_WORKSPACE)


def run_action(command: str, args=()) -> Outcome:
    """Run a niri-style action name on KWin via the mapping table."""
    if dbus_tool() is None:
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
    tool = dbus_tool() or "gdbus"
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
    global last_screenshot_method
    target = _shot_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    method = screenshot_method()
    errors: list[str] = []
    order = [method] if str(_opt("screenshot") or "auto").lower() != "auto" and method else \
        [m for m in ("spectacle", "portal", "grim") if m == method or platform.which({"portal": "gdbus"}.get(m, m))]
    for m in order:
        if m == "spectacle":
            ok, _, err = _run(spectacle_argv(str(target)), timeout=20.0)
            if ok and target.exists():
                last_screenshot_method = "spectacle"
                return str(target), _rect_for(target)
            errors.append(f"spectacle: {err or 'no file written'}")
        elif m == "portal":
            got = _portal_screenshot(target)
            if got:
                last_screenshot_method = "portal"
                return got, _rect_for(target)
            errors.append("portal: no response or denied")
        elif m == "grim":
            argv = ["grim"] + (["-o", output] if output else []) + [str(target)]
            ok, _, err = _run(argv, timeout=10.0)
            if ok and target.exists():
                last_screenshot_method = "grim"
                return str(target), _rect_for(target)
            errors.append(f"grim: {err}")
    last_screenshot_method = None
    raise CompositorUnsupported(NAME, CAP_SCREENSHOT, "; ".join(errors) or "no screenshot tool")


# --------------------------------------------------------------------------- #
# dry-run plan
# --------------------------------------------------------------------------- #
def plan() -> dict:
    tool = dbus_tool() or "gdbus"
    src = window_source()
    p: dict[str, Any] = {
        "dbus_tool": tool,
        "window_source": src or "none (install kdotool, or a D-Bus CLI + session bus for KWin scripts)",
        "switch_workspace": [call_set_current_desktop(2).argv(tool)],
        "desktops": [call_vdm_prop("desktops").argv(tool), call_vdm_prop("current").argv(tool)],
        "close (focused)": [call_shortcut("Window Close").argv(tool)],
        "minimize (focused)": [call_shortcut("Window Minimize").argv(tool)],
        "maximize (focused)": [call_shortcut("Window Maximize").argv(tool)],
        "move_to_workspace (focused)": [call_shortcut("Window to Desktop 2").argv(tool)],
        "compositor_action focus-column-left": [call_shortcut("Switch Window Left").argv(tool)],
        "compositor_action fullscreen-window": [call_shortcut("Window Fullscreen").argv(tool)],
        "compositor_action screenshot-screen": [call_shortcut("FullScreenScreenShot", KGA_SPECTACLE).argv(tool)],
        "clipboard": [call_klipper_get().argv(tool), ["wl-paste", "--no-newline", "--type", "text"]],
        "screenshot": [spectacle_argv("<png>"), call_portal_screenshot("<token>").argv("gdbus"), ["grim", "<png>"]],
    }
    if src == "kdotool" or src is None:
        p["list_windows (kdotool)"] = [kdotool_argv("search", ""), kdotool_argv("getactivewindow"),
                                       kdotool_argv("getwindowname", "<uuid>"),
                                       kdotool_argv("getwindowclassname", "<uuid>"),
                                       kdotool_argv("getwindowpid", "<uuid>")]
        p["activate (kdotool)"] = [kdotool_argv("windowactivate", "<uuid>")]
        p["close (kdotool)"] = [kdotool_argv("windowclose", "<uuid>")]
        p["move_to_workspace (kdotool)"] = [kdotool_argv("set_desktop_for_window", "<uuid>", "<n>")]
    if src == "script" or src is None:
        p["list_windows (kwin script)"] = [call_load_script("<runtime>/utter/utter-kwin-<pid>-<n>.js", "utter-kwin-<pid>-<n>").argv(tool),
                                           call_run_script(0, True).argv(tool), call_run_script(0, False).argv(tool),
                                           call_unload_script("utter-kwin-<pid>-<n>").argv(tool),
                                           ["<KWin script> callDBus(org.utter.kwin.p<pid>, /, org.utter.kwin, result, <json>)"]]
        p["activate (kwin script)"] = ["<same load/run/unload with> workspace.activeWindow = w"]
    return p


__all__ = [
    "NAME", "available", "tools", "capabilities", "focused_window", "list_windows", "find_windows", "list_monitors",
    "focus_window", "focus_window_on_workspace", "build_context", "close_window", "minimize_window",
    "maximize_window", "move_window_to_workspace", "switch_workspace", "screenshot", "run_action", "plan_action",
    "plan", "ACTION_MAP", "shortcut_for", "call_shortcut", "call_set_current_desktop", "call_current_desktop",
    "call_vdm_prop", "call_load_script", "call_run_script", "call_unload_script", "call_klipper_get",
    "call_klipper_set", "call_portal_screenshot", "query_script", "action_script", "parse_windows_json",
    "window_int", "window_uuid", "window_source", "screenshot_method", "spectacle_argv", "kdotool_argv",
    "kscreen_outputs", "total_geometry", "desktops", "current_desktop", "reset_cache", "last_screenshot_method",
]
