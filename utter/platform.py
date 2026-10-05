"""Host platform detection for utter.

Every platform-specific code path in the assistant sits behind this module so
the Linux (Wayland/niri) behaviour stays byte-for-byte identical when running
on Linux, and the macOS equivalents are picked only on Darwin.

Public API:
    name()        -> "linux" | "darwin" | "windows" | <sys.platform>
    is_linux()    -> bool
    is_macos()    -> bool
    is_windows()  -> bool
    has_module(n) -> bool   (import probe without importing into the caller)
    which(cmd)    -> str | None

Tests (and nothing else) may force a platform with ``UTTER_PLATFORM=darwin``;
the override is read on every call so a test can flip it without reloading.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys

LINUX = "linux"
MACOS = "darwin"
WINDOWS = "windows"

# ``sys.platform`` values that mean Windows. ``cygwin``/``msys`` are POSIX-ish
# Python runtimes on Windows; the assistant still needs the Windows seams there.
_WINDOWS_PLATFORMS = ("win32", "cygwin", "msys")

_ENV_OVERRIDE = "UTTER_PLATFORM"


def name() -> str:
    """Canonical platform name: ``"linux"``, ``"darwin"``, ``"windows"`` or ``sys.platform``."""
    forced = (os.environ.get(_ENV_OVERRIDE) or "").strip().lower()
    if forced in ("macos", "mac", "osx"):
        return MACOS
    if forced in ("windows", "win", *_WINDOWS_PLATFORMS):
        return WINDOWS
    if forced:
        return forced
    plat = sys.platform
    if plat.startswith("linux"):
        return LINUX
    if plat in _WINDOWS_PLATFORMS:
        return WINDOWS
    return plat


def is_linux() -> bool:
    return name() == LINUX


def is_macos() -> bool:
    return name() == MACOS


def is_windows() -> bool:
    return name() == WINDOWS


def has_module(module: str) -> bool:
    """True when ``module`` can be imported, without importing it here."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


__all__ = ["LINUX", "MACOS", "WINDOWS", "name", "is_linux", "is_macos", "is_windows",
           "has_module", "which"]
