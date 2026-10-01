"""D-Bus wire protocol for the session helpers (stdlib only, no ``shell=True``).

This module holds the *wire* half of :mod:`utter.context.backends.dbus`: the
tiny inbound receiver :class:`LiteBus`. KWin scripts cannot return values; the
standard trick (also used by ``kdotool``) is for the script to ``callDBus`` a
method on a bus name the caller owns. ``LiteBus`` speaks just enough of the
D-Bus wire protocol to connect to the session bus, say ``Hello``,
``RequestName`` and wait for one method call carrying a string. It is
exercised on any machine with a session bus (see tests), so it does not need a
live Plasma to be verified.

:func:`session_bus_address` lives here because it is the connection-level
counterpart of the wire code (``dbus.py`` re-exports it).
"""
from __future__ import annotations

import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional


def session_bus_address(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """``unix:path=`` or ``unix:abstract=`` socket from ``DBUS_SESSION_BUS_ADDRESS``."""
    e = os.environ if env is None else env
    addr = e.get("DBUS_SESSION_BUS_ADDRESS") or ""
    if not addr:
        rt = e.get("XDG_RUNTIME_DIR")
        if rt and os.path.exists(os.path.join(rt, "bus")):
            return os.path.join(rt, "bus")
        return None
    for part in addr.split(";"):
        if not part.startswith("unix:"):
            continue
        for kv in part[len("unix:"):].split(","):
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            if k == "path":
                return v
            if k == "abstract":
                return "\0" + v
    return None


# --------------------------------------------------------------------------- #
# LiteBus: own a name and receive one method call (stdlib wire protocol)
# --------------------------------------------------------------------------- #
_METHOD_CALL, _METHOD_RETURN, _ERROR, _SIGNAL = 1, 2, 3, 4
_H_PATH, _H_IFACE, _H_MEMBER, _H_ERROR, _H_REPLY_SERIAL, _H_DEST, _H_SENDER, _H_SIG = 1, 2, 3, 4, 5, 6, 7, 8


class _W:
    def __init__(self):
        self.b = bytearray()

    def pad(self, n: int) -> None:
        while len(self.b) % n:
            self.b.append(0)

    def u8(self, v: int) -> None:
        self.b.append(v & 0xFF)

    def u32(self, v: int) -> None:
        self.pad(4)
        self.b += struct.pack("<I", v)

    def s(self, v: str) -> None:
        raw = v.encode("utf-8")
        self.u32(len(raw))
        self.b += raw + b"\0"

    def g(self, v: str) -> None:
        raw = v.encode("ascii")
        self.u8(len(raw))
        self.b += raw + b"\0"


class _R:
    def __init__(self, data: bytes, little: bool = True):
        self.d = data
        self.i = 0
        self.e = "<" if little else ">"

    def pad(self, n: int) -> None:
        while self.i % n:
            self.i += 1

    def u8(self) -> int:
        v = self.d[self.i]
        self.i += 1
        return v

    def u32(self) -> int:
        self.pad(4)
        v = struct.unpack_from(self.e + "I", self.d, self.i)[0]
        self.i += 4
        return v

    def s(self) -> str:
        n = self.u32()
        v = self.d[self.i:self.i + n].decode("utf-8", "replace")
        self.i += n + 1
        return v

    def g(self) -> str:
        n = self.u8()
        v = self.d[self.i:self.i + n].decode("ascii", "replace")
        self.i += n + 1
        return v

    def value(self, sig: str) -> tuple[Any, str]:
        """Read one complete type from ``sig``; returns (value, remaining signature)."""
        c = sig[0]
        rest = sig[1:]
        if c in "sog":
            return (self.s() if c != "g" else self.g()), rest
        if c == "y":
            return self.u8(), rest
        if c == "b":
            return bool(self.u32()), rest
        if c in "iu":
            self.pad(4)
            v = struct.unpack_from(self.e + ("i" if c == "i" else "I"), self.d, self.i)[0]
            self.i += 4
            return v, rest
        if c in "nq":
            self.pad(2)
            v = struct.unpack_from(self.e + ("h" if c == "n" else "H"), self.d, self.i)[0]
            self.i += 2
            return v, rest
        if c in "xtd":
            self.pad(8)
            v = struct.unpack_from(self.e + {"x": "q", "t": "Q", "d": "d"}[c], self.d, self.i)[0]
            self.i += 8
            return v, rest
        if c == "v":
            inner = self.g()
            v, _ = self.value(inner)
            return v, rest
        if c == "a":
            n = self.u32()
            elem, rest2 = _split_one(rest)
            align = _alignment(elem)
            self.pad(align)
            end = self.i + n
            items: list = []
            while self.i < end:
                v, _ = self.value(elem)
                items.append(v)
            if elem.startswith("{"):
                return {k: v for k, v in items}, rest2
            return items, rest2
        if c in "({":
            close = ")" if c == "(" else "}"
            inner, rest2 = _until_close(sig[1:], close)
            self.pad(8)
            vals: list = []
            s = inner
            while s:
                v, s = self.value(s)
                vals.append(v)
            return (tuple(vals) if c == "(" else (vals[0], vals[1])), rest2
        raise ValueError(f"unsupported signature {sig!r}")


def _until_close(s: str, close: str) -> tuple[str, str]:
    depth = 1
    for idx, ch in enumerate(s):
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
            if depth == 0:
                return s[:idx], s[idx + 1:]
    raise ValueError(f"unbalanced signature {s!r}")


def _split_one(sig: str) -> tuple[str, str]:
    c = sig[0]
    if c == "a":
        inner, rest = _split_one(sig[1:])
        return "a" + inner, rest
    if c in "({":
        inner, rest = _until_close(sig[1:], ")" if c == "(" else "}")
        return c + inner + (")" if c == "(" else "}"), rest
    return c, sig[1:]


def _alignment(sig: str) -> int:
    c = sig[0]
    if c in "yg":
        return 1
    if c in "nq":
        return 2
    if c in "biuahso":
        return 4
    if c == "v":
        return 1
    return 8  # x t d ( {


def build_message(mtype: int, serial: int, fields: list[tuple[int, str, Any]], body: bytes = b"",
                  flags: int = 0) -> bytes:
    """Serialise a D-Bus message (little endian). ``fields`` = (code, sig, value)."""
    w = _W()
    w.u8(ord("l"))
    w.u8(mtype)
    w.u8(flags)
    w.u8(1)
    w.u32(len(body))
    w.u32(serial)
    fw = _W()
    for code, sig, value in fields:
        fw.pad(8)
        fw.u8(code)
        fw.g(sig)
        if sig in ("s", "o"):
            fw.s(value)
        elif sig == "g":
            fw.g(value)
        elif sig == "u":
            fw.u32(value)
        else:
            raise ValueError(f"unsupported header field signature {sig!r}")
    w.u32(len(fw.b))
    w.b += fw.b
    w.pad(8)
    w.b += body
    return bytes(w.b)


def marshal_body(sig: str, values: tuple) -> bytes:
    w = _W()
    for c, v in zip(sig, values):
        if c in ("s", "o"):
            w.s(v)
        elif c == "u":
            w.u32(int(v))
        elif c == "i":
            w.pad(4)
            w.b += struct.pack("<i", int(v))
        elif c == "b":
            w.u32(1 if v else 0)
        else:
            raise ValueError(f"marshal_body: unsupported {c!r}")
    return bytes(w.b)


@dataclass
class Message:
    mtype: int
    serial: int
    fields: dict
    body: bytes
    little: bool = True

    @property
    def member(self) -> str:
        return str(self.fields.get(_H_MEMBER, ""))

    @property
    def sender(self) -> str:
        return str(self.fields.get(_H_SENDER, ""))

    @property
    def signature(self) -> str:
        return str(self.fields.get(_H_SIG, ""))

    def args(self) -> list[Any]:
        if not self.signature:
            return []
        r = _R(self.body, self.little)
        out: list[Any] = []
        sig = self.signature
        while sig:
            v, sig = r.value(sig)
            out.append(v)
        return out


def parse_message(data: bytes) -> tuple[Optional[Message], int]:
    """Parse one message from ``data``; returns (message | None if incomplete, bytes consumed)."""
    if len(data) < 16:
        return None, 0
    little = data[0:1] == b"l"
    e = "<" if little else ">"
    mtype = data[1]
    body_len = struct.unpack_from(e + "I", data, 4)[0]
    serial = struct.unpack_from(e + "I", data, 8)[0]
    fields_len = struct.unpack_from(e + "I", data, 12)[0]
    header_end = 16 + fields_len
    body_start = (header_end + 7) // 8 * 8
    total = body_start + body_len
    if len(data) < total:
        return None, 0
    r = _R(data[:header_end], little)
    r.i = 16
    fields: dict = {}
    while r.i < header_end:
        r.pad(8)
        if r.i >= header_end:
            break
        code = r.u8()
        sig = r.g()
        v, _ = r.value(sig)
        fields[code] = v
    return Message(mtype, serial, fields, data[body_start:total], little), total


class LiteBus:
    """Minimal session-bus connection: own a name, receive one string-bearing call."""

    def __init__(self, env: Optional[Mapping[str, str]] = None, timeout: float = 5.0):
        self.env = env
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.unique = ""
        self.serial = 0
        self.buf = bytearray()

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> "LiteBus":
        path = session_bus_address(self.env)
        if not path:
            raise OSError("no session bus address (DBUS_SESSION_BUS_ADDRESS unset)")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(path)
        self.sock = s
        uid_hex = str(os.getuid()).encode("ascii").hex()
        s.sendall(b"\0AUTH EXTERNAL " + uid_hex.encode("ascii") + b"\r\n")
        line = self._read_line()
        if not line.startswith(b"OK"):
            s.sendall(b"AUTH ANONYMOUS\r\n")
            line = self._read_line()
            if not line.startswith(b"OK"):
                raise OSError(f"D-Bus auth failed: {line!r}")
        s.sendall(b"BEGIN\r\n")
        reply = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "Hello")
        self.unique = str(reply.args()[0]) if reply and reply.args() else ""
        return self

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self) -> "LiteBus":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- protocol ----------------------------------------------------------
    def _read_line(self) -> bytes:
        assert self.sock is not None
        out = bytearray()
        while not out.endswith(b"\r\n"):
            chunk = self.sock.recv(1)
            if not chunk:
                raise OSError("D-Bus connection closed during auth")
            out += chunk
        return bytes(out[:-2])

    def _next_serial(self) -> int:
        self.serial += 1
        return self.serial

    def _send(self, data: bytes) -> None:
        assert self.sock is not None
        self.sock.sendall(data)

    def _recv_message(self, deadline: float) -> Optional[Message]:
        assert self.sock is not None
        while True:
            msg, used = parse_message(bytes(self.buf))
            if msg is not None:
                del self.buf[:used]
                return msg
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self.sock.settimeout(min(remaining, self.timeout))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise OSError("D-Bus connection closed")
            self.buf += chunk

    def _call(self, dest: str, path: str, iface: str, member: str, sig: str = "", args: tuple = ()) -> Optional[Message]:
        serial = self._next_serial()
        fields: list[tuple[int, str, Any]] = [
            (_H_PATH, "o", path), (_H_DEST, "s", dest), (_H_IFACE, "s", iface), (_H_MEMBER, "s", member),
        ]
        body = b""
        if sig:
            fields.append((_H_SIG, "g", sig))
            body = marshal_body(sig, args)
        self._send(build_message(_METHOD_CALL, serial, fields, body))
        deadline = time.monotonic() + self.timeout
        while True:
            msg = self._recv_message(deadline)
            if msg is None:
                raise TimeoutError(f"no reply to {iface}.{member}")
            if msg.mtype in (_METHOD_RETURN, _ERROR) and msg.fields.get(_H_REPLY_SERIAL) == serial:
                if msg.mtype == _ERROR:
                    raise OSError(f"D-Bus error {msg.fields.get(_H_ERROR)} for {member}")
                return msg
            self._handle_incidental(msg)

    def _handle_incidental(self, msg: Message) -> None:
        """Reply to Ping/introspection-ish calls so the bus never thinks we hung."""
        if msg.mtype == _METHOD_CALL:
            self._reply(msg)

    def _reply(self, msg: Message, sig: str = "", args: tuple = ()) -> None:
        fields: list[tuple[int, str, Any]] = [(_H_REPLY_SERIAL, "u", msg.serial)]
        if msg.sender:
            fields.append((_H_DEST, "s", msg.sender))
        body = b""
        if sig:
            fields.append((_H_SIG, "g", sig))
            body = marshal_body(sig, args)
        self._send(build_message(_METHOD_RETURN, self._next_serial(), fields, body))

    def request_name(self, name: str) -> bool:
        reply = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                           "RequestName", "su", (name, 4))  # 4 = DBUS_NAME_FLAG_DO_NOT_QUEUE
        code = reply.args()[0] if reply and reply.args() else 0
        return code in (1, 4)  # PRIMARY_OWNER or ALREADY_OWNER

    def wait_for_call(self, member: str, timeout: Optional[float] = None) -> Optional[list[Any]]:
        """Block until a METHOD_CALL named ``member`` arrives; returns its arguments."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            msg = self._recv_message(deadline)
            if msg is None:
                return None
            if msg.mtype == _METHOD_CALL and msg.member == member:
                args = msg.args()
                self._reply(msg)
                return args
            self._handle_incidental(msg)


__all__ = [
    "session_bus_address", "build_message", "marshal_body", "parse_message", "Message", "LiteBus",
]
