"""Clipboard on macOS via ``pbpaste`` / ``pbcopy``. Never raises."""
from __future__ import annotations

import subprocess

_TIMEOUT = 2.0

# ``pbpaste`` prints text only; an image-only pasteboard yields empty output.
_COMMANDS: tuple = (["pbpaste", "-Prefer", "txt"], ["pbpaste"])


def get_clipboard() -> str:
    for args in _COMMANDS:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, errors="replace",
                                  timeout=_TIMEOUT)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if proc.returncode == 0:
            return proc.stdout
    return ""


def set_clipboard(text: str) -> bool:
    try:
        proc = subprocess.run(["pbcopy"], input=text or "", text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return proc.returncode == 0


__all__ = ["get_clipboard", "set_clipboard"]
