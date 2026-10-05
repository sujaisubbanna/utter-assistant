"""Keyboard injection.

Primary backend is `wtype` (virtual-keyboard Wayland protocol, no daemon); it
handles XKB key names and modifier chords directly. `ydotool` is the fallback
(needs `ydotoold`, see systemd/ydotoold.service).

Chord syntax: "ctrl+t", "super+Return", "ctrl+shift+Tab", "Return".
No shell is used.

On macOS (``utter.platform.is_macos()``) both entry points delegate to
:mod:`utter.macos.inject` (Quartz ``CGEventPost``, AppleScript fallback). An
optional ``pid`` selects native background posting (``CGEventPostToPid``, no
focus change); it is only meaningful on macOS — on Linux it is ignored and the
Wayland/X11 backends are used unchanged.
"""
from __future__ import annotations

import os
import subprocess
import time

from utter import platform
from utter.types import Action, ActionResult, Tier


def _macos_backend() -> str:
    try:
        from utter.config import load_config

        return getattr(load_config().macos, "injection", "quartz") or "quartz"
    except Exception:  # noqa: BLE001
        return "quartz"

_TIMEOUT = 5.0

# wtype modifier names
_MODS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "super": "logo",
    "meta": "logo",
    "win": "logo",
    "logo": "logo",
    "cmd": "logo",
    "command": "logo",
    "altgr": "altgr",
}

# ydotool evdev keycodes (fallback only)
_YDOTOOL_MOD = {"ctrl": 29, "shift": 42, "alt": 56, "logo": 125, "altgr": 100}
_YDOTOOL_KEY = {
    "return": 28, "enter": 28, "tab": 15, "escape": 1, "esc": 1,
    "space": 57, "backspace": 14, "delete": 111, "insert": 110,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "home": 102, "end": 107, "page_up": 104, "page_down": 109,
    "minus": 12, "equal": 13, "comma": 51, "period": 52, "slash": 53,
    "semicolon": 39, "apostrophe": 40, "grave": 41,
    "bracketleft": 26, "bracketright": 27, "backslash": 43,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
}
for _i, _ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _YDOTOOL_KEY[_ch] = 30 + _i
# evdev digit keycodes are not contiguous
_YDOTOOL_KEY.update({"1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
                     "6": 7, "7": 8, "8": 9, "9": 10, "0": 11})
_YDOTOOL_KEY.update({"+": 13, "=": 13, "-": 12, "_": 12})


def _ydotool_env() -> dict:
    env = os.environ.copy()
    runtime = env.get("XDG_RUNTIME_DIR")
    if runtime and "YDOTOOL_SOCKET" not in env:
        env["YDOTOOL_SOCKET"] = f"{runtime}/.ydotool_socket"
    return env


def prefers_ydotool() -> bool:
    """True on KWin: it has no virtual-keyboard protocol for ``wtype``, so
    ``ydotool`` (uinput) goes first and ``wtype`` is only a last resort."""
    try:
        from utter.context import compositor

        return compositor.active_name() == compositor.KWIN
    except Exception:  # noqa: BLE001
        return False


def _ydotool_key_result(tokens: list[str], t0: float) -> ActionResult:
    try:
        proc = _run(["ydotool", "key", *tokens], env=_ydotool_env())
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD, f"ydotool failed ({e})",
                            (time.perf_counter() - t0) * 1000)
    ok = proc.returncode == 0
    detail = "ydotool key" if ok else f"ydotool failed: {(proc.stderr or '').strip()}"
    return ActionResult(ok, Action.KEY, Tier.KEYBOARD, detail, (time.perf_counter() - t0) * 1000)


