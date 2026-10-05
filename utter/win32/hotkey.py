"""Global push-to-talk keys on Windows via a low-level keyboard hook.

Primary backend: ``WH_KEYBOARD_LL`` installed with ``SetWindowsHookExW`` and
pumped by ``GetMessageW``. The hook is *listen-only*: it always chains to
``CallNextHookEx`` so the key still reaches the focused application, and the
desktop needs no elevation for a low-level hook.

Unlike macOS ``flagsChanged``, Windows delivers modifier keys as normal
``WM_KEYDOWN``/``WM_KEYUP`` messages, so press/release edges come straight from
the key's virtual-key code. Held keys auto-repeat ``WM_KEYDOWN``; the pure
:class:`PTTState` edge detector ignores those repeats.

Public API (same shape as :mod:`utter.voice.hotkey` on Linux):

    listen(on_press, on_release, key_name="KEY_RIGHTCTRL", *, stop_event=None)
    listen_many({"KEY_F13": (press, release), ...}, stop_event=None)
    resolve_keycode("KEY_RIGHTCTRL") -> 0xA3
    PTTState(...).feed("down" | "up", vk) -> "press" | "release" | None

``ctypes.windll`` / ``WinDLL`` are touched only inside the listener, and only
after :func:`utter.platform.is_windows` is true, so this module imports and its
pure parts are testable on Linux/macOS.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Optional, Tuple

from .. import platform

logger = logging.getLogger(__name__)

DEFAULT_KEY = "KEY_RIGHTCTRL"


def _canonical_keys() -> Dict[str, int]:
    keys: Dict[str, int] = {}
    for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
        keys[ch] = 0x41 + i
    for digit in range(10):
        keys[str(digit)] = 0x30 + digit
    for i in range(1, 25):
        keys[f"f{i}"] = 0x70 + (i - 1)
    for i in range(10):
        keys[f"kp{i}"] = 0x60 + i
    keys.update({
        "backspace": 0x08, "tab": 0x09, "return": 0x0D, "enter": 0x0D,
        "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
        "pause": 0x13, "caps_lock": 0x14, "capslock": 0x14,
        "escape": 0x1B, "esc": 0x1B,
        "space": 0x20,
        "page_up": 0x21, "pageup": 0x21, "prior": 0x21,
        "page_down": 0x22, "pagedown": 0x22, "next": 0x22,
        "end": 0x23, "home": 0x24,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "print_screen": 0x2C, "snapshot": 0x2C,
        "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
        "leftwin": 0x5B, "rightwin": 0x5C, "apps": 0x5D,
        "num_lock": 0x90, "scroll_lock": 0x91,
        "leftshift": 0xA0, "rightshift": 0xA1,
        "leftctrl": 0xA2, "rightctrl": 0xA3,
        "leftalt": 0xA4, "rightalt": 0xA5,
        "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D,
        "decimal": 0x6E, "divide": 0x6F,
        "minus": 0xBD, "equal": 0xBB, "comma": 0xBC, "period": 0xBE,
        "slash": 0xBF, "grave": 0xC0,
        "bracketleft": 0xDB, "backslash": 0xDC, "bracketright": 0xDD,
        "semicolon": 0xBA, "apostrophe": 0xDE,
        "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
        "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2,
        "media_play_pause": 0xB3,
    })
    return keys


#: Canonical Windows key name -> virtual-key code.
VK: Dict[str, int] = _canonical_keys()

#: Names (macOS-style or generic) that map onto a canonical key.
_ALIASES: Dict[str, str] = {
    "windows": "leftwin", "super": "leftwin", "meta": "leftwin",
    "logo": "leftwin", "cmd": "leftwin", "command": "leftwin",
    "option": "leftalt", "menu": "alt",
    "right_option": "rightalt", "left_option": "leftalt",
    "right_command": "rightwin", "left_command": "leftwin",
    "right_control": "rightctrl", "left_control": "leftctrl",
    "right_ctrl": "rightctrl", "left_ctrl": "leftctrl",
    "pageup": "page_up", "pagedown": "page_down",
    "printscreen": "print_screen", "capslock": "caps_lock",
}


def _evdev_keys() -> Dict[str, int]:
    """evdev ``KEY_*`` name -> Windows VK (so a shared config works)."""
    out: Dict[str, int] = {}
    for ch in "abcdefghijklmnopqrstuvwxyz":
        out["key_" + ch] = VK[ch]
    for digit in range(10):
        out["key_" + str(digit)] = VK[str(digit)]
    for i in range(1, 25):
        out[f"key_f{i}"] = VK[f"f{i}"]
    out.update({
        "key_esc": VK["escape"], "key_minus": VK["minus"], "key_equal": VK["equal"],
        "key_backspace": VK["backspace"], "key_tab": VK["tab"],
        "key_leftbrace": VK["bracketleft"], "key_rightbrace": VK["bracketright"],
        "key_enter": VK["return"],
        "key_leftctrl": VK["leftctrl"], "key_rightctrl": VK["rightctrl"],
        "key_semicolon": VK["semicolon"], "key_apostrophe": VK["apostrophe"],
        "key_grave": VK["grave"],
        "key_leftshift": VK["leftshift"], "key_rightshift": VK["rightshift"],
        "key_backslash": VK["backslash"], "key_comma": VK["comma"],
        "key_dot": VK["period"], "key_slash": VK["slash"],
        "key_leftalt": VK["leftalt"], "key_rightalt": VK["rightalt"],
        "key_space": VK["space"], "key_capslock": VK["caps_lock"],
        "key_leftmeta": VK["leftwin"], "key_rightmeta": VK["rightwin"],
        "key_insert": VK["insert"], "key_home": VK["home"],
        "key_pageup": VK["page_up"], "key_pagedown": VK["page_down"],
        "key_delete": VK["delete"], "key_end": VK["end"],
        "key_numlock": VK["num_lock"], "key_scrolllock": VK["scroll_lock"],
    })
    return out


#: Lower-cased evdev name -> virtual-key code.
_EVDEV_VK: Dict[str, int] = _evdev_keys()

#: Virtual-key codes that behave as modifiers (left/right variants included).
_MODIFIER_VK = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

#: msg id -> edge kind (mirrors the macOS ``_EVENT_KIND`` table).
_EVENT_KIND = {0x0100: "down", 0x0101: "up", 0x0104: "down", 0x0105: "up"}


def normalize_key(key_name: str) -> str:
    """Return the canonical key name for ``key_name`` (raises ``ValueError``)."""
    raw = (key_name or "").strip()
    if not raw:
        raise ValueError("empty key name")
    low = raw.casefold().replace("-", "_").replace(" ", "_")
    name = _ALIASES.get(low, low)
    if name in VK:
        return name
    if low in _EVDEV_VK:
        return low
    raise ValueError(f"unknown Windows key name: {key_name!r}")


def resolve_keycode(key_name: str) -> int:
    """Map a key name (Windows, macOS-style or evdev ``KEY_*``) to a VK code.

    A bare integer string is returned as-is so a numeric config value works.
    """
    raw = (key_name or "").strip()
    if not raw:
        raise ValueError("empty key name")
    if raw.isdigit():
        return int(raw)
    low = raw.casefold().replace("-", "_").replace(" ", "_")
    if low in _EVDEV_VK:
        return _EVDEV_VK[low]
    name = _ALIASES.get(low, low)
    if name in VK:
        return VK[name]
    if len(raw) == 1 and raw.casefold() in VK:
        return VK[raw.casefold()]
    raise ValueError(f"unknown Windows key name: {key_name!r}")


def is_modifier(keycode: int) -> bool:
    return int(keycode) in _MODIFIER_VK


class PTTState:
    """Edge detector for one push-to-talk key (pure; unit-tested).

    ``feed(kind, keycode)`` returns ``"press"``, ``"release"`` or ``None``.
    ``kind`` is ``"down"`` / ``"up"`` or a raw Windows message id
    (``WM_KEYDOWN`` = 0x0100, ``WM_KEYUP`` = 0x0101, and the ``WM_SYS*``
    variants). Auto-repeat ``down`` events while held return ``None``.
    """

    def __init__(self, keycode: int):
        self.keycode = int(keycode)
        self.pressed = False

    def feed(self, kind, keycode: int, flags: int = 0) -> Optional[str]:
        if isinstance(kind, int):
            kind = _EVENT_KIND.get(kind)
        if kind is None or int(keycode) != self.keycode:
            return None
        if kind == "down":
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


def _safe(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - a handler must never kill the hook
        logger.exception("push-to-talk handler failed")


def _dispatch(states: Dict[int, Tuple[PTTState, Handlers]], kind, keycode: int) -> None:
    entry = states.get(int(keycode))
    if entry is None:
        return
    state, (on_press, on_release) = entry
    edge = state.feed(kind, keycode)
    if edge == "press":
        _safe(on_press)
    elif edge == "release":
        _safe(on_release)


# -- WH_KEYBOARD_LL backend --------------------------------------------------

def _listen_hook(states, stop_event: Optional[threading.Event]) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
    WM_QUIT = 0x0012
    PM_NOREMOVE = 0x0000

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                                   wintypes.UINT, wintypes.UINT]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]

    holder: dict = {"hook": None, "proc": None}

    def _handler(n_code, w_param, l_param):
        if n_code >= HC_ACTION:
            msg = int(w_param)
            if msg in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                kind = "down" if msg in (WM_KEYDOWN, WM_SYSKEYDOWN) else "up"
                _dispatch(states, kind, int(kb.vkCode))
        # Listen-only: always let the event reach the focused application.
        return user32.CallNextHookEx(holder["hook"], n_code, w_param, l_param)

    proc = HOOKPROC(_handler)  # keep a reference alive for the hook lifetime
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
    if not hook:
        raise OSError(ctypes.get_last_error(),  # type: ignore[attr-defined]
                      "SetWindowsHookExW(WH_KEYBOARD_LL) failed")
    holder["hook"] = hook
    holder["proc"] = proc

    # Create this thread's message queue before a watcher may post to it.
    msg = wintypes.MSG()
    user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

    if stop_event is not None:
        thread_id = int(kernel32.GetCurrentThreadId())

        def _wait() -> None:
            stop_event.wait()
            user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)

        watcher = threading.Thread(target=_wait, name="win32-ptt-stop", daemon=True)
        watcher.start()

    logger.info("win32 low-level hook listening for keys %s", sorted(states))
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnhookWindowsHookEx(hook)


# -- public ------------------------------------------------------------------

def listen_many(keys: Dict[str, Handlers], *, stop_event: Optional[threading.Event] = None,
                **_ignored) -> None:
    """Block, dispatching press/release edges for several keys at once."""
    states: Dict[int, Tuple[PTTState, Handlers]] = {}
    for name, handlers in keys.items():
        code = resolve_keycode(name)
        states[code] = (PTTState(code), handlers)
    if not states:
        raise ValueError("no push-to-talk keys configured")
    if not platform.is_windows():
        raise RuntimeError("win32 hotkey backend is only available on Windows")
    return _listen_hook(states, stop_event)


def listen(on_press: Callable[[], None], on_release: Callable[[], None],
           key_name: str = DEFAULT_KEY, *, stop_event: Optional[threading.Event] = None,
           **_ignored) -> None:
    """Single-key blocking loop, API-compatible with :func:`utter.voice.hotkey.listen`."""
    listen_many({key_name: (on_press, on_release)}, stop_event=stop_event)


__all__ = ["listen", "listen_many", "resolve_keycode", "normalize_key", "is_modifier",
           "PTTState", "VK", "DEFAULT_KEY"]
