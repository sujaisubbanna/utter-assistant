"""Windows (Win32) backends for utter.

Every module here mirrors the shape of the Linux (``utter.context.*`` /
``utter.actions.launch``) and macOS (``utter.macos.*``) providers, and is picked
only when :func:`utter.platform.is_windows` is true (see
``utter/context/desktop.py`` and friends for the dispatch seams).

Nothing Windows-specific (``ctypes.WinDLL``, ``ctypes.WINFUNCTYPE``,
``win32clipboard``, ``uiautomation``, ``winreg``) is imported at module import
time. Each backend imports its native dependencies lazily inside a
``platform.is_windows()`` guard, so this package imports cleanly on Linux and
macOS and every provider degrades to ``None``/empty there. The low-level
loaders raise :class:`utter.win32.desktop.WindowsUnavailable` when a Win32 call
is attempted off Windows.

Modules:
    desktop      focused window + window list + monitors (ctypes user32/kernel32)
    axtree       bounded UI Automation tree walk for text-field detection
    clipboard    get/set text via ``win32clipboard`` (pywin32) with a ctypes fallback
    launch       open URL/app via ``os.startfile`` / ``ShellExecuteW`` + Start-Menu ``.lnk``
    permissions  advisory microphone-privacy probe + Settings deep link
    hotkey       push-to-talk via a ``WH_KEYBOARD_LL`` low-level hook
    inject       key chords + typed text via ``SendInput`` (``KEYEVENTF_UNICODE``)
    pointer      mouse movement/clicks via ``SetCursorPos`` / ``mouse_event``
    dpi          best-effort per-monitor DPI awareness (no-op off Windows)
"""
from __future__ import annotations

__all__ = ["desktop", "axtree", "clipboard", "launch", "permissions",
           "hotkey", "inject", "pointer", "dpi"]
