#!/usr/bin/env python3
"""Daemon CLI: the native hotkey path, and the removed ``--bridge`` mode.

Guards against the vocalinux bridge creeping back into the daemon surface:
``--bridge`` must be rejected, and the daemon must dispatch to the native
evdev hotkey loop on Linux.

Usage::

    .venv-agent/bin/python tests/voice/test_daemon_cli.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Deterministic: exercise the Linux dispatch even when the suite runs elsewhere.
os.environ["UTTER_PLATFORM"] = "linux"

import utter.daemon as daemon  # noqa: E402

ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


# -- --bridge is gone ---------------------------------------------------------
check("Utter.run_bridge removed", not hasattr(daemon.Utter, "run_bridge"))
check("_assistant_context removed", not hasattr(daemon, "_assistant_context"))

stderr = io.StringIO()
with contextlib.redirect_stderr(stderr):
    try:
        daemon.main(["--bridge"])
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
check("--bridge is rejected", code not in (0, None))
check("--bridge named in the usage error", "--bridge" in stderr.getvalue())

stdout = io.StringIO()
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
    try:
        daemon.main(["--help"])
    except SystemExit:
        pass
check("--help does not advertise --bridge", "--bridge" not in stdout.getvalue())

# -- daemon still starts in the native hotkey mode ---------------------------
calls: list = []
saved_setup, saved_hotkey, saved_macos = (
    daemon.Utter.setup,
    daemon.Utter.run_hotkey,
    daemon.Utter.run_macos,
)
daemon.Utter.setup = lambda self: None
daemon.Utter.run_hotkey = lambda self: calls.append("hotkey")
daemon.Utter.run_macos = lambda self: calls.append("macos")
try:
    rc = daemon.main([])
finally:
    daemon.Utter.setup = saved_setup
    daemon.Utter.run_hotkey = saved_hotkey
    daemon.Utter.run_macos = saved_macos

check("main() returns 0", rc == 0)
check("Linux dispatches to run_hotkey", calls == ["hotkey"])

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