def _ydotool_type_result(text: str, t0: float) -> ActionResult:
    try:
        proc = subprocess.run(
            ["ydotool", "type", "-f", "-"],
            input=text,
            capture_output=True,
            text=True,
            timeout=max(_TIMEOUT, 1.0 + len(text) * 0.02),
            env=_ydotool_env(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD, f"ydotool failed ({e})",
                            (time.perf_counter() - t0) * 1000)
    ok = proc.returncode == 0
    detail = f"ydotool type {len(text)} chars" if ok else f"ydotool failed: {(proc.stderr or '').strip()}"
    return ActionResult(ok, Action.TYPE_TEXT, Tier.KEYBOARD, detail, (time.perf_counter() - t0) * 1000)


def _normalize_key(key: str) -> str:
    k = key.strip()
    low = k.casefold()
    if low in ("enter", "return"):
        return "Return"
    if low in ("esc", "escape"):
        return "Escape"
    if low == "space":
        return "space"
    if low.startswith("page") and ("up" in low or "down" in low):
        return "Page_Up" if "up" in low else "Page_Down"
    return k


def _wtype_chord(mods: list[str], key: str) -> list[str]:
    argv = ["wtype"]
    for m in mods:
        argv += ["-M", m]
    argv += ["-k", _normalize_key(key)]
    return argv


def _ydotool_chord(mods: list[str], key: str) -> list[str] | None:
    tokens: list[str] = []
    codes: list[int] = []
    for m in mods:
        code = _YDOTOOL_MOD.get(m)
        if code is None:
            return None
        codes.append(code)
        tokens.append(f"{code}:1")
    kc = _YDOTOOL_KEY.get(_normalize_key(key).casefold())
    if kc is None and len(key) == 1:
        kc = _YDOTOOL_KEY.get(key.casefold())
    if kc is None:
        return None
    tokens.append(f"{kc}:1")
    tokens.append(f"{kc}:0")
    for code in reversed(codes):
        tokens.append(f"{code}:0")
    return tokens


def _run(argv: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT, env=env)


def send_key(chord: str, *, pid: int | None = None) -> ActionResult:
    """Send a key chord, e.g. "ctrl+t", "super+Return", "Return".

    ``pid`` (macOS only) posts the chord straight to that process without
    changing focus; ``None`` keeps the focused behaviour.
    """
    if platform.is_macos():
        from utter.macos import inject

        return inject.send_key(chord, backend=_macos_backend(), pid=pid)
    if platform.is_windows():
        from utter.win32 import inject

        return inject.send_key(chord, pid=pid)
    t0 = time.perf_counter()
    spec = (chord or "").strip()
    if not spec:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD, "empty chord",
                            (time.perf_counter() - t0) * 1000)

    parts = [p for p in spec.split("+") if p != ""]
    if not parts:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD, f"bad chord {chord!r}",
                            (time.perf_counter() - t0) * 1000)
    *raw_mods, key = parts
    mods: list[str] = []
    for m in raw_mods:
        mapped = _MODS.get(m.strip().casefold())
        if mapped is None:
            return ActionResult(False, Action.KEY, Tier.KEYBOARD,
                                f"unknown modifier {m!r}",
                                (time.perf_counter() - t0) * 1000)
        mods.append(mapped)

    wtype_argv = _wtype_chord(mods, key)
    if prefers_ydotool():
        tokens = _ydotool_chord(mods, key)
        if tokens is not None:
            res = _ydotool_key_result(tokens, t0)
            if res.ok:
                return res
            # ydotool missing/failed: wtype is still worth one try (X11 sessions, XWayland)
    try:
        proc = _run(wtype_argv)
        if proc.returncode == 0:
            return ActionResult(True, Action.KEY, Tier.KEYBOARD,
                                f"wtype {' '.join(wtype_argv[1:])}",
                                (time.perf_counter() - t0) * 1000)
        wtype_err = (proc.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        wtype_err = str(e)

    tokens = _ydotool_chord(mods, key)
    if tokens is None:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD,
                            f"wtype failed ({wtype_err}); no ydotool mapping",
                            (time.perf_counter() - t0) * 1000)
    try:
        proc = _run(["ydotool", "key", *tokens], env=_ydotool_env())
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, Action.KEY, Tier.KEYBOARD,
                            f"wtype failed ({wtype_err}); ydotool failed ({e})",
                            (time.perf_counter() - t0) * 1000)
    ok = proc.returncode == 0
    detail = "ydotool key" if ok else f"ydotool failed: {(proc.stderr or '').strip()}"
    return ActionResult(ok, Action.KEY, Tier.KEYBOARD, detail,
                        (time.perf_counter() - t0) * 1000)


def type_text(text: str, *, pid: int | None = None) -> ActionResult:
    """Type literal text. ``pid`` (macOS only) targets that process."""
    if platform.is_macos():
        from utter.macos import inject

        return inject.type_text(text, backend=_macos_backend(), pid=pid)
    if platform.is_windows():
        from utter.win32 import inject

        return inject.type_text(text, pid=pid)
    t0 = time.perf_counter()
    if text is None:
        text = ""
    if prefers_ydotool():
        res = _ydotool_type_result(text, t0)
        if res.ok:
            return res
    try:
        proc = _run(["wtype", "--", text])
        if proc.returncode == 0:
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD,
                                f"wtype {len(text)} chars",
                                (time.perf_counter() - t0) * 1000)
        wtype_err = (proc.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        wtype_err = str(e)

    try:
        proc = subprocess.run(
            ["ydotool", "type", "-f", "-"],
            input=text,
            capture_output=True,
            text=True,
            timeout=max(_TIMEOUT, 1.0 + len(text) * 0.02),
            env=_ydotool_env(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                            f"wtype failed ({wtype_err}); ydotool failed ({e})",
                            (time.perf_counter() - t0) * 1000)
    ok = proc.returncode == 0
    detail = f"ydotool type {len(text)} chars" if ok else f"ydotool failed: {(proc.stderr or '').strip()}"
    return ActionResult(ok, Action.TYPE_TEXT, Tier.KEYBOARD, detail,
                        (time.perf_counter() - t0) * 1000)


__all__ = ["send_key", "type_text"]
