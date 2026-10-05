"""Best-effort per-monitor DPI awareness for the Win32 capture/input backends.

A DPI-unaware process is shown *virtualised* (logical) coordinates by Windows,
while ``mss`` and the pointer APIs work in *physical* pixels. Making the process
per-monitor-DPI-aware keeps screenshots, window rects and pointer coordinates in
one consistent physical space, so a scaled display does not shift grounding.

This is a **best-effort optimisation, not a correctness requirement**: every
failure is swallowed, and on a non-Windows host (or an older Windows without the
API) it is a no-op returning ``False``. That keeps the modules importable and
the Linux/macOS test suite runnable.

Constants:
    ``DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`` (``-4``) — Windows 10 1607+
    ``PROCESS_PER_MONITOR_DPI_AWARE`` (``2``)             — Windows 8.1+

The process-level call only works once; a later call returns
``ERROR_ACCESS_DENIED`` (``E_ACCESSDENIED`` below), which also means awareness
is already set — for example by an application manifest — and is treated as
success.
"""
from __future__ import annotations

import logging

from utter import platform

logger = logging.getLogger(__name__)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (user32, Win10 1607+).
_PER_MONITOR_AWARE_V2 = -4
# PROCESS_PER_MONITOR_DPI_AWARE (shcore, Win8.1+).
_PROCESS_PER_MONITOR_DPI_AWARE = 2
# HRESULT 0x80070005 as a signed 32-bit int: "access denied" => already set.
_E_ACCESS_DENIED = -2147024891

# The call is process-wide and idempotent: once it succeeds there is no point
# trying again on every capture/window lookup.
_DONE = False


def ensure_dpi_aware() -> bool:
    """Make this process per-monitor DPI-aware once.

    Returns ``True`` when awareness is (or was) set, ``False`` on a non-Windows
    host or when no API was available. Never raises.
    """
    global _DONE
    if _DONE:
        return True
    if not platform.is_windows():
        return False

    import ctypes

    # ``ctypes.WinDLL`` only exists on Windows; ``getattr`` also covers a test
    # that forces ``UTTER_PLATFORM=windows`` while running on Linux.
    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        return False

    ok = False

    try:
        user32 = win_dll("user32", use_last_error=True)
    except OSError as exc:  # pragma: no cover - real Windows only
        logger.debug("could not load user32 for DPI awareness: %s", exc)
        return False

    # Preferred: per-monitor v2 (correct for per-monitor scaling).
    try:
        set_ctx = user32.SetProcessDpiAwarenessContext
        set_ctx.argtypes = [ctypes.c_void_p]
        set_ctx.restype = ctypes.c_int
        if set_ctx(ctypes.c_void_p(_PER_MONITOR_AWARE_V2)):
            ok = True
    except (AttributeError, OSError) as exc:  # pragma: no cover - older Windows
        logger.debug("SetProcessDpiAwarenessContext unavailable: %s", exc)

    # Windows Vista fallback: system-DPI aware.
    if not ok:
        try:
            set_aware = user32.SetProcessDPIAware
            set_aware.restype = ctypes.c_int
            if set_aware():
                ok = True
        except (AttributeError, OSError) as exc:  # pragma: no cover
            logger.debug("SetProcessDPIAware unavailable: %s", exc)

    # Windows 8.1 fallback: per-monitor aware via shcore.
    if not ok:
        try:
            shcore = win_dll("shcore", use_last_error=True)
            set_awareness = shcore.SetProcessDpiAwareness
            set_awareness.argtypes = [ctypes.c_int]
            set_awareness.restype = ctypes.c_long
            if set_awareness(_PROCESS_PER_MONITOR_DPI_AWARE) in (0, _E_ACCESS_DENIED):
                ok = True
        except (AttributeError, OSError) as exc:  # pragma: no cover
            logger.debug("SetProcessDpiAwareness unavailable: %s", exc)

    if ok:
        _DONE = True
    return ok


__all__ = ["ensure_dpi_aware"]
