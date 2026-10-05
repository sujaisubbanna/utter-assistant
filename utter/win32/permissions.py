"""Advisory Windows microphone-privacy status + a Settings deep link.

Windows has no permission *prompt* API like macOS TCC; a user (or an MDM) grants
microphone access through Settings, or the packaged-app privacy consent store.
This module only **reports** the best-known state and offers the ``ms-settings:``
deep link. It is advisory: the OS still enforces the real decision, and nothing
here ever blocks or prompts.

Public API mirrors :mod:`utter.macos.permissions`::

    PERMISSIONS                ordered table (id, label, why)
    check(name)                -> "granted" | "denied" | "not_determined" | "unknown"
    request(name)              -> same as check (no prompt on Windows)
    status_all(request=False)  -> dict (also written to STATE_FILE)
    settings_url(name)         -> "ms-settings:privacy-microphone"

``winreg``/``win32*`` are imported lazily; on Linux every check returns
``"unknown"``. Pure helpers are unit-tested there.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List

from utter import platform

logger = logging.getLogger(__name__)

GRANTED = "granted"
DENIED = "denied"
NOT_DETERMINED = "not_determined"
UNKNOWN = "unknown"

_CONSENT_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion"
    r"\CapabilityAccessManager\ConsentStore\microphone"
)
_SETTINGS_URI = "ms-settings:privacy-microphone"

# Order matters: this is the order an onboarding screen walks through.
PERMISSIONS: List[Dict[str, str]] = [
    {"id": "microphone", "pane": "privacy-microphone",
     "label": "Microphone", "why": "Hear you while a push-to-talk key is held."},
]

PERMISSION_IDS = [p["id"] for p in PERMISSIONS]


def settings_url(name: str) -> str:
    """Deep link into Windows Settings -> Privacy for ``name``."""
    for p in PERMISSIONS:
        if p["id"] == name:
            return f"ms-settings:{p['pane']}"
    raise KeyError(name)


def state_file() -> Path:
    """Where the daemon publishes the last known status (advisory)."""
    override = os.environ.get("UTTER_PERMISSIONS_FILE")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "utter" / "permissions.json"


def _consent_status() -> str:
    """Read the microphone consent store. Best-effort; ``unknown`` on failure."""
    if not platform.is_windows():
        return UNKNOWN
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return UNKNOWN

    # HKCU wins over HKLM; within a hive, the global "Value" is the clearest
    # signal (per-exe values live under the NonPackaged subkey).
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, _CONSENT_PATH) as key:
                value, _ = winreg.QueryValueEx(key, "Value")
        except OSError:
            continue
        text = str(value or "").strip().casefold()
        if text == "allow":
            return GRANTED
        if text == "deny":
            return DENIED
        if text in ("prompt", "promptifneeded"):
            return NOT_DETERMINED
    return UNKNOWN


_CHECKS = {
    "microphone": _consent_status,
}


def _probe(name: str, request: bool) -> str:
    if name not in _CHECKS:
        raise KeyError(name)
    if not platform.is_windows():
        return UNKNOWN
    try:
        return _CHECKS[name]()
    except Exception as exc:  # noqa: BLE001 - a probe must never crash the daemon
        logger.debug("permission probe %s failed: %s", name, exc)
        return UNKNOWN


def check(name: str) -> str:
    return _probe(name, request=False)


def request(name: str) -> str:
    """Windows offers no prompt API: report the current status (advisory)."""
    return _probe(name, request=True)


def status_all(request: bool = False, names=None, write: bool = True) -> dict:
    """Status of every permission (or ``names``), published to :func:`state_file`."""
    wanted = list(names) if names else PERMISSION_IDS
    items = []
    for p in PERMISSIONS:
        if p["id"] not in wanted:
            continue
        items.append({
            "id": p["id"], "label": p["label"], "why": p["why"],
            "status": _probe(p["id"], request), "settings_url": settings_url(p["id"]),
        })
    doc = {
        "ok": True,
        "platform": platform.name(),
        "process": os.environ.get("UTTER_PERMISSIONS_PROCESS") or _executable(),
        "advisory": True,
        "all_granted": all(i["status"] == GRANTED for i in items) and bool(items),
        "permissions": items,
        "ts": time.time(),
    }
    if write:
        _write_state(doc)
    return doc


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
