"""Global push-to-talk keys on macOS, without ``keyd``/``evdev``.

Primary backend: a Quartz ``CGEventTap`` (listen-only, never swallows events)
created through PyObjC. Modifier keys (Option/Command/Control/Shift/Fn) only
produce ``flagsChanged`` events, so press/release edges are derived from the
key code plus the modifier-flag transition. Regular keys (F13..F20, etc.) use
``keyDown``/``keyUp`` with auto-repeat ignored.

Fallback backend: ``pynput`` (``pynput.keyboard.Listener``), which uses the same
mechanism under the hood but needs no Quartz bindings.

Both need the process (your terminal or Python.app) to be allowed under
System Settings -> Privacy & Security -> Input Monitoring (and Accessibility).

Public API (same shape as :mod:`utter.voice.hotkey` on Linux):

    listen(on_press, on_release, key_name="right_option", *, stop_event=None)
    listen_many({"right_option": (press, release), ...}, stop_event=None)
    resolve_keycode("right_option") -> 61
    PTTState(...).feed(event_kind, keycode, flags) -> "press" | "release" | None
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_KEY = "right_option"

# Virtual key codes (Carbon ``kVK_*``) for keys that make sense as PTT keys.
KEYCODES: Dict[str, int] = {
    "right_command": 54, "right_cmd": 54,
    "left_command": 55, "left_cmd": 55, "command": 55, "cmd": 55,
    "left_shift": 56, "shift": 56,
    "caps_lock": 57,
    "left_option": 58, "left_alt": 58, "option": 58, "alt": 58,
    "left_control": 59, "left_ctrl": 59, "control": 59, "ctrl": 59,
    "right_shift": 60,
    "right_option": 61, "right_alt": 61,
    "right_control": 62, "right_ctrl": 62,
    "fn": 63, "function": 63,
    "f13": 105, "f14": 107, "f15": 113, "f16": 106, "f17": 64,
    "f18": 79, "f19": 80, "f20": 90,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "space": 49, "escape": 53, "esc": 53, "tab": 48, "grave": 50,
    "home": 115, "end": 119, "page_up": 116, "page_down": 121,
    "insert": 114, "help": 114,
}

# Modifier flag bit each modifier key toggles in ``CGEventFlags``.
_FLAG_ALPHA_SHIFT = 1 << 16
_FLAG_SHIFT = 1 << 17
_FLAG_CONTROL = 1 << 18
_FLAG_ALTERNATE = 1 << 19
_FLAG_COMMAND = 1 << 20
_FLAG_SECONDARY_FN = 1 << 23

MODIFIER_FLAG: Dict[int, int] = {
    54: _FLAG_COMMAND, 55: _FLAG_COMMAND,
    56: _FLAG_SHIFT, 60: _FLAG_SHIFT,
    57: _FLAG_ALPHA_SHIFT,
    58: _FLAG_ALTERNATE, 61: _FLAG_ALTERNATE,
    59: _FLAG_CONTROL, 62: _FLAG_CONTROL,
    63: _FLAG_SECONDARY_FN,
}

# CGEventType values we care about.
EVENT_KEY_DOWN = 10
EVENT_KEY_UP = 11
EVENT_FLAGS_CHANGED = 12
EVENT_TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
EVENT_TAP_DISABLED_BY_USER = 0xFFFFFFFF

_EVENT_KIND = {EVENT_KEY_DOWN: "down", EVENT_KEY_UP: "up", EVENT_FLAGS_CHANGED: "flags"}


def resolve_keycode(key_name: str) -> int:
    """Map a key name (``"right_option"``, ``"f13"``, or a bare integer) to a code.

    Linux-style evdev names such as ``KEY_RIGHTALT`` are accepted too so a shared
    config does not blow up on macOS.
    """
    raw = (key_name or "").strip()
    if not raw:
        raise ValueError("empty key name")
    if raw.isdigit():
        return int(raw)
    low = raw.lower().replace("-", "_").replace(" ", "_")
    if low in KEYCODES:
        return KEYCODES[low]
    if low.startswith("key_"):
        alias = {
            "key_rightalt": "right_option", "key_leftalt": "left_option",
            "key_rightctrl": "right_control", "key_leftctrl": "left_control",
            "key_rightmeta": "right_command", "key_leftmeta": "left_command",
            "key_rightshift": "right_shift", "key_leftshift": "left_shift",
            "key_insert": "insert", "key_capslock": "caps_lock", "key_space": "space",
        }.get(low)
        if alias is None and low[4:] in KEYCODES:
            alias = low[4:]
        if alias is not None:
            return KEYCODES[alias]
    raise ValueError(f"unknown macOS key name: {key_name!r}")


def is_modifier(keycode: int) -> bool:
    return int(keycode) in MODIFIER_FLAG


class PTTState:
    """Edge detector for one push-to-talk key (pure; unit-tested).

    ``feed(kind, keycode, flags)`` returns ``"press"``, ``"release"`` or None.
    ``kind`` is ``"down"`` / ``"up"`` / ``"flags"`` (or the raw CGEventType).
    Auto-repeat ``down`` events while held are ignored.
    """

    def __init__(self, keycode: int):
        self.keycode = int(keycode)
        self.pressed = False

    def feed(self, kind, keycode: int, flags: int = 0) -> Optional[str]:
        if isinstance(kind, int):
            kind = _EVENT_KIND.get(kind)
        if kind is None or int(keycode) != self.keycode:
            return None
        if kind == "flags":
            bit = MODIFIER_FLAG.get(self.keycode)
            if bit is None:
                return None
            down = bool(int(flags) & bit)
        elif kind == "down":
            down = True
        elif kind == "up":
            down = False
        else:
            return None
        if down and not self.pressed:
            self.pressed = True
            return "press"
        if not down and self.pressed:
            self.pressed = False
            return "release"
        return None


Handlers = Tuple[Callable[[], None], Callable[[], None]]


def _dispatch(states: Dict[int, Tuple[PTTState, Handlers]], kind, keycode: int, flags: int) -> None:
    entry = states.get(int(keycode))
    if entry is None:
        return
    state, (on_press, on_release) = entry
    edge = state.feed(kind, keycode, flags)
    if edge == "press":
        _safe(on_press)
    elif edge == "release":
        _safe(on_release)


def _safe(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - a handler must never kill the tap
        logger.exception("push-to-talk handler failed")


# -- Quartz backend ----------------------------------------------------------

def _listen_quartz(states, stop_event: Optional[threading.Event]) -> None:
    import Quartz  # type: ignore[import-not-found]

    mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
    tap_holder: dict = {"tap": None}

    def _callback(proxy, event_type, event, refcon):
        et = int(event_type)
        if et in (EVENT_TAP_DISABLED_BY_TIMEOUT, EVENT_TAP_DISABLED_BY_USER):
            if tap_holder["tap"] is not None:
                Quartz.CGEventTapEnable(tap_holder["tap"], True)
            return event
        keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
        flags = int(Quartz.CGEventGetFlags(event))
        if et == EVENT_KEY_DOWN and Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventAutorepeat):
            return event
        _dispatch(states, et, keycode, flags)
        return event  # listen-only: never swallow

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly, mask, _callback, None)
    if tap is None:
        raise RuntimeError(
            "CGEventTapCreate failed: allow this app under System Settings -> "
            "Privacy & Security -> Input Monitoring (and Accessibility)")
    tap_holder["tap"] = tap
    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    loop = Quartz.CFRunLoopGetCurrent()
    Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    logger.info("quartz event tap listening for keys %s", sorted(states))
    try:
        while not (stop_event is not None and stop_event.is_set()):
            # Run the loop in short slices so stop_event is honoured.
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.25, False)
    finally:
        Quartz.CGEventTapEnable(tap, False)
        Quartz.CFRunLoopRemoveSource(loop, source, Quartz.kCFRunLoopCommonModes)


# -- pynput backend ----------------------------------------------------------

def _listen_pynput(states, stop_event: Optional[threading.Event]) -> None:
    from pynput import keyboard  # type: ignore[import-not-found]

    def _vk(key) -> Optional[int]:
        vk = getattr(key, "vk", None)
        if vk is None:
            vk = getattr(getattr(key, "value", None), "vk", None)
        return int(vk) if vk is not None else None

    def on_press(key):
        vk = _vk(key)
        if vk is not None:
            _dispatch(states, "down", vk, 0)

    def on_release(key):
        vk = _vk(key)
        if vk is not None:
            _dispatch(states, "up", vk, 0)

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        logger.info("pynput listener watching keys %s", sorted(states))
        while listener.running and not (stop_event is not None and stop_event.is_set()):
            listener.join(0.25)


# -- public ------------------------------------------------------------------

def listen_many(keys: Dict[str, Handlers], *, stop_event: Optional[threading.Event] = None,
                backend: str = "quartz") -> None:
    """Block, dispatching press/release edges for several keys at once."""
    states: Dict[int, Tuple[PTTState, Handlers]] = {}
    for name, handlers in keys.items():
        code = resolve_keycode(name)
        states[code] = (PTTState(code), handlers)
    if not states:
        raise ValueError("no push-to-talk keys configured")
    chosen = (backend or "quartz").strip().lower()
    if chosen == "pynput":
        return _listen_pynput(states, stop_event)
    try:
        return _listen_quartz(states, stop_event)
    except ImportError:
        logger.warning("pyobjc-framework-Quartz missing; trying pynput")
        return _listen_pynput(states, stop_event)


def listen(on_press: Callable[[], None], on_release: Callable[[], None],
           key_name: str = DEFAULT_KEY, *, stop_event: Optional[threading.Event] = None,
           backend: str = "quartz", **_ignored) -> None:
    """Single-key blocking loop, API-compatible with :func:`utter.voice.hotkey.listen`."""
    listen_many({key_name: (on_press, on_release)}, stop_event=stop_event, backend=backend)


__all__ = ["listen", "listen_many", "resolve_keycode", "is_modifier", "PTTState",
           "KEYCODES", "MODIFIER_FLAG", "DEFAULT_KEY"]
