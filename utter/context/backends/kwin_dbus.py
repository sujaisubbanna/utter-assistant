"""KWin D-Bus call table (pure; unit-tested).

Part of the KWin backend, split out of :mod:`utter.context.backends.kwin`:
the destination/path/interface constants, the :func:`call_*` builders, the
niri-action → KWin mapping (:data:`ACTION_MAP`) and :func:`shortcut_for`.
Everything here is pure: it builds :class:`~utter.context.backends.dbus.Call`
records and never runs a command. The facade in ``kwin.py`` re-exports this
whole surface.

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
"""
from __future__ import annotations

from typing import Any, Optional

from utter.context.backends import dbus

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


def _dbus(c: dbus.Call) -> dbus.Reply:
    return dbus.call(c, timeout=_TIMEOUT)


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


__all__ = [
    "NAME", "_TIMEOUT", "KWIN", "KWIN_PATH", "KWIN_IFACE", "VDM_PATH", "VDM_IFACE", "SCRIPTING_PATH",
    "SCRIPTING_IFACE", "SCRIPT_IFACE", "KGA", "KGA_IFACE", "KGA_KWIN", "KGA_SPECTACLE", "KGA_POWERDEVIL",
    "KLIPPER", "KLIPPER_PATH", "KLIPPER_IFACE", "PORTAL", "PORTAL_PATH", "PORTAL_SHOT_IFACE", "RESULT_IFACE",
    "RESULT_MEMBER", "call_current_desktop", "call_set_current_desktop", "call_next_desktop",
    "call_previous_desktop", "call_vdm_prop", "call_shortcut", "call_load_script", "call_run_script",
    "call_unload_script", "call_klipper_get", "call_klipper_set", "call_portal_screenshot", "ACTION_MAP",
    "shortcut_for",
]
