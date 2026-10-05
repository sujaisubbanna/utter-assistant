"""Platform-neutral desktop context provider.

Re-exports the provider for the host platform so the daemon, executor and the
``utter_py`` plugin never import a compositor module directly:

    Linux / niri   -> :mod:`utter.context.niri`            (``niri msg --json``; unchanged)
    Linux / KWin   -> :mod:`utter.context.backends.kwin`   (KDE Plasma over D-Bus / kdotool)
    Linux / other  -> :mod:`utter.context.backends.fallback` (reports unsupported)
    macOS          -> :mod:`utter.macos.desktop`           (NSWorkspace + Accessibility + CGWindowList)
    Windows        -> :mod:`utter.win32.desktop`           (ctypes user32/kernel32)

Which Linux backend is used is decided by :mod:`utter.context.compositor`
(``[general] compositor = "auto" | "niri" | "kwin"``, or ``UTTER_COMPOSITOR``).

The functions below share one signature on every platform:
``focused_window``, ``list_windows``, ``find_windows``, ``list_monitors``,
``focus_window``, ``focus_window_on_workspace``, ``build_context``.
"""
from __future__ import annotations

from utter import platform


def provider():
    """The platform's context module (resolved on every call so tests can flip it).

    On niri this is still the :mod:`utter.context.niri` module itself, so the
    original behaviour (and its tests) are untouched.
    """
    if platform.is_windows():
        from utter.win32 import desktop as _win

        return _win
    if platform.is_macos():
        from utter.macos import desktop as _mac

        return _mac
    from utter.context import compositor

    name = compositor.active_name()
    if name == compositor.NIRI:
        from utter.context import niri as _niri

        return _niri
    return compositor.backend_for(name)


def backend():
    """The full compositor backend module (provider surface + window actions)."""
    if platform.is_windows():
        from utter.win32 import desktop as _win

        return _win
    if platform.is_macos():
        from utter.macos import desktop as _mac

        return _mac
    from utter.context import compositor

    return compositor.active()


def focused_window():
    return provider().focused_window()


def list_windows():
    return provider().list_windows()


def find_windows(app_id=None, title_contains=None):
    return provider().find_windows(app_id=app_id, title_contains=title_contains)


def list_monitors():
    return provider().list_monitors()


def focus_window(window_id):
    return provider().focus_window(window_id)


def focus_window_on_workspace(window_id):
    mod = provider()
    fn = getattr(mod, "focus_window_on_workspace", None) or mod.focus_window
    return fn(window_id)


def build_context(with_a11y: bool = False):
    return provider().build_context(with_a11y=with_a11y)


def windows_as_dicts() -> list:
    """``[{"id", "app_id", "title", "pid", "is_focused"}, ...]`` for either platform."""
    out = []
    for w in list_windows():
        out.append({"id": w.id, "app_id": w.app_id, "title": w.title, "pid": w.pid,
                    "workspace_id": w.workspace_id, "is_focused": w.is_focused})
    return out


__all__ = ["provider", "backend", "focused_window", "list_windows", "find_windows", "list_monitors",
           "focus_window", "focus_window_on_workspace", "build_context", "windows_as_dicts"]
