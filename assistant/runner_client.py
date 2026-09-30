"""Tiny stdlib JSON-RPC 2.0 client for the runner unix socket.

Independent of the conformance suite (which lives under ``tests/``); this is the
client the ``assistant`` CLI ships with.
"""
from __future__ import annotations

import json
import select
import socket
import time
from typing import Any, Optional

_HEADER_SEP = b"\r\n\r\n"


class RunnerError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"runner error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def encode_frame(obj: Any) -> bytes:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


class RunnerClient:
    def __init__(self, path: str, timeout: float = 10.0):
        self.path = path
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()
        self._next_id = 0

    # -- lifecycle -------------------------------------------------------- #
    def connect(self) -> "RunnerClient":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.path)
        self._sock = sock
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> "RunnerClient":
        return self.connect()

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- framing ---------------------------------------------------------- #
    def _try_parse(self) -> Any:
        idx = self._buf.find(_HEADER_SEP)
        if idx < 0:
            return None
        header = bytes(self._buf[:idx]).decode("ascii", "replace")
        length: Optional[int] = None
        for line in header.replace("\r\n", "\n").split("\n"):
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() == "content-length":
                length = int(value.strip())
        if length is None:
            raise RunnerError(-32700, f"frame missing Content-Length: {header!r}")
        start = idx + len(_HEADER_SEP)
        if len(self._buf) < start + length:
            return None
        body = bytes(self._buf[start:start + length])
        del self._buf[:start + length]
        return json.loads(body.decode("utf-8"))

    def _recv_message(self, timeout: float) -> Any:
        deadline = time.monotonic() + timeout
        while True:
            parsed = self._try_parse()
            if parsed is not None:
                return parsed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for a frame from {self.path}")
            assert self._sock is not None
            ready, _, _ = select.select([self._sock], [], [], remaining)
            if not ready:
                raise TimeoutError(f"timed out waiting for a frame from {self.path}")
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError(f"runner closed the connection ({self.path})")
            self._buf.extend(chunk)

    # -- rpc -------------------------------------------------------------- #
    def call(self, method: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        if self._sock is None:
            raise RunnerError(-32000, "client is not connected")
        self._next_id += 1
        rid = self._next_id
        self._sock.sendall(encode_frame(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        ))
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"request {method!r} timed out")
            msg = self._recv_message(remaining)
            if not isinstance(msg, dict) or msg.get("id") != rid or "method" in msg:
                continue
            if "error" in msg:
                err = msg.get("error") or {}
                raise RunnerError(int(err.get("code", -32000)),
                                  str(err.get("message", "")), err.get("data"))
            return msg.get("result")
