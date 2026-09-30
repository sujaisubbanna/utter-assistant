"""SCM_RIGHTS fd passing for unix socket transports (PROTOCOL §10, §12).

``fd.pass`` is only valid over a socket (never stdio pipes). These helpers are
the low-level primitive; the socket server writes the JSON-RPC reply frame and
the descriptor in a single ``sendmsg`` so the client can ``recvmsg`` both.
"""

from __future__ import annotations

import array
import os
import socket
from dataclasses import dataclass
from typing import Any

_MAX_FDS = 16


@dataclass
class FdReply:
    """A handler's instruction to the socket server: send ``fd`` as ancillary."""

    fd: int
    result: dict[str, Any]


def _raw(sock: Any) -> Any:
    """Unwrap asyncio's TransportSocket to the underlying ``socket.socket``."""
    return getattr(sock, "_sock", sock)


def send_fds(sock: Any, fds: list[int], payload: bytes = b"") -> int:
    """Send ``payload`` with ``fds`` attached as SCM_RIGHTS ancillary data."""
    anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", list(fds)).tobytes())]
    return _raw(sock).sendmsg([payload], anc)


def recv_fds(sock: Any, maxfds: int = _MAX_FDS, bufsize: int = 65536) -> tuple[bytes, list[int]]:
    """Receive bytes plus any SCM_RIGHTS descriptors."""
    fds = array.array("i")
    data, ancdata, _flags, _addr = _raw(sock).recvmsg(
        bufsize, socket.CMSG_LEN(maxfds * fds.itemsize)
    )
    received: list[int] = []
    for level, ctype, cdata in ancdata:
        if level == socket.SOL_SOCKET and ctype == socket.SCM_RIGHTS:
            usable = len(cdata) - (len(cdata) % fds.itemsize)
            fds.frombytes(cdata[:usable])
            received.extend(fds)
    return bytes(data), received


def close_all(fds: list[int]) -> None:
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass
