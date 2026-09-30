"""Independent client-side framing + JSON-RPC 2.0 helper for the utter
plugin protocol.

This module is written *from the frozen spec* (``protocol/PROTOCOL.md`` §1, §2,
§7) and deliberately does **not** import anything from the runner. Independence
is the point of a conformance suite: if the runner's own framing and this
client agree on the wire, the wire format is real.

Framing::

    Content-Length: <bytes>\\r\\n\\r\\n<utf-8 json>

Transports:
  * unix socket (runner control socket / plugin ``connect`` sockets)
  * stdio file objects (a spawned plugin's stdin/stdout)

Everything is synchronous and stdlib-only. Timeouts are per-frame. ``$/cancel``
is sent as a notification (best-effort, may arrive after side effects).
"""

from __future__ import annotations

import array
import errno
import json
import os
import select
import socket
import subprocess
import sys
import time
from collections import deque
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class FramingError(Exception):
    """Malformed frame (bad/garbled Content-Length header, bad JSON body)."""


class TransportClosed(Exception):
    """Peer closed the transport (clean EOF)."""


class FramingTimeout(TimeoutError):
    """No complete frame arrived within the deadline."""


class RpcError(Exception):
    """A JSON-RPC error object as returned by the peer."""

    def __init__(self, code: int, message: str, data: Any = None, req_id: Any = None):
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data
        self.id = req_id

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"RpcError(code={self.code!r}, message={self.message!r}, id={self.id!r})"


# Canonical taxonomy from PROTOCOL.md §7 + §14.
ERR_PLUGIN = -32000
ERR_TIMEOUT = -32001
ERR_CANCELLED = -32002
ERR_PERMISSION = -32003
ERR_INCOMPATIBLE = -32004
ERR_DEGRADED = -32005
ERR_UNTRUSTED = -32006
ERR_HANDLE_TOO_LARGE = -32007  # M1 §14: handle too large for inline fetch
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602


# --------------------------------------------------------------------------- #
# transports
# --------------------------------------------------------------------------- #
class Transport:
    """Minimal byte transport contract."""

    #: True when the transport can carry ``SCM_RIGHTS`` ancillary fds.
    supports_fd = False

    def send_all(self, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def recv_some(self, timeout: float) -> Optional[bytes]:
        """Return some bytes, ``b""`` on EOF, or ``None`` on timeout."""
        raise NotImplementedError  # pragma: no cover - interface

    def close(self) -> None:  # pragma: no cover - interface
        pass

    # optional diagnostic
    def describe(self) -> str:
        return type(self).__name__


class SocketTransport(Transport):
    supports_fd = True

    def __init__(self, sock: socket.socket, timeout: float = 30.0):
        self._sock = sock
        self._sock.setblocking(False)

    def send_all(self, data: bytes) -> None:
        total = 0
        while total < len(data):
            try:
                total += self._sock.send(data[total:])
            except BlockingIOError:
                select.select([], [self._sock], [], 5.0)

    def send_all_with_fds(self, data: bytes, fds: list[int]) -> None:
        """Send ``data`` with ``fds`` as ``SCM_RIGHTS`` ancillaries (socket only)."""
        if not fds:
            self.send_all(data)
            return
        fds_bytes = array.array("i", fds)
        sent = 0
        while sent < len(data):
            try:
                sent += self._sock.sendmsg(
                    [data[sent:]],
                    [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds_bytes)],
                )
            except BlockingIOError:
                select.select([], [self._sock], [], 5.0)

    def recv_some_with_fds(self, timeout: float) -> tuple[Optional[bytes], list[int]]:
        """Receive bytes plus any ``SCM_RIGHTS`` fds. ``(None, [])`` on timeout."""
        r, _, _ = select.select([self._sock], [], [], timeout)
        if not r:
            return None, []
        fds: list[int] = []
        try:
            msg, ancdata, _flags, _addr = self._sock.recvmsg(
                65536, socket.CMSG_SPACE(4 * 16)
            )
        except BlockingIOError:
            return b"", []
        for level, ctype, cdata in ancdata:
            if level == socket.SOL_SOCKET and ctype == socket.SCM_RIGHTS:
                arr = array.array("i")
                arr.frombytes(cdata[: len(cdata) - (len(cdata) % arr.itemsize)])
                fds.extend(arr.tolist())
        return msg, fds

    def recv_some(self, timeout: float) -> Optional[bytes]:
        r, _, _ = select.select([self._sock], [], [], timeout)
        if not r:
            return None
        try:
            chunk = self._sock.recv(65536)
        except BlockingIOError:
            return b""
        if not chunk:
            return b""
        return chunk

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def describe(self) -> str:
        try:
            return f"unix:{self._sock.getpeername()}"
        except OSError:
            return "unix"


