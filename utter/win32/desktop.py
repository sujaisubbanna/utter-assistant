"""Desktop context on Windows via ctypes Win32 (stdlib only).

Exposes the same surface as :mod:`utter.context.niri` and
:mod:`utter.macos.desktop` so :mod:`utter.context.desktop` can swap providers
without callers changing::

    focused_window()  list_windows()  find_windows()  list_monitors()
    focus_window(id)  focus_window_on_workspace(id)  build_context(with_a11y)

Sources:
    * ``GetForegroundWindow`` -> the focused top-level window;
    * ``EnumWindows`` + ``IsWindowVisible`` -> the visible top-level windows;
    * ``GetWindowTextW`` -> window title;
    * ``GetWindowThreadProcessId`` + ``QueryFullProcessImageNameW`` -> exe path,
      from which :func:`app_id_from_exe` derives the ``app_id`` (exe stem,
      lower-cased, e.g. ``chrome.exe`` -> ``"chrome"``);
    * ``EnumDisplayMonitors`` + ``GetMonitorInfoW`` -> monitor rectangles.

Window ids are ``HWND`` values (``window_id``). Everything is best-effort and
never raises into the daemon: a failure yields ``None``/``[]``/``False``. On a
non-Windows host the public providers return empty and the low-level
:func:`require_windows` / ``_dlls`` raise :class:`WindowsUnavailable`.
"""
from __future__ import annotations

import ctypes
import logging
from typing import Optional

from utter import platform
from utter.types import Context, FocusedWindow, Monitor, Rect, WindowInfo
from utter.win32.dpi import ensure_dpi_aware as _ensure_dpi_aware

logger = logging.getLogger(__name__)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_RESTORE = 9
MONITORINFOF_PRIMARY = 1

_USER32 = None
_KERNEL32 = None


class WindowsUnavailable(RuntimeError):
    """Raised when a raw Win32 entry point is used on a non-Windows host."""


def require_windows() -> None:
    """Raise :class:`WindowsUnavailable` unless the host is Windows."""
    if not platform.is_windows():
        raise WindowsUnavailable("the Win32 desktop backend is only available on Windows")


def app_id_from_exe(exe: str) -> str:
    """Derive a stable ``app_id`` from a full executable path (pure; unit-tested).

    ``C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe`` -> ``"chrome"``.
    Handles both ``/`` and ``\\`` separators (so it is testable on Linux), strips
    a trailing ``.exe`` and lower-cases the result. Returns ``""`` for empty input.
    """
    raw = str(exe or "").strip().strip('"')
    if not raw:
        return ""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name.casefold()


def _dlls():
    """Return cached ``(user32, kernel32)`` DLLs with prototypes set (Windows only)."""
    global _USER32, _KERNEL32
    if _USER32 is not None and _KERNEL32 is not None:
        return _USER32, _KERNEL32
    require_windows()
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    _USER32, _KERNEL32 = user32, kernel32
    return _USER32, _KERNEL32


def _window_title(hwnd) -> str:
    user32, _ = _dlls()
    try:
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception as exc:  # noqa: BLE001 - a bad window must not abort a scan
        logger.debug("GetWindowTextW failed: %s", exc)
        return ""


def _window_pid(hwnd) -> int:
    user32, _ = _dlls()
    try:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("GetWindowThreadProcessId failed: %s", exc)
        return 0


