"""Clipboard read via wl-clipboard (`wl-paste`)."""
from __future__ import annotations

import subprocess

_TIMEOUT = 2.0

# Ask for text explicitly: when the clipboard holds an image, wl-paste then
# exits non-zero instead of emitting PNG bytes.
_COMMANDS: tuple = (
    ["wl-paste", "--no-newline", "--type", "text"],
    ["wl-paste", "--type", "text"],
)


def get_clipboard() -> str:
    """Return the current Wayland clipboard text, or "" if none/unreadable.

    Uses `wl-paste --no-newline` so multi-line selections keep their newlines.
    Never raises; a non-text selection simply yields "".
    """
    for args in _COMMANDS:
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


__all__ = ["get_clipboard"]
