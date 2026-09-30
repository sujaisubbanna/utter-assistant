#!/usr/bin/env python3
"""fake_py — a deterministic fake utter plugin (Python, stdlib only).

Implements the frozen handshake plus the methods the M0 conformance suite and
measurement spike need:

  protocol.hello, plugin.describe, plugin.health
  router.plan, action.capabilities, action.invoke, context.snapshot
  stream.subscribe / stream.stop  (lossy frame emitter for backpressure tests)
  handle.create / handle.stat / handle.fetch  (content-addressed blob)
  fd.pass  (socket transport only; reports unsupported over stdio)
  $/cancel  (idempotent; long invokes report cancelled)

Determinism contract (asserted by tests/conformance/run.py):
  router.plan("open youtube")
      -> steps == [{op:"ensure_url",
                    args:{url:"https://www.youtube.com"},
                    provenance:"user"}]
  action.invoke("ensure_url", ...) -> ok
  action.invoke("terminal", ...)   -> needs_confirm

Transport: stdio by default. With ``--socket <path>`` the plugin listens on a
unix socket instead (used to exercise fd passing). Terminates on stdin EOF.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import os
import select
import socket
import sys
import threading
import time
from typing import Any, Optional

PROTOCOL = "1.0"
ABI = 1
PLUGIN_NAME = "fake_py"
PLUGIN_VERSION = "0.1.0"
PLUGIN_KIND = "bundle"

PROVIDES = [
    "action.open_url@1",
    "action.terminal@1",
    "context.live@1",
    "fs.tmp@1",
    "host.fd.pass@1",
    "experimental/fake_py@1",
]
REQUIRES = ["context.live@1", "fs.tmp@1"]
PERMISSIONS = ["filesystem.read", "filesystem.write", "network"]

YOUTUBE_URL = "https://www.youtube.com"

# ops the fake advertises
OPS = [
    {"op": "ensure_url", "side_effect": "open_url", "needs_confirm": False},
    {"op": "open_url", "side_effect": "open_url", "needs_confirm": False},
    {"op": "terminal", "side_effect": "shell", "needs_confirm": True},
    {"op": "slow", "side_effect": "none", "needs_confirm": False},
    {"op": "blob", "side_effect": "none", "needs_confirm": False},
]

# in-memory handle store: handle://<sha256> -> bytes
_HANDLES: dict[str, bytes] = {}
_HANDLES_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# framing
# --------------------------------------------------------------------------- #
def encode_frame(obj: Any) -> bytes:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class Peer:
    """One framed peer over a socket or a pair of file objects."""

    def __init__(self, sock: Optional[socket.socket] = None,
                 read_file=None, write_file=None):
        self.sock = sock
        self.read_file = read_file
        self.write_file = write_file
        self.buf = bytearray()
        self.write_lock = threading.Lock()
        self.closed = False

    def send(self, obj: Any) -> None:
        data = encode_frame(obj)
        with self.write_lock:
            if self.sock is not None:
                self.sock.sendall(data)
            else:
                self.write_file.write(data)
                self.write_file.flush()

    def send_with_fds(self, obj: Any, fds: list[int]) -> None:
        """Send a frame with ``SCM_RIGHTS`` ancillary fds (socket transport only)."""
        if self.sock is None:
            raise OSError("fd passing requires the socket transport")
        data = encode_frame(obj)
        fds_bytes = array.array("i", fds)
        with self.write_lock:
            self.sock.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds_bytes)])

    def _read_some(self, timeout: float) -> Optional[bytes]:
        if self.sock is not None:
            r, _, _ = select.select([self.sock], [], [], timeout)
            if not r:
                return None
            return self.sock.recv(65536)
        fd = self.read_file.fileno()
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            return None
        return os.read(fd, 65536)

    def read_message(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Return the next JSON message, or None on timeout/EOF."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            parsed = self._try_parse()
            if parsed is not None:
                return parsed
            if deadline is None:
                chunk = self._read_some(1.0)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                chunk = self._read_some(remaining)
            if chunk is None:
                continue
            if chunk == b"":
                self.closed = True
                return None
            self.buf.extend(chunk)

    def _try_parse(self) -> Optional[Any]:
        idx = self.buf.find(b"\r\n\r\n")
        sep = 4
        if idx < 0:
            idx = self.buf.find(b"\n\n")
            sep = 2
        if idx < 0:
            return None
        header = bytes(self.buf[:idx]).decode("ascii", "replace")
        length = None
        for line in header.replace("\r\n", "\n").split("\n"):
            key, s, value = line.partition(":")
            if s and key.strip().lower() == "content-length":
                length = int(value.strip())
        if length is None:
            raise ValueError(f"missing Content-Length: {header!r}")
        start = idx + sep
        if len(self.buf) < start + length:
            return None
        body = bytes(self.buf[start:start + length])
        del self.buf[:start + length]
        return json.loads(body.decode("utf-8"))


# --------------------------------------------------------------------------- #
# plugin state
# --------------------------------------------------------------------------- #
class FakePlugin:
    def __init__(self, peer: Peer, transport: str):
        self.peer = peer
        self.transport = transport
        self.epoch = 0
        self.cancelled: set[Any] = set()
        self.cancel_lock = threading.Lock()
        self.streams: dict[str, dict] = {}
        self.stream_lock = threading.Lock()
        self._stream_seq = 0

    # -- helpers ----------------------------------------------------------- #
    def result(self, req_id: Any, result: Any) -> None:
        self.peer.send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def error(self, req_id: Any, code: int, message: str, data: Any = None) -> None:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        self.peer.send({"jsonrpc": "2.0", "id": req_id, "error": err})

    def notify(self, method: str, params: Any) -> None:
        self.peer.send({"jsonrpc": "2.0", "method": method, "params": params})

    def is_cancelled(self, req_id: Any) -> bool:
        with self.cancel_lock:
            return req_id in self.cancelled

    # -- dispatch ---------------------------------------------------------- #
    def handle(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "$/cancel":
            target = params.get("id")
            with self.cancel_lock:
                self.cancelled.add(target)
            return  # notification: no reply

        if method == "stream.stop":
            sid = str(params.get("stream_id") or "")
            with self.stream_lock:
                self.streams.pop(sid, None)
            if req_id is not None:
                self.result(req_id, {"stopped": True, "stream_id": sid})
            return

        if method == "stream.ack":
            if req_id is not None:
                self.result(req_id, self._ack(params))
            return

        if method == "stream.subscribe":
            self._subscribe(req_id, params)
            return

        if method == "action.invoke":
            # may block; run off the read loop so $/cancel can arrive
            threading.Thread(target=self._invoke, args=(req_id, params), daemon=True).start()
            return

        handler = {
            "protocol.hello": self._hello,
            "plugin.describe": self._describe,
            "plugin.health": self._health,
            "router.plan": self._plan,
            "action.capabilities": self._capabilities,
            "context.snapshot": self._snapshot,
            "handle.create": self._handle_create,
            "handle.stat": self._handle_stat,
            "handle.fetch": self._handle_fetch,
            "fd.pass": self._fd_pass,
            "memfd.ring": self._memfd_ring,
        }.get(str(method or ""))
        if handler is None:
            if req_id is not None:
                self.error(req_id, -32601, f"method not found: {method}")
            return
        try:
            result = handler(params)
            if req_id is not None:
                self.result(req_id, result)
        except Exception as exc:  # noqa: BLE001
            if req_id is not None:
                self.error(req_id, -32000, f"plugin error: {exc}")

    # -- handshake --------------------------------------------------------- #
    def _hello(self, params: dict) -> dict:
        self.epoch = int(params.get("epoch", 0))
        return {
            "protocol": PROTOCOL,
            "abi": ABI,
            "plugin": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION, "kind": PLUGIN_KIND},
            "transport": self.transport,
            "provides": list(PROVIDES),
            "requires": list(REQUIRES),
            "permissions": list(PERMISSIONS),
        }

    def _describe(self, params: dict) -> dict:
        return {
            "methods": [
                "protocol.hello", "plugin.describe", "plugin.health",
                "router.plan", "action.capabilities", "action.invoke",
                "context.snapshot", "stream.subscribe", "stream.ack", "stream.stop",
                "handle.create", "handle.stat", "handle.fetch", "fd.pass",
                "memfd.ring",
            ],
            "streams": ["fake.frames"],
        }

    def _health(self, params: dict) -> dict:
        return {"status": "ok", "detail": "fake_py ready"}

    # -- router / action --------------------------------------------------- #
    def _plan(self, params: dict) -> dict:
        utterance = str(params.get("utterance", "")).strip().lower()
        provenance = params.get("provenance", "user")
        if utterance in ("open youtube", "open youtube.com", "go to youtube"):
            return {
                "steps": [{
                    "op": "ensure_url",
                    "args": {"url": YOUTUBE_URL},
                    "provenance": provenance,
                }]
            }
        if utterance.startswith("run ") or utterance.startswith("terminal "):
            cmd = utterance.split(" ", 1)[1]
            return {
                "steps": [{
                    "op": "terminal",
                    "args": {"command": cmd},
                    "provenance": provenance,
                    "confirm": True,
                }]
            }
        return {"steps": []}

    def _capabilities(self, params: dict) -> dict:
        return {"ops": list(OPS)}

    def _invoke(self, req_id: Any, params: dict) -> None:
        op = params.get("op")
        args = params.get("args") or {}
        provenance = params.get("provenance", "user")

        if op in ("ensure_url", "open_url"):
            url = args.get("url", "")
            self.result(req_id, {
                "ok": True, "op": op, "detail": f"opened {url}",
                "provenance": provenance,
            })
            return

        if op == "terminal":
            # The plugin only *hints*; the runner owns confirmation (TRUST.md §3).
            self.result(req_id, {
                "ok": False, "op": op, "needs_confirm": True,
                "detail": f"terminal requires confirmation: {args.get('command', '')}",
                "provenance": provenance,
            })
            return

        if op == "slow":
            ms = int(args.get("ms", 5000))
            deadline = time.monotonic() + ms / 1000.0
            while time.monotonic() < deadline:
                if self.is_cancelled(req_id):
                    self.error(req_id, -32002, "cancelled", {"op": op})
                    return
                time.sleep(0.01)
            self.result(req_id, {"ok": True, "op": op, "detail": f"slept {ms}ms"})
            return

        if op == "blob":
            data = str(args.get("data", "hello utter")).encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            handle = f"handle://{digest}"
            with _HANDLES_LOCK:
                _HANDLES[handle] = data
            self.result(req_id, {
                "ok": True, "op": op, "handle": handle,
                "sha256": digest, "bytes": len(data),
            })
            return

        self.error(req_id, -32000, f"unknown op: {op}")

    # -- context ----------------------------------------------------------- #
    def _snapshot(self, params: dict) -> dict:
        return {
            "focused": {"app_id": "zen", "title": "YouTube", "pid": os.getpid()},
            "clipboard": "",
            "timestamp": time.time(),
            "source": "fake_py",
        }

    # -- handles ----------------------------------------------------------- #
    def _handle_create(self, params: dict) -> dict:
        if "size" in params:
            data = bytes(int(params["size"]))
        else:
            data = str(params.get("data", "hello utter")).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        handle = f"handle://{digest}"
        with _HANDLES_LOCK:
            _HANDLES[handle] = data
        return {"handle": handle, "sha256": digest, "bytes": len(data)}

    def _handle_stat(self, params: dict) -> dict:
        handle = params.get("handle", "")
        with _HANDLES_LOCK:
            data = _HANDLES.get(handle)
        if data is None:
            raise ValueError(f"unknown handle {handle}")
        return {"handle": handle, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}

    def _handle_fetch(self, params: dict) -> dict:
        handle = params.get("handle", "")
        with _HANDLES_LOCK:
            data = _HANDLES.get(handle)
        if data is None:
            raise ValueError(f"unknown handle {handle}")
        import base64
        return {
            "handle": handle,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "data_b64": base64.b64encode(data).decode("ascii"),
        }

    # -- fd passing -------------------------------------------------------- #
    def _fd_pass(self, params: dict) -> dict:
        if self.transport != "socket":
            return {"supported": False, "reason": "stdio transport has no fd passing"}
        # Over the socket transport, actually send a memfd as an SCM_RIGHTS
        # ancillary so the peer can read it back.
        kind = str(params.get("kind") or "memfd")
        payload = str(params.get("meta", {}).get("data", "fake_py fd payload")).encode()
        try:
            fd = os.memfd_create(f"fake_py-{kind}", 0)
            os.write(fd, payload)
            os.lseek(fd, 0, 0)
            self.peer.send_with_fds(
                {"jsonrpc": "2.0", "method": "fd.recv",
                 "params": {"kind": kind, "bytes": len(payload)}},
                [fd],
            )
            os.close(fd)
            return {"supported": True, "kind": kind, "bytes": len(payload)}
        except (AttributeError, OSError) as exc:
            return {"supported": False, "reason": f"fd send failed: {exc}"}

    # -- memfd ring buffer ------------------------------------------------- #
    def _memfd_ring(self, params: dict) -> dict:
        """Create a memfd ring buffer and return its size + a handle name.

        The fd itself is delivered via ``fd.pass``; this method only reports the
        ring geometry so the client can validate the round trip.
        """
        size = int(params.get("size", 4096))
        try:
            fd = os.memfd_create("fake_py-ring", 0)
            os.ftruncate(fd, size)
            os.close(fd)
            return {"ok": True, "size": size, "kind": "memfd.ring"}
        except (AttributeError, OSError) as exc:
            return {"ok": False, "reason": f"memfd unavailable: {exc}"}

    # -- streams ----------------------------------------------------------- #
    def _subscribe(self, req_id: Any, params: dict) -> None:
        mode = str(params.get("mode") or "lossy")
        with self.stream_lock:
            self._stream_seq += 1
            sid = f"fake-stream-{self._stream_seq}"
            self.streams[sid] = {
                "method": params.get("method", "fake.frames"),
                "params": params.get("params") or {},
                "mode": mode,
                # reliable mode: credit window (default 64, PROTOCOL.md §11)
                "credits": int(params.get("credits", 64)),
                "acked": 0,
                "paused": False,
            }
        if req_id is not None:
            self.result(req_id, {"stream_id": sid, "mode": mode})
        threading.Thread(target=self._emit, args=(sid,), daemon=True).start()

    def _ack(self, params: dict) -> dict:
        sid = str(params.get("stream_id") or "")
        seq = int(params.get("seq") or 0)
        with self.stream_lock:
            st = self.streams.get(sid)
            if st is None:
                return {"ok": False, "reason": "unknown stream"}
            st["acked"] = max(st["acked"], seq)
            st["credits"] += 1  # replenish one credit per ack
            st["paused"] = False
        return {"ok": True, "stream_id": sid, "seq": seq}

    def _emit(self, sid: str) -> None:
        """Emit frames until stopped.

        lossy: produce as fast as possible (the *runner* owns the bounded queue
        and drop-oldest policy).
        reliable: pause when the credit window is exhausted; resume on ack.
        """
        seq = 0
        while True:
            with self.stream_lock:
                st = self.streams.get(sid)
                if st is None:
                    return
                mode = st["mode"]
                if mode == "reliable":
                    if st["credits"] <= 0:
                        st["paused"] = True
                        # wait for an ack to replenish credit
                        time.sleep(0.005)
                        continue
                    st["credits"] -= 1
            seq += 1
            try:
                self.notify("fake.frames", {
                    "stream_id": sid,
                    "seq": seq,
                    "data": {"n": seq, "t": time.time()},
                })
            except OSError:
                return
            if mode == "reliable":
                time.sleep(0.002)  # paced so the client can observe pausing
            # lossy: no sleep — deliberately faster than any consumer

    def stream_state(self, sid: str) -> dict:
        with self.stream_lock:
            st = self.streams.get(sid)
            return dict(st) if st else {}


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def serve_stdio() -> int:
    peer = Peer(read_file=sys.stdin.buffer, write_file=sys.stdout.buffer)
    plugin = FakePlugin(peer, transport="stdio")
    while True:
        msg = peer.read_message(timeout=None)
        if msg is None:
            break  # EOF -> terminate
        plugin.handle(msg)
    return 0


def serve_socket(path: str) -> int:
    if os.path.exists(path):
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(4)
    try:
        conn, _ = srv.accept()
    finally:
        srv.close()
    peer = Peer(sock=conn)
    plugin = FakePlugin(peer, transport="socket")
    while True:
        msg = peer.read_message(timeout=None)
        if msg is None:
            break
        plugin.handle(msg)
    conn.close()
    try:
        os.unlink(path)
    except OSError:
        pass
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="fake utter plugin (python)")
    ap.add_argument("--socket", metavar="PATH",
                    help="listen on a unix socket instead of stdio")
    args = ap.parse_args(argv)
    if args.socket:
        return serve_socket(args.socket)
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
