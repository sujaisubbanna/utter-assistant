"""User notifications on macOS.

Uses ``terminal-notifier`` when installed (clickable, grouped), otherwise
``osascript -e 'display notification ...'``. Never raises, never blocks.
"""
from __future__ import annotations

import shutil
import subprocess

_TIMEOUT = 5.0


def applescript_notification(message: str, title: str = "Utter", subtitle: str = "") -> str:
    def esc(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if subtitle:
        script += f' subtitle "{esc(subtitle)}"'
    return script


def notify(message: str, title: str = "Utter", subtitle: str = "") -> bool:
    message = (message or "").strip()
    if not message:
        return False
    try:
        if shutil.which("terminal-notifier"):
            argv = ["terminal-notifier", "-title", title, "-message", message, "-group", "utter"]
            if subtitle:
                argv += ["-subtitle", subtitle]
        else:
            argv = ["osascript", "-e", applescript_notification(message, title, subtitle)]
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


__all__ = ["notify", "applescript_notification"]