class FileTransport(Transport):
    """Reads from a raw fd (never a buffered reader) and writes to a file obj.

    We read with ``os.read`` on the underlying fd so that no userspace buffer
    steals bytes from us. The write side may be a ``BufferedWriter``.
    """

    def __init__(self, read_file, write_file):
        self._rf = read_file
        self._wf = write_file
        self._rfd = read_file.fileno()

    def send_all(self, data: bytes) -> None:
        self._wf.write(data)
        self._wf.flush()

    def recv_some(self, timeout: float) -> Optional[bytes]:
        r, _, _ = select.select([self._rfd], [], [], timeout)
        if not r:
            return None
        try:
            return os.read(self._rfd, 65536)
        except OSError as exc:  # pragma: no cover - platform dependent
            if exc.errno in (errno.EIO, errno.EBADF):
                return b""
            raise

    def close(self) -> None:
        # Do NOT close the underlying files: the caller owns the process.
        pass

    def describe(self) -> str:
        return "stdio"


# --------------------------------------------------------------------------- #
# framing codec
# --------------------------------------------------------------------------- #
def encode_frame(obj: Any) -> bytes:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _parse_header(header: str) -> int:
    length: Optional[int] = None
    for line in header.replace("\r\n", "\n").split("\n"):
        if not line:
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key.strip().lower() == "content-length":
            try:
                length = int(value.strip())
            except ValueError as exc:
                raise FramingError(f"bad Content-Length: {value!r}") from exc
    if length is None:
        raise FramingError(f"frame header missing Content-Length: {header!r}")
    if length < 0:
        raise FramingError(f"negative Content-Length: {length}")
    return length


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #
class FramingClient:
    """Synchronous JSON-RPC 2.0 client over a Content-Length framed transport.

    Parameters
    ----------
    transport:
        A :class:`Transport`.
    timeout:
        Default per-request timeout in seconds.
    request_handler:
        Optional callable ``(method, params, id) -> result`` used to service
        *server-to-client* requests (e.g. ``host.confirm``). If it raises an
        :class:`RpcError` that error is returned to the peer; if omitted, server
        requests are answered with ``-32601``.
    notification_sink:
        Optional callable invoked for every incoming notification.
    """

    def __init__(
        self,
        transport: Transport,
        timeout: float = 30.0,
        *,
        request_handler: Optional[Callable[[str, Any, Any], Any]] = None,
        notification_sink: Optional[Callable[[str, Any], None]] = None,
        name: str = "",
    ):
        self.transport = transport
        self.timeout = timeout
        self.name = name
        self.request_handler = request_handler
        self.notification_sink = notification_sink
        self._buf = bytearray()
        self._next_id = 1
        self.notifications: deque[dict] = deque()
        self.server_requests: deque[dict] = deque()
        self.closed = False

    # -- constructors ------------------------------------------------------ #
    @classmethod
    def connect_unix(cls, path: str, timeout: float = 30.0, **kw) -> "FramingClient":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(path)
        sock.settimeout(None)
        return cls(SocketTransport(sock, timeout), timeout, name=f"unix:{path}", **kw)

    @classmethod
    def connect_socket(cls, sock: socket.socket, timeout: float = 30.0, **kw) -> "FramingClient":
        return cls(SocketTransport(sock, timeout), timeout, **kw)

    @classmethod
    def socketpair(cls, timeout: float = 30.0, **kw) -> tuple["FramingClient", "FramingClient"]:
        """Return two clients connected by a unix ``socketpair`` (fd-capable)."""
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        return (cls(SocketTransport(a, timeout), timeout, name="pair-a", **kw),
                cls(SocketTransport(b, timeout), timeout, name="pair-b", **kw))

    @property
    def raw_socket(self) -> Optional[socket.socket]:
        if isinstance(self.transport, SocketTransport):
            return self.transport._sock
        return None

    @classmethod
    def from_process(cls, proc: subprocess.Popen, timeout: float = 30.0, **kw) -> "FramingClient":
        assert proc.stdout is not None and proc.stdin is not None
        return cls(FileTransport(proc.stdout, proc.stdin), timeout, name="stdio", **kw)

    @classmethod
    def open_plugin(cls, argv: list[str], timeout: float = 30.0, **kw) -> "FramingClient":
        """Spawn a stdio plugin and return a client wired to it."""
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        client = cls.from_process(proc, timeout, **kw)
        client.proc = proc  # type: ignore[attr-defined]
        return client

    # -- raw io ------------------------------------------------------------ #
    def _recv_message(self, timeout: Optional[float]) -> Any:
        if timeout is None:
            timeout = self.timeout
        deadline = time.monotonic() + timeout
        while True:
            parsed = self._try_parse()
            if parsed is not None:
                return parsed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FramingTimeout(
                    f"timed out waiting for frame after {timeout}s "
                    f"(buffered {len(self._buf)} bytes) from {self.transport.describe()}"
                )
            chunk = self.transport.recv_some(remaining)
            if chunk is None:
                continue
            if chunk == b"":
                self.closed = True
                raise TransportClosed(
                    f"transport closed by {self.transport.describe()} "
                    f"(buffered {len(self._buf)} bytes)"
                )
            self._buf.extend(chunk)

    def _try_parse(self) -> Optional[Any]:
        idx = self._buf.find(b"\r\n\r\n")
        sep = 4
        if idx < 0:
            idx = self._buf.find(b"\n\n")
            sep = 2
        if idx < 0:
            return None
        header = bytes(self._buf[:idx]).decode("ascii", "replace")
        length = _parse_header(header)
        start = idx + sep
        if len(self._buf) < start + length:
            return None
        body = bytes(self._buf[start:start + length])
        del self._buf[:start + length]
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FramingError(f"invalid JSON body: {exc}") from exc

    def _recv_message_with_fds(self, timeout: Optional[float]) -> tuple[Any, list[int]]:
        """Like :meth:`_recv_message` but also returns any ``SCM_RIGHTS`` fds.

        The runner sends an ``fd.pass`` reply frame and its descriptor in a
        single ``sendmsg``, so the client must ``recvmsg`` to capture both.
        """
        if timeout is None:
            timeout = self.timeout
        if not isinstance(self.transport, SocketTransport):
            raise FramingError("fd.pass requires the socket transport")
        deadline = time.monotonic() + timeout
        fds: list[int] = []
        while True:
            parsed = self._try_parse()
            if parsed is not None:
                return parsed, fds
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FramingTimeout(
                    f"timed out waiting for fd frame after {timeout}s "
                    f"(buffered {len(self._buf)} bytes)"
                )
            chunk, got = self.transport.recv_some_with_fds(remaining)
            if chunk is None:
                continue
            if chunk == b"":
                self.closed = True
                raise TransportClosed("transport closed while awaiting fd frame")
            self._buf.extend(chunk)
            fds.extend(got)

    def send_frame(self, obj: Any) -> None:
        self.transport.send_all(encode_frame(obj))

    # -- high level -------------------------------------------------------- #
    def _handle_incoming(self, msg: Any) -> Optional[Any]:
        """Process one incoming message. Return a response dict if the peer sent
        us a request that must be answered, else None."""
        if isinstance(msg, list):
            # Batching is not used by the protocol, but tolerate it.
            for item in msg:
                out = self._handle_incoming(item)
                if out is not None:
                    self._respond(out)
            return None

        if not isinstance(msg, dict):
            raise FramingError(f"frame is not a JSON object: {msg!r}")

        has_method = "method" in msg
        has_id = "id" in msg
        if has_method and has_id:
            # server -> client request
            self.server_requests.append(msg)
            reply = self._answer_server_request(msg)
            return reply
        if has_method:  # notification
            self.notifications.append(msg)
            if self.notification_sink is not None:
                try:
                    self.notification_sink(str(msg.get("method") or ""), msg.get("params"))
                except Exception:  # noqa: BLE001 - sink must never break the client
                    pass
            return None
        return None  # a response, handled by request()

    def _respond(self, response: dict) -> None:
        self.send_frame(response)

    def _answer_server_request(self, msg: dict) -> dict:
        req_id = msg.get("id")
        method = str(msg.get("method") or "")
        params = msg.get("params")
        if self.request_handler is None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": ERR_METHOD_NOT_FOUND,
                              "message": f"no handler for server request {method!r}"}}
        try:
            result = self.request_handler(method, params, req_id)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except RpcError as exc:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": exc.code, "message": exc.message, "data": exc.data}}

    def new_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    def notify(self, method: str, params: Any = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.send_frame(msg)

    def cancel(self, req_id: Any) -> None:
        """Send a best-effort ``$/cancel`` notification (idempotent per spec)."""
        self.notify("$/cancel", {"id": req_id})

    def request(self, method: str, params: Any = None, timeout: Optional[float] = None,
                req_id: Optional[Any] = None) -> Any:
        if req_id is None:
            req_id = self.new_id()
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send_frame(msg)
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FramingTimeout(f"request {method!r} id={req_id} timed out")
            reply = self._recv_message(remaining)
            answer = self._handle_incoming(reply)
            if answer is not None:
                self._respond(answer)
            if not isinstance(reply, dict):
                continue
            if reply.get("id") != req_id or "method" in reply:
                continue
            if "error" in reply:
                err = reply["error"] or {}
                raise RpcError(int(err.get("code", ERR_PLUGIN)),
                               str(err.get("message", "")),
                               err.get("data"), req_id)
            return reply.get("result")

    # alias
    call = request

    def send_request_async(self, method: str, params: Any = None,
                           req_id: Optional[Any] = None) -> Any:
        """Send a request without waiting. Return the id so it can be awaited."""
        if req_id is None:
            req_id = self.new_id()
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send_frame(msg)
        return req_id

    def await_response(self, req_id: Any, timeout: Optional[float] = None) -> Any:
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FramingTimeout(f"await id={req_id} timed out")
            reply = self._recv_message(remaining)
            answer = self._handle_incoming(reply)
            if answer is not None:
                self._respond(answer)
            if not isinstance(reply, dict):
                continue
            if reply.get("id") != req_id or "method" in reply:
                continue
            if "error" in reply:
                err = reply["error"] or {}
                raise RpcError(int(err.get("code", ERR_PLUGIN)),
                               str(err.get("message", "")), err.get("data"), req_id)
            return reply.get("result")

    def drain_notifications(self, timeout: float = 0.0) -> list[dict]:
        """Read any immediately available notifications. Returns the drained list.

        With ``timeout=0`` this is a non-blocking poll: it reads whatever is
        already buffered/available without waiting for a full frame.
        """
        out: list[dict] = []
        deadline = time.monotonic() + timeout
        while True:
            while self.notifications:
                out.append(self.notifications.popleft())
            remaining = deadline - time.monotonic()
            if remaining < 0:
                break
            # Non-blocking: only read if bytes are already available.
            if not self._readable(remaining):
                break
            try:
                msg = self._recv_message(timeout=max(remaining, 0.001))
            except (FramingTimeout, TransportClosed):
                break
            self._handle_incoming(msg)
        return out

    def _readable(self, timeout: float) -> bool:
        """True if the transport has bytes ready (or a frame is buffered)."""
        if self._buf:
            return True
        if isinstance(self.transport, SocketTransport):
            r, _, _ = select.select([self.transport._sock], [], [], max(timeout, 0.0))
            return bool(r)
        if isinstance(self.transport, FileTransport):
            r, _, _ = select.select([self.transport._rfd], [], [], max(timeout, 0.0))
            return bool(r)
        return False

    # -- M1 client API helpers (PROTOCOL.md §10-§14) ----------------------- #
    def subscribe(self, method: str, params: Any = None, mode: Optional[str] = None,
                  timeout: Optional[float] = None) -> dict:
        """``stream.subscribe`` → ``{stream_id, mode}``."""
        p: dict[str, Any] = {"method": method}
        if params is not None:
            p["params"] = params
        if mode is not None:
            p["mode"] = mode
        return self.request("stream.subscribe", p, timeout=timeout)

    def ack(self, stream_id: str, seq: int, timeout: Optional[float] = None) -> Any:
        """``stream.ack`` — replenish reliable-mode credit."""
        return self.request("stream.ack", {"stream_id": stream_id, "seq": seq},
                            timeout=timeout)

    def stop_stream(self, stream_id: str, timeout: Optional[float] = None) -> Any:
        """``stream.stop`` — idempotent; frees buffers."""
        return self.request("stream.stop", {"stream_id": stream_id}, timeout=timeout)

    def collect_stream(self, stream_id: str, *, duration: float = 1.0,
                       read_budget: Optional[int] = None,
                       poll: float = 0.01) -> list[dict]:
        """Consume notifications for ``stream_id`` for ``duration`` seconds.

        ``read_budget`` bounds how many frames are read per poll (drop-oldest
        for a deliberately slow consumer). Returns the retained notifications.
        """
        out: list[dict] = []
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            time.sleep(poll)
            notes = self.drain_notifications(timeout=poll)
            batch = [n for n in notes
                     if (n.get("params") or {}).get("stream_id") == stream_id]
            if read_budget is not None and len(batch) > read_budget:
                batch = batch[-read_budget:]  # drop-oldest
            out.extend(batch)
        return out

    def invoke(self, plugin: str, method: str, params: Any = None,
               timeout: Optional[float] = None) -> Any:
        """``runner.invoke`` — runner-mediated plugin call."""
        return self.request("runner.invoke",
                            {"plugin": plugin, "method": method, "params": params or {}},
                            timeout=timeout)

    def validate_plugin(self, plugin: str, timeout: Optional[float] = None) -> dict:
        """``runner.validate_plugin`` → negotiation + capability/permission report."""
        return self.request("runner.validate_plugin", {"plugin": plugin}, timeout=timeout)

    def auth(self, token: str, timeout: Optional[float] = None) -> Any:
        """``runner.auth`` — token authentication for a default-deny socket."""
        return self.request("runner.auth", {"token": token}, timeout=timeout)

    def handle_fetch(self, handle: str, timeout: Optional[float] = None) -> dict:
        """``handle.fetch`` — inline (≤64 KiB) or ``-32007``."""
        return self.request("handle.fetch", {"handle": handle}, timeout=timeout)

    def fd_pass(self, kind: str, meta: Any = None, fds: Optional[list[int]] = None,
                timeout: Optional[float] = None) -> Any:
        """``fd.pass`` — send a control frame, optionally with ``SCM_RIGHTS`` fds.

        Returns the JSON-RPC result. When ``fds`` are supplied the frame is sent
        with ``sendmsg`` ancillaries (socket transport only).
        """
        if fds:
            if not self.transport.supports_fd:
                raise FramingError("fd.pass requires the socket transport")
            req_id = self.new_id()
            msg = {"jsonrpc": "2.0", "id": req_id, "method": "fd.pass",
                   "params": {"kind": kind, "meta": meta or {}}}
            self.transport.send_all_with_fds(encode_frame(msg), fds)  # type: ignore[attr-defined]
            return self.await_response(req_id, timeout=timeout)
        return self.request("fd.pass", {"kind": kind, "meta": meta or {}}, timeout=timeout)

    def fd_pass_recv(self, kind: str, meta: Any = None,
                     timeout: Optional[float] = None) -> tuple[Any, list[int]]:
        """``fd.pass`` → ``(result, fds)``.

        The runner sends the JSON-RPC reply frame and the descriptor in a single
        ``sendmsg``, so this uses ``recvmsg`` to capture both. The caller owns
        the returned fds and must close them.
        """
        if not isinstance(self.transport, SocketTransport):
            raise FramingError("fd.pass requires the socket transport")
        req_id = self.new_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": "fd.pass",
               "params": {"kind": kind, "meta": meta or {}}}
        self.send_frame(msg)
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FramingTimeout(f"fd.pass id={req_id} timed out")
            reply, fds = self._recv_message_with_fds(remaining)
            answer = self._handle_incoming(reply)
            if answer is not None:
                self._respond(answer)
            if not isinstance(reply, dict):
                continue
            if reply.get("id") != req_id or "method" in reply:
                continue
            if "error" in reply:
                err = reply["error"] or {}
                raise RpcError(int(err.get("code", ERR_PLUGIN)),
                               str(err.get("message", "")), err.get("data"), req_id)
            return reply.get("result"), fds

    def send_fd_frame(self, kind: str, meta: Any = None,
                      fds: Optional[list[int]] = None) -> Any:
        """Send an ``fd.pass`` frame with ``SCM_RIGHTS`` fds *without* awaiting.

        Returns the request id. Use :meth:`recv_fds` on the peer to read the
        frame + descriptors. This is the raw mechanism used by the socketpair
        round-trip test.
        """
        if not self.transport.supports_fd:
            raise FramingError("fd.pass requires the socket transport")
        req_id = self.new_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": "fd.pass",
               "params": {"kind": kind, "meta": meta or {}}}
        self.transport.send_all_with_fds(encode_frame(msg), fds or [])  # type: ignore[attr-defined]
        return req_id

    def recv_fds(self, timeout: float = 5.0) -> tuple[Optional[bytes], list[int]]:
        """Receive raw bytes + ``SCM_RIGHTS`` fds (socket transport only)."""
        if not isinstance(self.transport, SocketTransport):
            raise FramingError("recv_fds requires the socket transport")
        return self.transport.recv_some_with_fds(timeout)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "FramingClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# convenience: stdio handshake used by tests/spike
