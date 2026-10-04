#!/usr/bin/env python3
"""Unit checks for the M3 decision-head probe.

Proves ``_decision_head_state`` distinguishes a real OpenAI-style head
(200 + a non-empty models list) from a foreign service on the port (404, or an
empty list) and from a closed port — and that only "ready" makes an empty plan a
failure. This keeps the M3 skip narrow instead of a blanket skip.

Runs hermetically on a throwaway local HTTP stub; never touches :8001.

Usage::

    .venv-agent/bin/python tests/m3/test_decision_head_probe.py
"""
from __future__ import annotations

import http.server
import contextlib
import io
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(HERE))

import verify_m3  # noqa: E402
from _harness.report import Report  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves ``/v1/models`` in one of three shapes, selected by ``mode``."""

    mode = "ready"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if not self.path.endswith("/models"):
            self._send(404, {"detail": "Not Found"})
        elif _Handler.mode == "ready":
            self._send(200, {"object": "list", "data": [{"id": "qwen3-4b"}]})
        elif _Handler.mode == "empty":
            self._send(200, {"object": "list", "data": []})
        else:
            self._send(404, {"detail": "Not Found"})

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:  # noqa: A002 - stdlib signature
        pass


class _StubServer(http.server.ThreadingHTTPServer):
    """Starts on an ephemeral loopback port so tests never touch :8001."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    def __enter__(self) -> "_StubServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.shutdown()
        self.server_close()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])  # released on close -> refused


class _EmptyClient:
    """Minimal FramingClient stand-in returning an empty command result."""

    def request(self, _method, _params, timeout=None):
        return {"results": []}


def _check_quietly(rep: Report) -> None:
    """Run ``check_decision_head`` without its report output polluting the log."""
    with contextlib.redirect_stdout(io.StringIO()):
        verify_m3.check_decision_head(_EmptyClient(), rep, plugin_healthy=True)


class DecisionHeadStateTest(unittest.TestCase):
    def test_ready_head_is_asserted_not_skipped(self):
        _Handler.mode = "ready"
        with _StubServer() as srv, \
                patch.object(verify_m3, "_decision_head_url", return_value=srv.base_url):
            self.assertEqual(verify_m3._decision_head_state(srv.base_url), "ready")
            rep = Report()
            _check_quietly(rep)
        self.assertEqual(len(rep.failed), 1)  # empty plan is a real failure
        self.assertEqual(rep.skips, [])

    def test_foreign_404_head_is_skipped(self):
        _Handler.mode = "foreign"
        with _StubServer() as srv, \
                patch.object(verify_m3, "_decision_head_url", return_value=srv.base_url):
            self.assertEqual(verify_m3._decision_head_state(srv.base_url), "foreign")
            rep = Report()
            _check_quietly(rep)
        self.assertEqual(rep.failed, [])
        self.assertEqual(len(rep.skips), 1)

    def test_empty_model_list_is_foreign(self):
        _Handler.mode = "empty"
        with _StubServer() as srv:
            self.assertEqual(verify_m3._decision_head_state(srv.base_url), "foreign")

    def test_closed_port_is_offline(self):
        url = f"http://127.0.0.1:{_closed_port()}/v1"
        self.assertEqual(verify_m3._decision_head_state(url), "offline")

    def test_offline_head_is_skipped(self):
        url = f"http://127.0.0.1:{_closed_port()}/v1"
        with patch.object(verify_m3, "_decision_head_url", return_value=url):
            rep = Report()
            _check_quietly(rep)
        self.assertEqual(rep.failed, [])
        self.assertEqual(len(rep.skips), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
