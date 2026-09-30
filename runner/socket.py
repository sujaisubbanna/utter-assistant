"""Unix-socket client API: dir 0700, socket 0600, SO_PEERCRED uid check,
default-deny allow-list / token auth, rate limiting, fd passing (TRUST §5, §13).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import socket as _socket
import struct
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import fdpass, framing
from .rpc import (
    NO_RESPONSE,
    PERMISSION_DENIED,
    RpcError,
    RpcPeer,
)

log = logging.getLogger("runner.socket")

# handler(method, params, peer) -> result (may return fdpass.FdReply)
Handler = Callable[[str, dict, RpcPeer], Awaitable[Any]]

DEFAULT_RATE_LIMIT = (1000, 10.0)  # max requests per window (per connection)


def default_socket_path() -> str:
    override = os.environ.get("UTTER_RUNNER_SOCK")
    if override:
        return override
    base = os.environ.get("XDG_RUNTIME_DIR") or str(
        Path(tempfile.gettempdir()) / f"utter-{os.getuid()}"
    )
    return str(Path(base) / "utter" / "runner.sock")


class RateLimiter:
    def __init__(self, max_requests: int, window: float):
        self.max = max_requests
        self.window = window
        self._hits: list[float] = []

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._hits = [t for t in self._hits if now - t < self.window]
        if len(self._hits) >= self.max:
            return False
        self._hits.append(now)
        return True


class SocketServer:
    def __init__(
        self,
        path: str,
        handler: Handler,
        *,
        require_uid: int | None = None,
        allow_binaries: list[str] | None = None,
        allow_same_uid: bool = False,
        token: str = "",
        rate_limit: tuple[int, float] = DEFAULT_RATE_LIMIT,
        on_disconnect: Callable[[RpcPeer], Awaitable[None]] | None = None,
    ):
        self.path = str(path)
        self.handler = handler
        self.require_uid = os.getuid() if require_uid is None else require_uid
        self.allow_binaries = set(allow_binaries or [])
        self.allow_same_uid = bool(allow_same_uid)
        self.token = token or ""
        self._rate_limit = rate_limit
        self._on_disconnect = on_disconnect
        self._server: asyncio.AbstractServer | None = None
        self._peers: set[tuple[RpcPeer, Any]] = set()

    async def start(self) -> None:
        directory = Path(self.path).parent
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        if os.path.exists(self.path):
            os.unlink(self.path)
        self._server = await asyncio.start_unix_server(self._on_client, path=self.path)
        os.chmod(self.path, 0o600)
        log.info(
            "runner socket listening at %s (allow_same_uid=%s binaries=%s token=%s)",
            self.path, self.allow_same_uid, sorted(self.allow_binaries), bool(self.token),
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for peer, _writer in list(self._peers):
            try:
                await peer.aclose()
            except Exception:
                pass
        self._peers.clear()
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
        except OSError:
            pass

    # -- per client ------------------------------------------------------- #
    async def _on_client(self, reader: asyncio.StreamReader, writer: Any) -> None:
        sock = writer.get_extra_info("socket")
        creds = self._peer_creds(sock)
        if creds is None:
            await self._reject(writer, "SO_PEERCRED unavailable")
            return
        pid, uid, _gid = creds
        exe = self._exe(pid)
        allowed, needs_auth, why = self._authorize_creds(pid, uid, exe)
        if not allowed:
            await self._reject(writer, why)
            return
        log.debug("socket: accepted client (%s)", why)

        limiter = RateLimiter(*self._rate_limit)
        authed = not needs_auth

        async def on_request(method: str, params: dict, rid: Any) -> Any:
            nonlocal authed
            if not limiter.allow():
                raise RpcError(PERMISSION_DENIED, "rate limit exceeded")
            if not authed:
                if method == "runner.auth":
                    supplied = str((params or {}).get("token", ""))
                    if self.token and hmac.compare_digest(supplied, self.token):
                        authed = True
                        return {}
                    raise RpcError(PERMISSION_DENIED, "invalid token")
                raise RpcError(PERMISSION_DENIED, "authentication required (send runner.auth)")
            result = await self.handler(method, params, peer)
            if isinstance(result, fdpass.FdReply):
                await self._send_fd_reply(peer, rid, result)
                return NO_RESPONSE
            return result

        peer = RpcPeer(reader, writer, name="client", on_request=on_request)
        self._peers.add((peer, writer))
        try:
            peer.start()
            await peer.wait_closed()
        finally:
            self._peers.discard((peer, writer))
            if self._on_disconnect is not None:
                try:
                    await self._on_disconnect(peer)
                except Exception:
                    log.exception("socket: disconnect cleanup failed")
            try:
                writer.close()
            except Exception:
                pass

    async def _reject(self, writer: Any, why: str) -> None:
        log.warning("socket: rejected client: %s", why)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    async def _send_fd_reply(self, peer: RpcPeer, rid: Any, reply: fdpass.FdReply) -> None:
        payload = framing.encode({"jsonrpc": "2.0", "id": rid, "result": reply.result})
        try:
            sock = peer.writer.get_extra_info("socket")
            if sock is None:
                raise OSError("no socket transport")
            fdpass.send_fds(sock, [reply.fd], payload)
        except OSError as exc:
            try:
                await peer.respond_error(rid, RpcError(-32005, f"fd.pass unsupported: {exc}"))
            except Exception:
                pass
        finally:
            try:
                os.close(reply.fd)
            except OSError:
                pass

    # -- auth ------------------------------------------------------------- #
    def _authorize_creds(self, pid: int, uid: int, exe: str | None) -> tuple[bool, bool, str]:
        """Return (allowed, needs_auth, reason); ``SocketServer`` is default-deny."""
        if uid != self.require_uid:
            return False, False, f"uid {uid} != required {self.require_uid}"
        if self.allow_same_uid:
            return True, False, f"same-uid dev override pid={pid}"
        if self.allow_binaries:
            if exe is not None and self._binary_allowed(exe):
                return True, False, f"allow-listed binary {Path(exe).name}"
            return False, False, f"binary {exe!r} not allow-listed (default-deny)"
        if self.token:
            return True, True, f"token auth required pid={pid}"
        return False, False, "default-deny: no allow_binaries/token/allow_same_uid"

    def _binary_allowed(self, exe: str) -> bool:
        name = Path(exe).name
        for allowed in self.allow_binaries:
            if name == allowed:
                return True
            # tolerate versioned interpreters: "python" matches "python3.14"
            if name.startswith(allowed) and name[len(allowed):len(allowed) + 1].isdigit():
                return True
        return False

    @staticmethod
    def _peer_creds(sock: Any) -> tuple[int, int, int] | None:
        if sock is None:
            return None
        try:
            raw = sock.getsockopt(
                _socket.SOL_SOCKET, _socket.SO_PEERCRED, struct.calcsize("3i")
            )
            return struct.unpack("3i", raw)
        except (AttributeError, OSError):
            return None

    @staticmethod
    def _exe(pid: int) -> str | None:
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None
