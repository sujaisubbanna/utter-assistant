"""Map GDK key events to Linux evdev key names (``KEY_F13``, ``KEY_INSERT`` …).

The config stores evdev names (see ``[ptt]`` in config.default.toml). On
Wayland, GDK keycodes are evdev scancodes plus the XKB offset of 8.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

XKB_OFFSET = 8
_HEADER = Path("/usr/include/linux/input-event-codes.h")


def _from_evdev() -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        from evdev import ecodes  # type: ignore

        for name, code in ecodes.ecodes.items():
            if name.startswith("KEY_") and isinstance(code, int):
                out.setdefault(code, name)
    except Exception:  # noqa: BLE001
        pass
    return out


def _from_header() -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        text = _HEADER.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for match in re.finditer(r"^#define\s+(KEY_[A-Z0-9_]+)\s+(0x[0-9a-fA-F]+|\d+)", text, re.M):
        name, raw = match.group(1), match.group(2)
        out.setdefault(int(raw, 0), name)
    return out


def _build() -> dict[int, str]:
    merged = _from_header()
    merged.update(_from_evdev())  # evdev names win where both exist
    return merged


_MAP: dict[int, str] = _build()


def name_for_gdk_keycode(keycode: int) -> Optional[str]:
    """Return e.g. ``KEY_F13`` for a GDK keycode, or None if unknown."""
    return _MAP.get(int(keycode) - XKB_OFFSET)


def is_modifier(evdev_name: str) -> bool:
    return evdev_name in {
        "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT", "KEY_LEFTCTRL", "KEY_RIGHTCTRL",
        "KEY_LEFTALT", "KEY_RIGHTALT", "KEY_LEFTMETA", "KEY_RIGHTMETA",
        "KEY_CAPSLOCK", "KEY_NUMLOCK", "KEY_SCROLLLOCK", "KEY_COMPOSE",
    }


def display_name(evdev_name: str) -> str:
    if not evdev_name:
        return "not set"
    pretty = evdev_name
    if pretty.startswith("KEY_"):
        pretty = pretty[4:]
    replacements = {
        "LEFTCTRL": "Left Ctrl", "RIGHTCTRL": "Right Ctrl",
        "LEFTSHIFT": "Left Shift", "RIGHTSHIFT": "Right Shift",
        "LEFTALT": "Left Alt", "RIGHTALT": "Right Alt",
        "LEFTMETA": "Left Super", "RIGHTMETA": "Right Super",
        "INSERT": "Insert", "DELETE": "Delete", "RETURN": "Enter",
        "SPACE": "Space", "ESC": "Escape", "TAB": "Tab",
    }
    if pretty in replacements:
        return replacements[pretty]
    if pretty.startswith("F") and pretty[1:].isdigit():
        return pretty
    return pretty.replace("_", " ").title()
