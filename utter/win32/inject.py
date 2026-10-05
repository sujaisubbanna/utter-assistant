"""Key presses and typed text on Windows via ``SendInput``.

Literal text is sent as Unicode scan codes (``KEYEVENTF_UNICODE``), so any
character types regardless of the active keyboard layout. Chords are sent as
virtual-key events with their modifiers pressed and released around the key.

Chord syntax matches Linux/macOS: ``"ctrl+t"``, ``"super+Return"``, ``"Enter"``.
``super``/``meta``/``win``/``logo``/``cmd`` map to the Windows key.

``SetForegroundWindow`` is deliberately *not* called: injection targets
whatever window has focus, same contract as the Linux backends. ``ctypes.windll``
is touched only inside the send helpers, never at import time.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

from ..types import Action, ActionResult, Tier
from . import hotkey as _hotkey

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Modifier name -> left/right-specific virtual-key code (unambiguous).
MODS = {
    "ctrl": 0xA2, "control": 0xA2,
    "shift": 0xA0,
    "alt": 0xA4, "option": 0xA4, "altgr": 0xA5,
    "super": 0x5B, "meta": 0x5B, "win": 0x5B, "windows": 0x5B,
    "logo": 0x5B, "cmd": 0x5B, "command": 0x5B,
}

# Virtual keys that must carry KEYEVENTF_EXTENDEDKEY on Windows.
_EXTENDED = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,   # page up/down, end, home, arrows
    0x2D, 0x2E, 0x2C, 0x5B, 0x5C, 0x6F, 0x0D,          # insert, delete, snapshot, win, divide, numpad enter
    0xA3, 0xA5,                                          # right ctrl / right alt
}


def _is_extended(vk: int) -> bool:
    return int(vk) in _EXTENDED


def parse_chord(chord: str) -> Tuple[List[int], int]:
    """``"ctrl+shift+t"`` -> ``([0xA2, 0xA0], 0x54)``.

    Raises ``ValueError`` for empty chords, unknown modifiers or unknown keys.
    Pure (no ctypes); unit-tested on any platform.
    """
    spec = (chord or "").strip()
    parts = [p for p in spec.split("+") if p != ""]
    if spec.endswith("+") and spec.rstrip("+"):
        parts.append("+")
    if not parts:
        raise ValueError(f"bad chord {chord!r}")
    *raw_mods, key = parts
    mods: List[int] = []
    for m in raw_mods:
        vk = MODS.get(m.strip().casefold())
        if vk is None:
            raise ValueError(f"unknown modifier {m!r}")
        if vk not in mods:
            mods.append(vk)
    try:
        key_vk = _hotkey.resolve_keycode(key)
    except ValueError as exc:
        raise ValueError(f"unknown key {key!r}") from exc
    return mods, key_vk


def _send_input(items: List[Tuple[int, int, int]]) -> None:
    """Send ``(vk, scan, flags)`` keyboard events through ``SendInput``."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG), ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    INPUT_KEYBOARD = 1
    count = len(items)
    if count == 0:
        return
    array = (INPUT * count)()
    for i, (vk, scan, flags) in enumerate(items):
        array[i].type = INPUT_KEYBOARD
        array[i].u.ki = KEYBDINPUT(int(vk) & 0xFFFF, int(scan) & 0xFFFF,
                                   int(flags) & 0xFFFFFFFF, 0, None)
    sent = user32.SendInput(count, ctypes.byref(array), ctypes.sizeof(INPUT))
    if sent != count:
        raise OSError(ctypes.get_last_error(),  # type: ignore[attr-defined]
                      f"SendInput sent {sent}/{count}")


def _chord_events(mods: List[int], key_vk: int) -> List[Tuple[int, int, int]]:
    events: List[Tuple[int, int, int]] = []
    for vk in mods:
        events.append((vk, 0, KEYEVENTF_EXTENDEDKEY if _is_extended(vk) else 0))
    key_flags = KEYEVENTF_EXTENDEDKEY if _is_extended(key_vk) else 0
    events.append((key_vk, 0, key_flags))
    events.append((key_vk, 0, key_flags | KEYEVENTF_KEYUP))
    for vk in reversed(mods):
        flags = KEYEVENTF_EXTENDEDKEY if _is_extended(vk) else 0
        events.append((vk, 0, flags | KEYEVENTF_KEYUP))
    return events


def _text_events(text: str, chunk: int = 64) -> List[Tuple[int, int, int]]:
    """`text` -> Unicode keyboard events (UTF-16 code units, surrogate pairs)."""
    raw = text.encode("utf-16-le")
    units: List[int] = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    events: List[Tuple[int, int, int]] = []
    for start in range(0, len(units), chunk):
        for unit in units[start:start + chunk]:
            events.append((0, unit, KEYEVENTF_UNICODE))
            events.append((0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(0.002)
    return events


def send_key(chord: str, *, pid: Optional[int] = None) -> ActionResult:
    """Send a key chord, e.g. ``"ctrl+t"``. ``pid`` is ignored on Windows."""
    t0 = time.perf_counter()
    try:
        mods, key_vk = parse_chord(chord)
    except ValueError as exc:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD, str(exc),
                            (time.perf_counter() - t0) * 1000)
    try:
        _send_input(_chord_events(mods, key_vk))
    except Exception as exc:  # noqa: BLE001 - report, never raise into the executor
        return ActionResult(False, Action.KEY, Tier.KEYBOARD, f"SendInput failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.KEY, Tier.KEYBOARD, f"win32 key {chord}",
                        (time.perf_counter() - t0) * 1000)


def type_text(text: str, *, pid: Optional[int] = None) -> ActionResult:
    """Type literal text as Unicode. ``pid`` is ignored on Windows."""
    t0 = time.perf_counter()
    text = text or ""
    if not text:
        return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "win32 typed 0 chars",
                            (time.perf_counter() - t0) * 1000)
    try:
        _send_input(_text_events(text))
    except Exception as exc:  # noqa: BLE001
        return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                            f"SendInput failed: {exc}",
                            (time.perf_counter() - t0) * 1000)
    return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD,
                        f"win32 typed {len(text)} chars",
                        (time.perf_counter() - t0) * 1000)


__all__ = ["send_key", "type_text", "parse_chord", "MODS"]
