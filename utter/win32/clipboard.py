"""Clipboard on Windows: ``win32clipboard`` (pywin32) with a ctypes fallback.

Same surface as :mod:`utter.context.clipboard` / :mod:`utter.macos.clipboard`:
``get_clipboard() -> str`` and ``set_clipboard(text) -> bool``. Never raises.
On a non-Windows host both return ``""``/``False`` without touching any DLL.

``win32clipboard`` is imported lazily; when pywin32 is absent a raw
user32/kernel32 ctypes path is used instead. Only text (``CF_UNICODETEXT``) is
read or written; a non-text clipboard yields ``""``.
"""
from __future__ import annotations

import ctypes
import logging

from utter import platform

logger = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


def _pywin32():
    """The ``win32clipboard`` module, or None (lazy; Windows only)."""
    if not platform.is_windows():
        return None
    try:
        import win32clipboard  # type: ignore[import-not-found]

        return win32clipboard
    except Exception:  # noqa: BLE001 - optional dependency
        return None


def _get_pywin32() -> str | None:
    clip = _pywin32()
    if clip is None:
        return None
    try:
        clip.OpenClipboard()
        try:
            if not clip.IsClipboardFormatAvailable(clip.CF_UNICODETEXT):
                return ""
            return str(clip.GetClipboardData(clip.CF_UNICODETEXT) or "")
        finally:
            clip.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        logger.debug("win32clipboard get failed: %s", exc)
        return None


def _dlls():
    from utter.win32.desktop import _dlls as _desktop_dlls

    return _desktop_dlls()


def _get_ctypes() -> str | None:
    from ctypes import wintypes

    try:
        user32, kernel32 = _dlls()
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        if not user32.OpenClipboard(None):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return ""
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.c_wchar_p(ptr).value or ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        logger.debug("ctypes clipboard get failed: %s", exc)
        return None


def get_clipboard() -> str:
    """Current clipboard text, or "" if none/unreadable. Never raises."""
    if not platform.is_windows():
        return ""
    for getter in (_get_pywin32, _get_ctypes):
        value = getter()
        if value is not None:
            return value
    return ""


def _set_pywin32(text: str) -> bool | None:
    clip = _pywin32()
    if clip is None:
        return None
    try:
        clip.OpenClipboard()
        try:
            clip.EmptyClipboard()
            clip.SetClipboardText(text or "", clip.CF_UNICODETEXT)
            return True
        finally:
            clip.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        logger.debug("win32clipboard set failed: %s", exc)
        return None


def _set_ctypes(text: str) -> bool | None:
    from ctypes import wintypes

    handle = None
    try:
        user32, kernel32 = _dlls()
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        buf = ctypes.create_unicode_buffer(text or "")
        size = ctypes.sizeof(buf)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, buf, size)
        kernel32.GlobalUnlock(handle)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                return False
            handle = None  # clipboard now owns the memory
            return True
        finally:
            user32.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        logger.debug("ctypes clipboard set failed: %s", exc)
        if handle:
            try:
                _dlls()[1].GlobalFree(handle)
            except Exception:  # noqa: BLE001
                pass
        return False


def set_clipboard(text: str) -> bool:
    """Copy ``text`` to the clipboard. Never raises."""
    if not platform.is_windows():
        return False
    for setter in (_set_pywin32, _set_ctypes):
        result = setter(text)
        if result is not None:
            return bool(result)
    return False


__all__ = ["get_clipboard", "set_clipboard"]
