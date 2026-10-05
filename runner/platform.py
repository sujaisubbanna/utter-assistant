"""Runner transport selection (stdlib only, never depends on ``utter``).

Unix keeps AF_UNIX + ``SO_PEERCRED``/``/proc`` unchanged; Windows (and the
Linux test override) uses loopback TCP + a mandatory token. ``transport_kind``
is overrideable with ``UTTER_RUNNER_TRANSPORT=unix|tcp`` so the TCP path can be
exercised on Linux without Windows.
"""

from __future__ import annotations

import os
import sys

UNIX = "unix"
TCP = "tcp"

_VALID = (UNIX, TCP)
_WINDOWS_PLATFORMS = ("win32", "cygwin", "msys")
_PLATFORM_ENV = "UTTER_PLATFORM"
_TRANSPORT_ENV = "UTTER_RUNNER_TRANSPORT"


def is_windows() -> bool:
    """True on Windows, honouring ``UTTER_PLATFORM`` for hermetic tests."""
    forced = (os.environ.get(_PLATFORM_ENV) or "").strip().lower()
    if forced in ("windows", "win", *_WINDOWS_PLATFORMS):
        return True
    if forced:
        return False
    return sys.platform in _WINDOWS_PLATFORMS


def transport_kind() -> str:
    """``"unix"`` or ``"tcp"``: env override, else platform default.

    The env override lets Linux tests exercise the Windows TCP path unchanged.
    """
    override = (os.environ.get(_TRANSPORT_ENV) or "").strip().lower()
    if override in _VALID:
        return override
    return TCP if is_windows() else UNIX


def resolve_transport(explicit: str = "") -> str:
    """Config-level ``socket_transport`` override, then env, then platform."""
    value = (explicit or "").strip().lower()
    if value in _VALID:
        return value
    return transport_kind()


__all__ = ["UNIX", "TCP", "is_windows", "transport_kind", "resolve_transport"]