def _exe_path(pid: int) -> str:
    """Full image path of ``pid`` ("" when it cannot be queried)."""
    if not pid:
        return ""
    _, kernel32 = _dlls()
    handle = None
    try:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        size = ctypes.c_ulong(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value or ""
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("QueryFullProcessImageNameW failed: %s", exc)
        return ""
    finally:
        if handle:
            try:
                kernel32.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass


def _raw_windows() -> list[dict]:
    """Visible top-level windows as ``{id,pid,app_id,title,is_focused}`` dicts."""
    from ctypes import wintypes

    _ensure_dpi_aware()
    user32, _ = _dlls()
    foreground = int(user32.GetForegroundWindow() or 0)
    rows: list[dict] = []

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    def _callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _window_title(hwnd)
            pid = _window_pid(hwnd)
            app_id = app_id_from_exe(_exe_path(pid))
            if not title and not app_id:
                return True
            rows.append({"id": int(hwnd), "pid": pid, "app_id": app_id,
                         "title": title, "is_focused": int(hwnd) == foreground})
        except Exception:  # noqa: BLE001 - skip a bad window, keep enumerating
            pass
        return True

    try:
        user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("EnumWindows failed: %s", exc)
        return []
    return rows


def _focused_window() -> Optional[FocusedWindow]:
    _ensure_dpi_aware()
    user32, _ = _dlls()
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    pid = _window_pid(hwnd)
    return FocusedWindow(
        app_id=app_id_from_exe(_exe_path(pid)),
        title=_window_title(hwnd),
        pid=pid,
        window_id=hwnd,
        workspace_id=0,
    )


def focused_window() -> Optional[FocusedWindow]:
    """Currently focused window, or None if there is none (never raises)."""
    if not platform.is_windows():
        return None
    try:
        return _focused_window()
    except Exception as exc:  # noqa: BLE001
        logger.debug("focused_window failed: %s", exc)
        return None


def list_windows() -> list[WindowInfo]:
    """Visible top-level windows as :class:`WindowInfo` (empty on failure)."""
    if not platform.is_windows():
        return []
    out: list[WindowInfo] = []
    try:
        for row in _raw_windows():
            out.append(WindowInfo(
                id=row["id"], app_id=row["app_id"], title=row["title"],
                workspace_id=0, pid=row["pid"], is_focused=row["is_focused"],
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_windows failed: %s", exc)
    return out


def find_windows(app_id: Optional[str] = None,
                 title_contains: Optional[str] = None) -> list[WindowInfo]:
    """Windows matching case-insensitive substring filters (same as Unix/macOS)."""
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


def _list_monitors() -> list[Monitor]:
    from ctypes import wintypes

    _ensure_dpi_aware()
    user32, _ = _dlls()

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )
    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC, ctypes.POINTER(wintypes.RECT), _MONITORENUMPROC, wintypes.LPARAM
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    collected: list = []

    def _callback(hmonitor, _hdc, _rect, _lparam):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        try:
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                collected.append(info)
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_callback), 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("EnumDisplayMonitors failed: %s", exc)
        return []

    monitors: list[Monitor] = []
    for idx, info in enumerate(collected):
        r = info.rcMonitor
        monitors.append(Monitor(
            id=idx,
            output=f"display-{idx}",
            is_focused=bool(int(info.dwFlags) & MONITORINFOF_PRIMARY),
            geometry=Rect(int(r.left), int(r.top),
                          int(r.right - r.left), int(r.bottom - r.top)),
        ))
    return monitors


def list_monitors() -> list[Monitor]:
    """Connected monitors (empty on failure)."""
    if not platform.is_windows():
        return []
    try:
        return _list_monitors()
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_monitors failed: %s", exc)
        return []


def focus_window(window_id) -> bool:
    """Bring the window with this HWND to the foreground. True when accepted."""
    if not platform.is_windows():
        return False
    try:
        hwnd = int(window_id)
    except (TypeError, ValueError):
        return False
    if not hwnd:
        return False
    try:
        user32, _ = _dlls()
        if not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception as exc:  # noqa: BLE001
        logger.debug("focus_window failed: %s", exc)
        return False


def focus_window_on_workspace(window_id) -> bool:
    # Windows virtual desktops have no stable public "focus window on desktop"
    # API; activating the window also switches to the desktop that holds it.
    return focus_window(window_id)


def build_context(with_a11y: bool = False) -> Context:
    """Cheap always-on snapshot; ``with_a11y`` adds a bounded UIA tree."""
    from utter.win32.clipboard import get_clipboard

    ctx = Context(
        focused=focused_window(),
        monitors=list_monitors(),
        windows=list_windows(),
        clipboard=get_clipboard(),
    )
    if with_a11y:
        try:
            from utter.win32 import axtree

            app_id = ctx.focused.app_id if ctx.focused else None
            ctx.a11y = axtree.dump_tree(app_id)
        except Exception:  # noqa: BLE001 - a11y must never break context
            ctx.a11y = None
    return ctx


__all__ = [
    "WindowsUnavailable",
    "require_windows",
    "app_id_from_exe",
    "focused_window",
    "list_windows",
    "find_windows",
    "list_monitors",
    "focus_window",
    "focus_window_on_workspace",
    "build_context",
]
