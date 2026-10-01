#!/usr/bin/env python3
"""Shared runner TOML fixtures for the protocol test suites.

The fake_py/fake_rs plugin tables and the generated runner configs were
duplicated in ``tests/conformance/run.py`` and ``scripts/m0_spike.py``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAKE_PY = REPO / "plugins" / "fake_py" / "plugin.py"
FAKE_RS = REPO / "plugins" / "fake_rs" / "target" / "release" / "fake_rs"

#: action.terminal stays off unless a fixture opts in (TRUST.md §4).
DEFAULT_POLICY = 'disabled_ops = ["terminal"]'


def plugin_blocks(*, python: str | None = None) -> str:
    """The fake_py (bundle) + fake_rs (action) ``[[plugin]]`` tables."""
    py_entry = json.dumps([python or sys.executable, str(FAKE_PY)])
    rs_entry = json.dumps([str(FAKE_RS)])
    return f"""[[plugin]]
id = "fake_py"
kind = "bundle"
runtime = "subprocess"
transport = "stdio"
entrypoint = {py_entry}
provides = ["action.open_url@1", "action.terminal@1", "context.live@1", "fs.tmp@1", "host.fd.pass@1", "host.audio.ringbuffer@1", "experimental/fake_py@1"]
requires = ["context.live@1", "fs.tmp@1"]
permissions = ["filesystem.read", "filesystem.write", "network"]

[[plugin]]
id = "fake_rs"
kind = "action"
runtime = "subprocess"
transport = "stdio"
entrypoint = {rs_entry}
provides = ["action.open_url@1", "experimental/fake_rs@1"]
requires = ["context.live@1"]
permissions = ["network"]
"""


def runner_config(*, socket: str, policy: str | None = DEFAULT_POLICY,
                  rpc_timeout_ms: int = 10000, confirm_timeout_ms: int | None = None,
                  python: str | None = None,
                  comment: str = "GENERATED — do not edit.") -> str:
    """Assemble a runner config around the fake plugins.

    ``socket``/``policy`` may be multi-line (comments included), matching the
    hand-written probes they replace.
    """
    lines = [f"# {comment}", "", "[runner]", f"rpc_timeout_ms = {rpc_timeout_ms}"]
    if confirm_timeout_ms is not None:
        lines.append(f"confirm_timeout_ms = {confirm_timeout_ms}")
    lines += ["", "[socket]", socket, "", plugin_blocks(python=python).rstrip("\n")]
    if policy is not None:
        lines += ["", "[policy]", policy]
    return "\n".join(lines) + "\n"