# --------------------------------------------------------------------------- #
def handshake_stdio(argv: list[str], *, protocol: str = "1.0", abi: int = 1,
                    runner: str = "conformance", epoch: int = 1,
                    timeout: float = 15.0) -> dict:
    """Spawn ``argv`` as a stdio plugin and drive the frozen handshake.

    Returns a dict with the raw hello/describe/health results and the client
    (caller may keep using it; the process is left running).
    """
    client = FramingClient.open_plugin(argv, timeout=timeout)
    try:
        hello = client.request("protocol.hello", {
            "protocol": protocol, "abi": abi, "runner": runner, "epoch": epoch,
        })
        describe = client.request("plugin.describe", {})
        health = client.request("plugin.health", {})
        return {"client": client, "hello": hello, "describe": describe, "health": health}
    except Exception:
        client.close()
        proc = getattr(client, "proc", None)
        if proc is not None:
            proc.kill()
        raise


def runner_socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.environ.get(
        "UTTER_RUNNER_SOCK",
        os.path.join(runtime, "utter", "runner.sock"),
    )


if __name__ == "__main__":  # pragma: no cover - tiny manual smoke tool
    if len(sys.argv) < 2:
        print("usage: framing_client.py <plugin-argv...>", file=sys.stderr)
        raise SystemExit(2)
    info = handshake_stdio(sys.argv[1:])
    print(json.dumps({k: info[k] for k in ("hello", "describe", "health")}, indent=2))
    client = info["client"]
    client.close()
    proc = getattr(client, "proc", None)
    if proc is not None:
        proc.terminate()
