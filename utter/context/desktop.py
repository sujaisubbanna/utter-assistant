"""Platform-neutral desktop context provider.

Re-exports the provider for the host platform so the daemon, executor and the
``utter_py`` plugin never import a compositor module directly:

    Linux  -> :mod:`utter.context.niri`   (``niri msg --json``; unchanged)
    macOS  -> :mod:`utter.macos.desktop`  (NSWorkspace + Accessibility + CGWindowList)

The functions below share one signature on both platforms:
``focused_window``, ``list_windows``, ``find_windows``, ``list_monitors``,
``focus_window``, ``focus_window_on_workspace``, ``build_context``.
"""
from __future__ import annotations

from utter import platform


def provider():
    """The platform's context module (resolved on every call so tests can flip it)."""
    if platform.is_macos():
        from utter.macos import desktop as _mac

        return _mac
    from utter.context import niri as _niri

    return _niri


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


__all__ = ["provider", "focused_window", "list_windows", "find_windows", "list_monitors",
           "focus_window", "focus_window_on_workspace", "build_context", "windows_as_dicts"]
