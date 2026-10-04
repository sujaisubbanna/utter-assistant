"""Clipboard read via wl-clipboard (`wl-paste`); `pbpaste` on macOS."""
from __future__ import annotations

import subprocess

from utter import platform

_TIMEOUT = 2.0

# Ask for text explicitly: when the clipboard holds an image, wl-paste then
# exits non-zero instead of emitting PNG bytes.
_COMMANDS: tuple = (
    ["wl-paste", "--no-newline", "--type", "text"],
    ["wl-paste", "--type", "text"],
)
_COMMANDS_MACOS: tuple = (["pbpaste", "-Prefer", "txt"], ["pbpaste"])


def commands_for(platform_name: str) -> tuple:
    """The paste commands tried on ``platform_name`` (pure; unit-tested)."""
    return _COMMANDS_MACOS if platform_name == platform.MACOS else _COMMANDS


# KDE Plasma: klipper over D-Bus first, wl-paste second. Which one actually
# works is remembered per process so a missing klipper costs one failed call.
_KWIN_WORKING: str | None = None


def reset_cache() -> None:
    global _KWIN_WORKING
    _KWIN_WORKING = None


def kwin_order(preference: str = "auto") -> tuple:
    """Clipboard sources tried on KWin for ``[kwin] clipboard`` (pure; unit-tested)."""
    pref = (preference or "auto").lower()
    if pref in ("klipper", "dbus"):
        return ("klipper",)
    if pref in ("wl-clipboard", "wl-paste", "wl_clipboard"):
        return ("wl-paste",)
    return ("klipper", "wl-paste")


def _klipper_text() -> str | None:
    from utter.context.backends import dbus, kwin

    reply = dbus.call(kwin.call_klipper_get(), timeout=_TIMEOUT)
    if not reply.ok or reply.value is None:
        return None
    return str(reply.value)


def _get_clipboard_kwin() -> str:
    global _KWIN_WORKING
    from utter.context.backends import kwin

    pref = str(getattr(kwin.cfg(), "clipboard", "auto") or "auto")
    order = (_KWIN_WORKING,) if _KWIN_WORKING else kwin_order(pref)
    for source in order:
        if source == "klipper":
            text = _klipper_text()
            if text is not None:
                _KWIN_WORKING = "klipper"
                return text
        else:
            text = _run_commands(_COMMANDS)
            if text is not None:
                _KWIN_WORKING = "wl-paste"
                return text
    return ""


def _run_commands(commands) -> str | None:
    for args in commands:
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if proc.returncode == 0:
            return proc.stdout
    return None


def _on_kwin() -> bool:
    try:
        from utter.context import compositor

        return compositor.active_name() == compositor.KWIN
    except Exception:  # noqa: BLE001
        return False


def get_clipboard() -> str:
    """Return the current Wayland clipboard text, or "" if none/unreadable.

    Uses `wl-paste --no-newline` so multi-line selections keep their newlines.
    Never raises; a non-text selection simply yields "". On KDE Plasma klipper
    is asked first (``org.kde.klipper``), wl-paste is the fallback.
    """
    commands = _COMMANDS if _COMMANDS is not _LINUX_DEFAULT else commands_for(platform.name())
    if commands is _LINUX_DEFAULT and _on_kwin():
        return _get_clipboard_kwin()
    for args in commands:
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                errors="replace",  # never let stray bytes kill a command
                timeout=_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if proc.returncode == 0:
            return proc.stdout
    return ""


_LINUX_DEFAULT = _COMMANDS  # tests replace _COMMANDS directly; honour that


def set_clipboard(text: str) -> bool:
    """Copy ``text`` to the Wayland clipboard via ``wl-copy``. Never raises."""
    try:
        proc = subprocess.run(["wl-copy"], input=text or "", text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return proc.returncode == 0


__all__ = ["get_clipboard", "set_clipboard", "commands_for", "kwin_order", "reset_cache"]
