"""Zen/Firefox tab control via the WebDriver BiDi Remote Agent.

This module is intentionally thin: it shells out to ``scripts/zen_bidi.py``,
which runs inside the repo's ``.venv-agent`` (where ``websockets`` is
installed). That keeps this file importable from *any* interpreter, including
one that has no third-party deps.

Zen only exposes BiDi when started with ``--remote-debugging-port=9222``
(``scripts/install-zen-bidi-desktop.sh`` sets that up for the desktop entry).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Optional

PORT = int(os.environ.get("ZEN_BIDI_PORT", "9222"))

# repo root: this file is <root>/utter/browser/zen.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _REPO_ROOT / "scripts" / "zen_bidi.py"


def _agent_python() -> str:
    """Interpreter used to run the helper (the repo's .venv-agent)."""
    override = os.environ.get("UTTER_AGENT_PY")
    if override:
        return override
    return str(_REPO_ROOT / ".venv-agent" / "bin" / "python")


def _run(args: list[str]) -> Optional[str]:
    """Run the BiDi helper; return stdout on success, None on any failure."""
    cmd = [_agent_python(), str(_HELPER), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_up() -> bool:
    """Fast TCP probe of 127.0.0.1:PORT. No subprocess."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.4):
            return True
    except OSError:
        return False


def list_tabs() -> list[dict]:
    """All top-level Zen tabs; [] on any failure."""
    out = _run(["list"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def find_tab(substr: str) -> Optional[dict]:
    """First tab whose url or title contains *substr* (case-insensitive)."""
    out = _run(["find", str(substr)])
    if not out:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def activate(context: str) -> bool:
    """Focus the window and select the tab with *context* id."""
    return _run(["activate", str(context)]) is not None


def activate_match(substr: str) -> Optional[dict]:
    """Find and activate a tab in ONE BiDi session (context ids are not stable
    across sessions). Returns the activated tab dict, or None."""
    out = _run(["activate-match", str(substr)])
    if not out:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
