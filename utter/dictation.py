"""Dictation delivery: target pinning, typing and the clipboard fallback.

Extracted from :mod:`utter.daemon` so the daemon voice lanes and the
``assistant dictation`` CLI share one implementation:

* pin the window focused at key-down and type the transcript there,
* copy the transcript to the clipboard when typing fails (the safety net),
* park an undelivered transcript in a pending record so the user can pick a
  destination after the fact (``$XDG_RUNTIME_DIR/utter/dictation-pending.json``).

Nothing here may raise into the audio/recognition path; every entry point
degrades to a returned failure.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .types import Action, ActionResult, FocusedWindow, Tier

log = logging.getLogger("utter")

# --- dictation target pinning ----------------------------------------------
# Dictation is typed into the window that was focused when the key went *down*,
# not whatever happens to be focused by the time the key is released.
_DICTATION_FALLBACK = "Choose where to type it (also copied)"
_DICTATION_FALLBACK_NOCLIP = "Choose where to type it (copy failed)"


def _capture_dictation_target() -> Optional[FocusedWindow]:
    """Snapshot the focused window at key-down (None when unavailable).

    Only the window is captured: neither platform exposes a cheap, generic
    "focused element" probe (macOS AX tree is unwired, AT-SPI has no focused
    node), so element capture is deliberately deferred to a follow-up.
    """
    from .context import desktop
    try:
        return desktop.focused_window()
    except Exception:  # noqa: BLE001 - capture must never break listening
        log.debug("dictation target capture failed", exc_info=True)
        return None


def _still_focused(target) -> bool:
    """Best-effort: is ``target`` the window that is focused right now?"""
    from .context import desktop
    try:
        current = desktop.focused_window()
    except Exception:  # noqa: BLE001
        return False
    if current is None:
        return False
    wid = int(getattr(target, "window_id", 0) or 0)
    cwid = int(getattr(current, "window_id", 0) or 0)
    if wid and cwid:
        return wid == cwid
    pid = int(getattr(target, "pid", 0) or 0)
    cpid = int(getattr(current, "pid", 0) or 0)
    if pid and cpid:
        return pid == cpid
    return (bool(getattr(current, "app_id", ""))
            and current.app_id == getattr(target, "app_id", ""))


def _refocus(target) -> bool:
    """Re-focus the pinned window before typing (Linux best effort)."""
    from .context import desktop
    wid = int(getattr(target, "window_id", 0) or 0)
    if not wid:
        return False
    try:
        return bool(desktop.focus_window_on_workspace(wid))
    except Exception:  # noqa: BLE001
        log.debug("dictation re-focus failed", exc_info=True)
        return False


def _type_dictation(text: str, target) -> ActionResult:
    """Type ``text`` into the key-down target. Never raises.

    macOS posts to the captured pid, so the user's current focus is untouched.
    Linux has no per-window text injection on Wayland: type as-is when the
    target is still focused, otherwise re-focus it first (best effort). Any
    failure is returned as ``ok=False`` for the caller's clipboard fallback.
    """
    from .actions import keyboard
    from . import platform
    try:
        if target is None:
            return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                                "no dictation target")
        if platform.is_macos():
            pid = int(getattr(target, "pid", 0) or 0)
            return keyboard.type_text(text, pid=pid or None)
        if not _still_focused(target):
            _refocus(target)
        return keyboard.type_text(text)
    except Exception as exc:  # noqa: BLE001 - degrade to the clipboard fallback
        return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                            f"type_text failed: {exc}")


def _deliver_dictation(text: str, target, cfg) -> ActionResult:
    """The one dictation seam both platforms call (Linux ``run_hotkey`` and
    macOS ``run_macos``): optionally reformat the transcript, then type it.

    Kept in a single place so the transform is never duplicated per platform,
    and so the assistant lane (which never calls this) stays untouched.
    ``format_transcript`` is offline-safe and returns the raw text on failure.
    """
    from .voice.formatting import format_transcript
    return _type_dictation(format_transcript(text, cfg), target)


def _copy_to_clipboard(text: str) -> bool:
    """Copy ``text`` for the fallback (macOS ``pbcopy`` / Linux ``wl-copy``)."""
    try:
        from . import platform
        if platform.is_macos():
            from .macos import clipboard
        else:
            from .context import clipboard
        return bool(clipboard.set_clipboard(text))
    except Exception:  # noqa: BLE001 - a missing tool must not break the loop
        log.debug("dictation clipboard fallback failed", exc_info=True)
        return False


# --- pending record ---------------------------------------------------------
# An undelivered dictation is parked here so the user can pick a destination
# after the fact. Shape: {"text": str, "reason": str, "ts": int}.
def pending_path() -> Path:
    """``$XDG_RUNTIME_DIR/utter/dictation-pending.json``."""
    from assistant.util import xdg_runtime_dir
    return xdg_runtime_dir() / "utter" / "dictation-pending.json"


def write_pending(text: str, reason: str, ts: Optional[int] = None) -> dict:
    """Atomically write the pending record and return it.

    Uses the same atomic write pattern as the rest of the assistant
    (:func:`assistant.util.atomic_write_json`).
    """
    from assistant.util import atomic_write_json
    record = {
        "text": str(text),
        "reason": str(reason or ""),
        "ts": int(time.time() if ts is None else ts),
    }
    atomic_write_json(pending_path(), record)
    return record


def read_pending() -> dict:
    """The pending record, or ``{}`` when absent/malformed."""
    from assistant.util import read_json
    try:
        data = read_json(pending_path(), default={})
    except Exception:  # noqa: BLE001 - a bad file must not break the CLI
        return {}
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        return data
    return {}


def clear_pending() -> bool:
    """Remove the pending record (True when one existed)."""
    try:
        pending_path().unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:  # noqa: BLE001 - best effort; absence is the goal
        log.debug("could not clear dictation pending record", exc_info=True)
        return False


# --- target-spec resolution + re-delivery -----------------------------------
def _list_windows() -> list:
    """Desktop windows for target resolution (empty on any backend failure)."""
    try:
        from .context import desktop
        return list(desktop.list_windows())
    except Exception:  # noqa: BLE001 - an unavailable backend is not an error
        log.debug("dictation window list failed", exc_info=True)
        return []


def _field(win, name: str, default=None):
    if isinstance(win, dict):
        return win.get(name, default)
    return getattr(win, name, default)


def _as_focused(win) -> FocusedWindow:
    """Normalize a ``WindowInfo``/dict to the typing target shape.

    ``WindowInfo.id`` maps to ``FocusedWindow.window_id`` (the two dataclasses
    spell the same field differently).
    """
    wid = _field(win, "window_id")
    if wid is None:
        wid = _field(win, "id", 0)
    return FocusedWindow(
        app_id=str(_field(win, "app_id", "") or ""),
        title=str(_field(win, "title", "") or ""),
        pid=int(_field(win, "pid", 0) or 0),
        window_id=int(wid or 0),
        workspace_id=int(_field(win, "workspace_id", 0) or 0),
    )


def resolve_target(spec: str, windows=None) -> Optional[FocusedWindow]:
    """Resolve a picker spec to a typing target (``None`` when unmatched).

    Accepted forms: ``<window-id>``, ``id:<window-id>``, ``pid:<n>``,
    ``app_id:<string>``. ``app_id`` prefers the focused window when several
    windows share the id. ``windows`` may be injected (tests); otherwise the
    live :mod:`utter.context` window list is used.
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    wins = list(windows) if windows is not None else _list_windows()

    match = None
    if spec.startswith("pid:"):
        key = spec[len("pid:"):].strip()
        if not key.isdigit():
            return None
        want = int(key)
        match = next((w for w in wins if int(_field(w, "pid", 0) or 0) == want), None)
    elif spec.startswith("app_id:"):
        want = spec[len("app_id:"):].strip()
        if not want:
            return None
        matches = [w for w in wins if str(_field(w, "app_id", "") or "") == want]
        match = next((w for w in matches if _field(w, "is_focused", False)),
                     matches[0] if matches else None)
    else:
        key = spec[len("id:"):].strip() if spec.startswith("id:") else spec
        if not key.isdigit():
            return None
        want = int(key)
        match = next((w for w in wins if int(_field(w, "id", 0) or 0) == want), None)

    return _as_focused(match) if match is not None else None


def deliver_to_spec(spec: str, text: str, cfg) -> ActionResult:
    """Resolve ``spec`` and type ``text`` into that window.

    Returns ``ok=False`` (never raises) when the spec matches no window, so the
    CLI can report ``{ok, detail}`` and keep the pending record for a retry.
    """
    target = resolve_target(spec)
    if target is None:
        return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                            f"no window matched {spec!r}")
    return _deliver_dictation(text, target, cfg)


__all__ = [
    "_DICTATION_FALLBACK",
    "_DICTATION_FALLBACK_NOCLIP",
    "_capture_dictation_target",
    "_still_focused",
    "_refocus",
    "_type_dictation",
    "_deliver_dictation",
    "_copy_to_clipboard",
    "pending_path",
    "write_pending",
    "read_pending",
    "clear_pending",
    "resolve_target",
    "deliver_to_spec",
]
