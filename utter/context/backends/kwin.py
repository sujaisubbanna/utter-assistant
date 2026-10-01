"""KWin backend for KDE Plasma (Plasma 6 Wayland first; Plasma 5 and X11 best-effort).

This module is the facade over three facets, all re-exported here so the rest
of the assistant keeps importing :mod:`utter.context.backends.kwin`:

* :mod:`utter.context.backends.kwin_dbus` — the D-Bus call table,
  ``ACTION_MAP`` and ``shortcut_for``.
* :mod:`utter.context.backends.kwin_windows` — the ``kdotool`` + KWin-script
  window paths, window-id mapping and the provider surface.
* :mod:`utter.context.backends.kwin_actions` — per-window actions, compositor
  actions and screenshots.

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

from typing import Any, Optional

from utter import platform
from utter.context.backends import dbus
from utter.context.backends.kwin_actions import *
from utter.context.backends.kwin_dbus import *
from utter.context.backends.kwin_windows import *
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
)

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
