"""Key presses and typed text on macOS.

Primary: Quartz ``CGEventPost`` (``CGEventCreateKeyboardEvent`` for chords,
``CGEventKeyboardSetUnicodeString`` for literal text, so any Unicode types
regardless of keyboard layout). Fallback: AppleScript through ``osascript``
(``System Events`` ``keystroke`` / ``key code``). Both need Accessibility
permission for the hosting process. No shell is used.

Chord syntax matches Linux: ``"ctrl+t"``, ``"cmd+Return"``, ``"super+space"``.
``super``/``meta``/``win``/``logo`` map to Command on macOS.
"""
from __future__ import annotations

import logging
import subprocess
import time
from typing import Optional

from utter.types import Action, ActionResult, Tier

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0

# Modifier name -> (CGEventFlags bit, AppleScript name)
_FLAG_SHIFT = 1 << 17
_FLAG_CONTROL = 1 << 18
_FLAG_ALTERNATE = 1 << 19
_FLAG_COMMAND = 1 << 20
_FLAG_FN = 1 << 23

MODS: dict[str, tuple[int, str]] = {
    "ctrl": (_FLAG_CONTROL, "control down"), "control": (_FLAG_CONTROL, "control down"),
    "shift": (_FLAG_SHIFT, "shift down"),
    "alt": (_FLAG_ALTERNATE, "option down"), "option": (_FLAG_ALTERNATE, "option down"),
    "altgr": (_FLAG_ALTERNATE, "option down"),
    "cmd": (_FLAG_COMMAND, "command down"), "command": (_FLAG_COMMAND, "command down"),
    "super": (_FLAG_COMMAND, "command down"), "meta": (_FLAG_COMMAND, "command down"),
    "win": (_FLAG_COMMAND, "command down"), "logo": (_FLAG_COMMAND, "command down"),
    "fn": (_FLAG_FN, ""),
}

# Modifier key codes pressed/released around a chord so apps that inspect the
# physical modifier state (not only the flags) also see it.
_MOD_KEYCODE = {_FLAG_CONTROL: 59, _FLAG_SHIFT: 56, _FLAG_ALTERNATE: 58, _FLAG_COMMAND: 55, _FLAG_FN: 63}

# Virtual key codes (ANSI layout; letters/digits are layout-dependent in theory
# but these are the codes every US/ISO Mac keyboard reports).
KEYCODES: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "equal": 24, "=": 24,
    "9": 25, "7": 26, "minus": 27, "-": 27, "8": 28, "0": 29,
    "bracketright": 30, "]": 30, "o": 31, "u": 32, "bracketleft": 33, "[": 33,
    "i": 34, "p": 35, "return": 36, "enter": 36, "l": 37, "j": 38,
    "apostrophe": 39, "'": 39, "k": 40, "semicolon": 41, ";": 41,
    "backslash": 42, "\\": 42, "comma": 43, ",": 43, "slash": 44, "/": 44,
    "n": 45, "m": 46, "period": 47, ".": 47, "tab": 48, "space": 49,
    "grave": 50, "`": 50, "backspace": 51, "delete": 117, "escape": 53, "esc": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "f13": 105, "f14": 107, "f15": 113, "f16": 106, "f17": 64, "f18": 79, "f19": 80, "f20": 90,
    "home": 115, "page_up": 116, "page_down": 121, "end": 119,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "insert": 114, "help": 114, "caps_lock": 57,
    "volume_up": 72, "volume_down": 73, "mute": 74,
}

_ALIASES = {"pageup": "page_up", "pagedown": "page_down", "prior": "page_up", "next": "page_down",
            "del": "delete", "plus": "equal", "+": "equal", "_": "minus"}


def normalize_key(key: str) -> str:
    k = (key or "").strip()
    low = k.casefold()
    low = _ALIASES.get(low, low)
    if low in ("page_up", "page_down"):
        return low
    if low.startswith("page") and ("up" in low or "down" in low):
        return "page_up" if "up" in low else "page_down"
    return low


