"""macOS privacy permissions (TCC) the assistant needs, with status + prompts.

macOS grants permissions per *process*; for a non-bundled interpreter that is
the python binary launchd (or your terminal) starts. The settings app therefore
never asks for itself: it runs this module through the daemon's own python
(``python -m assistant macos-permissions``) so the prompts attach to the right
binary, and the daemon re-checks everything at startup.

Public API:
    PERMISSIONS                       ordered table (id, settings pane, why)
    check(name)  -> "granted" | "denied" | "not_determined" | "unknown"
    request(name) -> same, after triggering the system prompt where possible
    status_all(request=False) -> dict  (also written to STATE_FILE)
    settings_url(name) -> "x-apple.systempreferences:..." deep link

Everything PyObjC / ctypes is imported lazily; on Linux every check returns
``"unknown"`` and nothing is prompted. Pure helpers are unit-tested there.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

GRANTED = "granted"
DENIED = "denied"
NOT_DETERMINED = "not_determined"
UNKNOWN = "unknown"

_SECURITY_PANE = "x-apple.systempreferences:com.apple.preference.security"

# Order matters: this is the order the onboarding screen walks through.
PERMISSIONS: List[Dict[str, str]] = [
    {"id": "microphone", "pane": "Privacy_Microphone",
     "label": "Microphone", "why": "Hear you while a push-to-talk key is held."},
    {"id": "speech_recognition", "pane": "Privacy_SpeechRecognition",
     "label": "Speech Recognition", "why": "Turn your voice into text with Apple's on-device recogniser."},
    {"id": "input_monitoring", "pane": "Privacy_ListenEvent",
     "label": "Input Monitoring", "why": "Notice when you press and release the push-to-talk keys."},
    {"id": "accessibility", "pane": "Privacy_Accessibility",
     "label": "Accessibility", "why": "Type dictated text, press shortcuts and read the focused window's title."},
    {"id": "screen_recording", "pane": "Privacy_ScreenCapture",
     "label": "Screen Recording", "why": "Take a screenshot when an action needs to find something on screen."},
]

PERMISSION_IDS = [p["id"] for p in PERMISSIONS]

_PROMPT_TIMEOUT_S = 20.0


def settings_url(name: str) -> str:
    """Deep link into System Settings -> Privacy & Security for ``name``."""
    for p in PERMISSIONS:
        if p["id"] == name:
            return f"{_SECURITY_PANE}?{p['pane']}"
    raise KeyError(name)


def state_file() -> Path:
    """Where the daemon publishes the last known status (read by the settings app)."""
    override = os.environ.get("UTTER_PERMISSIONS_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "utter" / "permissions.json"


# -- individual checks ---------------------------------------------------------

def _microphone(request: bool) -> str:
    try:
        import AVFoundation  # type: ignore[import-not-found]
    except ImportError:
        return UNKNOWN
    media = getattr(AVFoundation, "AVMediaTypeAudio", "soun")
    status = int(AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(media))
    table = {0: NOT_DETERMINED, 1: DENIED, 2: DENIED, 3: GRANTED}
    if status == 0 and request:
        done = threading.Event()
        out = {"ok": False}

        def _cb(granted):
            out["ok"] = bool(granted)
            done.set()

        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(media, _cb)
        done.wait(_PROMPT_TIMEOUT_S)
        return GRANTED if out["ok"] else DENIED if done.is_set() else NOT_DETERMINED
    return table.get(status, UNKNOWN)


def _speech(request: bool) -> str:
    try:
        import Speech  # type: ignore[import-not-found]
    except ImportError:
        return UNKNOWN
    status = int(Speech.SFSpeechRecognizer.authorizationStatus())
    table = {0: NOT_DETERMINED, 1: DENIED, 2: DENIED, 3: GRANTED}
    if status == 0 and request:
        done = threading.Event()
        out = {"status": 0}

        def _cb(new_status):
            out["status"] = int(new_status)
            done.set()

        Speech.SFSpeechRecognizer.requestAuthorization_(_cb)
        done.wait(_PROMPT_TIMEOUT_S)
        return table.get(out["status"], NOT_DETERMINED)
    return table.get(status, UNKNOWN)


def _input_monitoring(request: bool) -> str:
    """``IOHIDCheckAccess`` / ``IOHIDRequestAccess`` (IOKit, macOS 10.15+) via ctypes."""
    try:
        import ctypes
        import ctypes.util

        path = ctypes.util.find_library("IOKit") or "/System/Library/Frameworks/IOKit.framework/IOKit"
        iokit = ctypes.CDLL(path)
        iokit.IOHIDCheckAccess.restype = ctypes.c_uint32
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
    except (OSError, AttributeError):
        return UNKNOWN
    listen_event = 1  # kIOHIDRequestTypeListenEvent
    table = {0: GRANTED, 1: DENIED, 2: NOT_DETERMINED}
    status = table.get(int(iokit.IOHIDCheckAccess(listen_event)), UNKNOWN)
    if status != GRANTED and request:
        granted = bool(iokit.IOHIDRequestAccess(listen_event))
        if granted:
            return GRANTED
        status = table.get(int(iokit.IOHIDCheckAccess(listen_event)), status)
    return status


def _accessibility(request: bool) -> str:
    try:
        import ApplicationServices as AS  # type: ignore[import-not-found]
    except ImportError:
        return UNKNOWN
    try:
        if request:
            opts = {AS.kAXTrustedCheckOptionPrompt: True}
            trusted = bool(AS.AXIsProcessTrustedWithOptions(opts))
        else:
            trusted = bool(AS.AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return UNKNOWN
    # AX has no "not determined": it is either trusted or not.
    return GRANTED if trusted else DENIED


def _screen_recording(request: bool) -> str:
    try:
        import Quartz  # type: ignore[import-not-found]
    except ImportError:
        return UNKNOWN
    try:
        if request and not Quartz.CGPreflightScreenCaptureAccess():
            Quartz.CGRequestScreenCaptureAccess()
        return GRANTED if Quartz.CGPreflightScreenCaptureAccess() else DENIED
    except Exception:  # noqa: BLE001
        return UNKNOWN


_CHECKS = {
    "microphone": _microphone,
    "speech_recognition": _speech,
    "input_monitoring": _input_monitoring,
    "accessibility": _accessibility,
    "screen_recording": _screen_recording,
}


def _probe(name: str, request: bool) -> str:
    from utter.platform import is_macos

    if name not in _CHECKS:
        raise KeyError(name)
    if not is_macos():
        return UNKNOWN
    try:
        return _CHECKS[name](request)
    except Exception as exc:  # noqa: BLE001 - a probe must never crash the daemon
        logger.debug("permission probe %s failed: %s", name, exc)
        return UNKNOWN


def check(name: str) -> str:
    return _probe(name, request=False)


def request(name: str) -> str:
    """Trigger the system prompt (where macOS offers one) and return the result."""
    return _probe(name, request=True)


def status_all(request: bool = False, names=None, write: bool = True) -> dict:
    """Status of every permission (or ``names``), published to :func:`state_file`."""
    wanted = list(names) if names else PERMISSION_IDS
    items = []
    for p in PERMISSIONS:
        if p["id"] not in wanted:
            continue
        status = _probe(p["id"], request)
        items.append({"id": p["id"], "label": p["label"], "why": p["why"],
                      "status": status, "settings_url": settings_url(p["id"])})
    doc = {
        "ok": True,
        "platform": _platform_name(),
        "process": os.environ.get("UTTER_PERMISSIONS_PROCESS") or _executable(),
        "all_granted": all(i["status"] == GRANTED for i in items) and bool(items),
        "permissions": items,
        "ts": time.time(),
    }
    if write:
        _write_state(doc)
    return doc


def _platform_name() -> str:
    from utter.platform import name

    return name()


def _executable() -> str:
    import sys

    return sys.executable


def _write_state(doc: dict) -> None:
    try:
        path = state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2))
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("could not write %s: %s", state_file(), exc)


def read_state() -> dict | None:
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return None


__all__ = ["PERMISSIONS", "PERMISSION_IDS", "GRANTED", "DENIED", "NOT_DETERMINED", "UNKNOWN",
           "check", "request", "status_all", "settings_url", "state_file", "read_state"]
