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


def get_clipboard() -> str:
    """Return the current Wayland clipboard text, or "" if none/unreadable.

    Uses `wl-paste --no-newline` so multi-line selections keep their newlines.
    Never raises; a non-text selection simply yields "".
    """
    commands = _COMMANDS if _COMMANDS is not _LINUX_DEFAULT else commands_for(platform.name())
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

__all__ = ["get_clipboard", "commands_for"]
