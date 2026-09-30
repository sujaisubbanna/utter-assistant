#!/usr/bin/env python3
"""Minimal internal fake plugin for runner self-tests (router + action + stream).

Owned by ``runner/`` — independent of the conformance fakes under ``plugins/``.
Supports stdio (default) and unix-socket transports, plus a small lossy stream
emitter used to exercise the runner's stream relay.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from typing import Any, Optional
from urllib.parse import quote

PROTOCOL = "1.0"
ABI = 1
SITES = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
}

_WRITE_LOCK = threading.Lock()
_STREAMS: dict[str, dict] = {}
_STREAM_LOCK = threading.Lock()
_STREAM_SEQ = [0]


# --------------------------------------------------------------------------- #
# framing over an arbitrary binary file object
# --------------------------------------------------------------------------- #
def _read_message(stream: Any) -> Optional[Any]:
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
        if len(header) > 8192:
            raise ValueError("header too large")
    length: Optional[int] = None
    for line in header[:-4].split(b"\r\n"):
        name, sep, value = line.partition(b":")
        if sep and name.strip().lower() == b"content-length":
            length = int(value.strip())
    if length is None:
        raise ValueError("missing Content-Length")
    body = stream.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(stream: Any, obj: Any) -> None:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with _WRITE_LOCK:
        stream.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        stream.flush()


def _notify(stream: Any, method: str, params: Any) -> None:
    _write_message(stream, {"jsonrpc": "2.0", "method": method, "params": params})


# --------------------------------------------------------------------------- #
# methods
# --------------------------------------------------------------------------- #
def plan(params: dict) -> dict:
    utterance = str(params.get("utterance", "")).strip()
    low = utterance.lower()
    provenance = params.get("provenance", "user")
    if low.startswith("open "):
        target = low[5:].strip()
        url = SITES.get(target) or f"https://duckduckgo.com/?q={quote(target)}"
        return {"steps": [{"op": "ensure_url", "args": {"url": url}, "provenance": provenance}]}
    if low.startswith("run "):
        return {
            "steps": [{
                "op": "terminal",
                "args": {"command": utterance[4:].strip()},
                "provenance": provenance,
                "confirm": True,
            }]
        }
    return {"steps": []}


def handle(method: str, params: dict, kind: str) -> Any:
    if method == "protocol.hello":
        provides = (
            ["action.open_url@1", "action.terminal@1", "context.live@1"]
            if kind == "action"
            else []
        )
        return {
            "protocol": PROTOCOL,
            "abi": ABI,
            "plugin": {"name": f"runner-test-{kind}", "version": "0.1.0", "kind": kind},
            "transport": "stdio",
            "provides": provides,
            "requires": [],
            "permissions": [],
        }
    if method == "plugin.describe":
        methods = ["router.plan"] if kind == "router" else [
            "action.invoke", "action.capabilities",
            "stream.subscribe", "stream.stop", "context.snapshot",
        ]
        streams = [] if kind == "router" else ["test.frames"]
        return {"methods": methods, "streams": streams}
    if method == "plugin.health":
        return {"status": "ok", "detail": "runner test plugin"}
    if method == "router.plan":
        return plan(params)
    if method == "context.snapshot":
        return {"focused": {"app_id": "test", "title": "t"}, "source": "runner-test"}
    if method == "action.capabilities":
        return {"ops": [
            {"op": "ensure_url", "side_effect": "open_url", "needs_confirm": False},
            {"op": "open_url", "side_effect": "open_url", "needs_confirm": False},
            {"op": "terminal", "side_effect": "shell", "needs_confirm": True},
        ]}
    if method == "action.invoke":
        op = params.get("op")
        args = params.get("args") or {}
        detail = f"invoked {op} with {json.dumps(args, ensure_ascii=False)}"
        return {"ok": True, "op": op, "detail": detail, "provenance": params.get("provenance", "user")}
    if method == "stream.subscribe":
        _STREAM_SEQ[0] += 1
        sid = f"test-stream-{_STREAM_SEQ[0]}"
        with _STREAM_LOCK:
            _STREAMS[sid] = {"stop": False, "method": params.get("method") or "test.frames"}
        return {"stream_id": sid}
    if method == "stream.stop":
        sid = str(params.get("stream_id") or "")
        with _STREAM_LOCK:
            entry = _STREAMS.pop(sid, None)
        if entry is not None:
            entry["stop"] = True
        return {}
    raise ValueError(f"method not found: {method}")


def _emit(stream: Any, sid: str, params: dict) -> None:
    count = int(params.get("count") or 8)
    with _STREAM_LOCK:
        entry = _STREAMS.get(sid) or {"method": "test.frames", "stop": False}
    method = entry["method"]
    for i in range(1, count + 1):
        if entry.get("stop"):
            return
        try:
            _notify(stream, method, {"stream_id": sid, "seq": i, "data": {"n": i}})
        except OSError:
            return
        time.sleep(0.005)


def serve(read_stream: Any, write_stream: Any, kind: str) -> int:
    while True:
        msg = _read_message(read_stream)
        if msg is None:
            return 0
        if not isinstance(msg, dict):
            continue
        method = str(msg.get("method") or "")
        req_id = msg.get("id")
        raw_params = msg.get("params")
        params: dict = raw_params if isinstance(raw_params, dict) else {}
        if method == "$/cancel":
            continue
        if req_id is None:
            continue
        try:
            result = handle(method, params, kind)
            _write_message(write_stream, {"jsonrpc": "2.0", "id": req_id, "result": result})
            if method == "stream.subscribe" and isinstance(result, dict):
                sid = result.get("stream_id")
                threading.Thread(target=_emit, args=(write_stream, sid, params), daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            _write_message(write_stream, {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": str(exc)},
            })


# --------------------------------------------------------------------------- #
# transports
# --------------------------------------------------------------------------- #
def _connect_retry(path: str, timeout: float = 5.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(path)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
            time.sleep(0.05)
    raise OSError(f"could not connect to {path}: {last}")


def serve_socket_env(kind: str) -> int:
    path = os.environ.get("UTTER_PLUGIN_SOCKET")
    transport = os.environ.get("UTTER_PLUGIN_TRANSPORT", "listen")
    if not path:
        raise SystemExit("UTTER_PLUGIN_SOCKET not set")
    if transport == "connect":
        conn = _connect_retry(path)
    else:  # listen
        try:
            os.unlink(path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)
        srv.listen(1)
        conn, _ = srv.accept()
        srv.close()
    try:
        f = conn.makefile("rwb")
        return serve(f, f, kind)
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="runner internal test plugin")
    parser.add_argument("--kind", default="router", choices=["router", "action"])
    parser.add_argument("--socket-transport", action="store_true",
                        help="use UTTER_PLUGIN_SOCKET / UTTER_PLUGIN_TRANSPORT")
    args = parser.parse_args(argv)
    if args.socket_transport:
        return serve_socket_env(args.kind)
    return serve(sys.stdin.buffer, sys.stdout.buffer, args.kind)


if __name__ == "__main__":
    raise SystemExit(main())