def parse_chord(chord: str) -> tuple[int, list[str], int, str]:
    """``"ctrl+shift+t"`` -> ``(flags, applescript_mods, keycode, key)``.

    Raises ValueError for empty chords, unknown modifiers or unknown keys.
    """
    spec = (chord or "").strip()
    parts = [p for p in spec.split("+") if p != ""]
    if spec.endswith("+") and spec.rstrip("+"):
        parts.append("+")
    if not parts:
        raise ValueError(f"bad chord {chord!r}")
    *raw_mods, key = parts
    flags = 0
    as_mods: list[str] = []
    for m in raw_mods:
        entry = MODS.get(m.strip().casefold())
        if entry is None:
            raise ValueError(f"unknown modifier {m!r}")
        flags |= entry[0]
        if entry[1] and entry[1] not in as_mods:
            as_mods.append(entry[1])
    nk = normalize_key(key)
    code = KEYCODES.get(nk)
    if code is None and len(key) == 1:
        code = KEYCODES.get(key.casefold())
    if code is None:
        raise ValueError(f"unknown key {key!r}")
    return flags, as_mods, code, nk


# -- Quartz --------------------------------------------------------------------

def _post_key(Quartz, keycode: int, down: bool, flags: int = 0) -> None:
    ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
    if flags:
        Quartz.CGEventSetFlags(ev, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _quartz_chord(flags: int, keycode: int) -> None:
    import Quartz  # type: ignore[import-not-found]

    held = [kc for bit, kc in _MOD_KEYCODE.items() if flags & bit]
    acc = 0
    for bit, kc in _MOD_KEYCODE.items():
        if flags & bit:
            acc |= bit
            _post_key(Quartz, kc, True, acc)
    _post_key(Quartz, keycode, True, flags)
    _post_key(Quartz, keycode, False, flags)
    for kc in reversed(held):
        _post_key(Quartz, kc, False, 0)


def _quartz_type(text: str, chunk: int = 20) -> None:
    import Quartz  # type: ignore[import-not-found]

    for i in range(0, len(text), chunk):
        piece = text[i:i + chunk]
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(piece), piece)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.004)


# -- AppleScript ---------------------------------------------------------------

def applescript_key(as_mods: list[str], keycode: int) -> str:
    using = f" using {{{', '.join(as_mods)}}}" if as_mods else ""
    return f'tell application "System Events" to key code {int(keycode)}{using}'


def applescript_type(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'tell application "System Events" to keystroke "{escaped}"'


def _osascript(script: str, timeout: float = _TIMEOUT) -> tuple[bool, str]:
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
    return True, ""


# -- public --------------------------------------------------------------------

def send_key(chord: str, *, backend: str = "quartz") -> ActionResult:
    """Send a key chord such as ``"cmd+t"`` or ``"Return"``."""
    t0 = time.perf_counter()
    try:
        flags, as_mods, keycode, key = parse_chord(chord)
    except ValueError as exc:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD, str(exc),
                            (time.perf_counter() - t0) * 1000)
    err: Optional[str] = None
    if (backend or "quartz").lower() != "applescript":
        try:
            _quartz_chord(flags, keycode)
            return ActionResult(True, Action.KEY, Tier.KEYBOARD,
                                f"quartz key {chord}", (time.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001 - fall back to AppleScript
            err = str(exc)
    ok, as_err = _osascript(applescript_key(as_mods, keycode))
    detail = f"osascript key code {keycode}" if ok else \
        f"quartz failed ({err}); osascript failed ({as_err})" if err else f"osascript failed: {as_err}"
    return ActionResult(ok, Action.KEY, Tier.KEYBOARD, detail, (time.perf_counter() - t0) * 1000)


def type_text(text: str, *, backend: str = "quartz") -> ActionResult:
    """Type literal text into the focused field."""
    t0 = time.perf_counter()
    text = text or ""
    err: Optional[str] = None
    if (backend or "quartz").lower() != "applescript":
        try:
            _quartz_type(text)
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD,
                                f"quartz typed {len(text)} chars", (time.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
    ok, as_err = _osascript(applescript_type(text), timeout=max(_TIMEOUT, 1.0 + len(text) * 0.02))
    detail = f"osascript typed {len(text)} chars" if ok else \
        f"quartz failed ({err}); osascript failed ({as_err})" if err else f"osascript failed: {as_err}"
    return ActionResult(ok, Action.TYPE_TEXT, Tier.KEYBOARD, detail, (time.perf_counter() - t0) * 1000)


__all__ = ["send_key", "type_text", "parse_chord", "normalize_key", "applescript_key",
           "applescript_type", "KEYCODES", "MODS"]
