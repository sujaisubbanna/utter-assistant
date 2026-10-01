#!/usr/bin/env python3
"""Shared ``python -m runner`` subprocess helper for the protocol test suites.

Extracted from ``tests/conformance/run.py``, ``tests/m3/verify_m3.py`` and
``scripts/m0_spike.py``. Starts the runner, waits for its socket to accept a
connection, hands out a :class:`FramingClient`, and tears it down.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# framing_client lives in tests/conformance and is the independent client.
_CONF_DIR = REPO / "tests" / "conformance"
if str(_CONF_DIR) not in sys.path:
    sys.path.insert(0, str(_CONF_DIR))

from framing_client import FramingClient  # noqa: E402


class Runner:
    """Supervise the runner as a child process for the duration of a test."""

    def __init__(self, *, config: Path, sock_path: str, log_dir: Path,
                 timeout: float = 30.0, log_name: str = "runner.log",
                 env: dict | None = None, stop_timeout: float = 5.0,
                 tail_lines: int = 40, cwd: Path | None = None,
                 python: str | None = None) -> None:
        self.config = config
        self.sock_path = sock_path
        self.log_dir = Path(log_dir)
        self.timeout = timeout
        self.log_name = log_name
        self.extra_env = dict(env or {})
        self.stop_timeout = stop_timeout
        self.tail_lines = tail_lines
        self.cwd = Path(cwd) if cwd is not None else REPO
        self.python = python or sys.executable
        self.proc: subprocess.Popen | None = None
        self.log_path = self.log_dir / log_name
        self._log = None

    def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "wb")
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.update(self.extra_env)
        self.proc = subprocess.Popen(
            [self.python, "-m", "runner", "--config", str(self.config),
             "--socket", self.sock_path],
            cwd=str(self.cwd),
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            env=env,
        )

    def wait_ready(self) -> bool:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            if os.path.exists(self.sock_path):
                try:
                    FramingClient.connect_unix(self.sock_path, timeout=2.0).close()
                    return True
                except OSError:
                    pass
            time.sleep(0.1)
        return False

    def connect(self, **kw) -> FramingClient:
        return FramingClient.connect_unix(self.sock_path, timeout=self.timeout, **kw)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self._log is not None:
            self._log.close()

    def tail_log(self, n: int | None = None) -> str:
        try:
            lines = self.log_path.read_text(errors="replace").splitlines()
            return "\n".join(lines[-(n or self.tail_lines):])
        except OSError:
            return "(no runner log)"
