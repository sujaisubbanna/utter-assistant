#!/usr/bin/env python3
"""Cross-platform runner transport: Unix byte-identical, Windows/TCP token auth.

Runs on Linux by forcing ``UTTER_RUNNER_TRANSPORT=tcp`` (so the Windows path is
exercised without Windows). Covers:

  (a) ``_authorize_tcp`` is token-only; same-uid/binaries never grant over TCP
  (b) loopback round trip: pre-auth denied, wrong token denied, good token ok
  (c) ``default_socket_path()`` Windows-shaped (endpoint file) / Unix unchanged
  (d) token store idempotent
  (e) ``fd.pass`` -> ``-32005`` on TCP
  (f) ``check_config`` rejects Windows-unsupported keys
  (g) the Unix default path and peer-cred path are untouched

Usage::

    .venv-agent/bin/python tests/test_runner_transport.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}{(' -> ' + extra) if extra and not cond else ''}")


class env:
    """Context manager setting/removing env vars (None = remove) and restoring."""

    def __init__(self, **kw):
        self.kw = kw
        self.saved: dict = {}

    def __enter__(self):
        for key, value in self.kw.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


from runner import platform as rplatform  # noqa: E402
from runner import socket as rsock  # noqa: E402
from runner import tokenstore  # noqa: E402
from runner import rpc  # noqa: E402


async def handler(method, params, peer):
    return {"ok": True}


# --------------------------------------------------------------------------- #
# (a) TCP authorization is token-only
# --------------------------------------------------------------------------- #
async def test_authorize_tcp() -> None:
    base = rsock.SocketServer("/tmp/x.endpoint", handler, transport="tcp")
    allowed, needs_auth, why = base._authorize_tcp(("127.0.0.1", 1234))
    check("tcp: no token -> default-deny", allowed is False and "default-deny" in why, why)

    withtok = rsock.SocketServer("/tmp/x.endpoint", handler, transport="tcp", token="t")
    allowed, needs_auth, _ = withtok._authorize_tcp(("127.0.0.1", 1234))
    check("tcp: token -> allowed + needs auth", allowed is True and needs_auth is True)

    creds = rsock.SocketServer(
        "/tmp/x.endpoint", handler, transport="tcp",
        allow_same_uid=True, allow_binaries=["python"],
    )
    allowed, _, why = creds._authorize_tcp(("127.0.0.1", 1234))
    check("tcp: same-uid/binaries never grant without a token", allowed is False, why)

    check("tcp: supports_fd_pass is False",
          rsock.SocketServer("/tmp/x.endpoint", handler, transport="tcp").supports_fd_pass is False)
    check("unix: supports_fd_pass is True",
          rsock.SocketServer("/tmp/x.sock", handler, transport="unix").supports_fd_pass is True)


# --------------------------------------------------------------------------- #
# (b) same-host round trip + (e) fd.pass over TCP
# --------------------------------------------------------------------------- #
async def _call(host: str, port: int, method: str, params: dict | None = None):
    reader, writer = await asyncio.open_connection(host, port)
    peer = rpc.RpcPeer(reader, writer, name="tcp-client")
    peer.start()
    try:
        return await peer.call(method, params or {}, timeout_ms=2000)
    finally:
        await peer.aclose()


async def _authed_call(host: str, port: int, token: str, method: str, params: dict | None = None):
    reader, writer = await asyncio.open_connection(host, port)
    peer = rpc.RpcPeer(reader, writer, name="tcp-client")
    peer.start()
    try:
        await peer.call("runner.auth", {"token": token}, timeout_ms=2000)
        return await peer.call(method, params or {}, timeout_ms=2000)
    finally:
        await peer.aclose()


async def test_tcp_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        endpoint = os.path.join(tmp, "runner.endpoint")
        token_file = os.path.join(tmp, "runner-token")
        srv = rsock.SocketServer(
            endpoint, handler, transport="tcp", token="correct-horse", token_path=token_file
        )
        await srv.start()
        try:
            ep = tokenstore.read_endpoint(endpoint)
            assert ep is not None
            check("tcp: endpoint file written",
                  ep.get("host") == "127.0.0.1" and isinstance(ep.get("port"), int),
                  repr(ep))
            host, port = ep["host"], ep["port"]

            # before auth -> denied
            try:
                await _call(host, port, "runner.status")
                check("tcp: runner.status before auth is denied", False)
            except rpc.RpcError as exc:
                check("tcp: runner.status before auth is denied",
                      exc.code == rpc.PERMISSION_DENIED, f"code={exc.code}")

            # wrong token -> denied
            try:
                await _call(host, port, "runner.auth", {"token": "wrong"})
                check("tcp: wrong token denied", False)
            except rpc.RpcError as exc:
                check("tcp: wrong token denied", exc.code == rpc.PERMISSION_DENIED, f"code={exc.code}")

            # correct token -> ok, then an authorized request succeeds
            auth = await _call(host, port, "runner.auth", {"token": "correct-horse"})
            check("tcp: correct token accepted", auth == {}, repr(auth))
            status = await _authed_call(host, port, "correct-horse", "runner.status")
            check("tcp: authenticated request succeeds", status == {"ok": True}, repr(status))

            # fd.pass unavailable -> -32005 even after auth
            try:
                await _authed_call(host, port, "correct-horse", "fd.pass",
                                   {"kind": "memfd", "meta": {}})
                check("tcp: fd.pass rejected -32005", False)
            except rpc.RpcError as exc:
                check("tcp: fd.pass rejected -32005", exc.code == rpc.DEGRADED, f"code={exc.code}")
        finally:
            await srv.stop()
        check("tcp: stop removes the endpoint file", not os.path.exists(endpoint))
        check("tcp: client token file was persisted",
              tokenstore.read_token(token_file) == "correct-horse")


# --------------------------------------------------------------------------- #
# (c) default_socket_path + (d) token store
# --------------------------------------------------------------------------- #
def test_default_socket_path() -> None:
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / "LocalAppData"
        with env(UTTER_PLATFORM="windows", LOCALAPPDATA=str(local),
                 UTTER_RUNNER_TRANSPORT=None, UTTER_RUNNER_SOCK=None):
            got = rsock.default_socket_path()
            check("win: default_socket_path -> %LOCALAPPDATA%/utter/runner.endpoint",
                  got == str(local / "utter" / "runner.endpoint"), got)
        with env(UTTER_PLATFORM="linux", UTTER_RUNNER_TRANSPORT=None,
                 UTTER_RUNNER_SOCK=None, XDG_RUNTIME_DIR=td):
            got = rsock.default_socket_path()
            check("linux: default_socket_path unchanged (runner.sock)",
                  got == str(Path(td) / "utter" / "runner.sock"), got)
        # override env still wins
        with env(UTTER_PLATFORM="windows", UTTER_RUNNER_SOCK="/tmp/custom.ep"):
            check("UTTER_RUNNER_SOCK override wins", rsock.default_socket_path() == "/tmp/custom.ep")


def test_tokenstore() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "runner-token"
        first = tokenstore.load_or_create_token(path)
        second = tokenstore.load_or_create_token(path)
        check("tokenstore: idempotent", bool(first) and first == second, f"{first!r} vs {second!r}")
        check("tokenstore: token file has the token", tokenstore.read_token(path) == first)
        check("tokenstore: token is high-entropy length",
              len(first) >= 32)
        # explicit token persists and is reused
        tokenstore.ensure_token(path, "fixed-token")
        check("tokenstore: explicit token persisted",
              tokenstore.read_token(path) == "fixed-token"
              and tokenstore.load_or_create_token(path) == "fixed-token")
        ep = Path(td) / "runner.endpoint"
        tokenstore.write_endpoint(ep, "127.0.0.1", 4321)
        check("tokenstore: endpoint round trip",
              tokenstore.read_endpoint(ep) == {"host": "127.0.0.1", "port": 4321})
        tokenstore.remove_endpoint(ep)
        check("tokenstore: endpoint removed", tokenstore.read_endpoint(ep) is None)


# --------------------------------------------------------------------------- #
# (f) check_config rejects Windows/TCP-unsupported keys
# --------------------------------------------------------------------------- #
def test_check_config() -> None:
    from runner.config import check_config

    bad = """
[[plugin]]
id = "p1"
kind = "action"
transport = "connect"
entrypoint = ["python", "-c", "pass"]

[runner]
socket_transport = "tcp"

[socket]
allow_same_uid = true
allow_binaries = ["python"]
"""
    good = """
[[plugin]]
id = "p1"
kind = "action"
transport = "stdio"
entrypoint = ["python", "-c", "pass"]

[runner]
socket_transport = "tcp"

[socket]
token = "s3cret"
"""
    with tempfile.TemporaryDirectory() as td:
        bad_path = Path(td) / "bad.toml"
        bad_path.write_text(bad)
        good_path = Path(td) / "good.toml"
        good_path.write_text(good)
        with env(UTTER_PLATFORM="linux", UTTER_RUNNER_TRANSPORT=None):
            ok_bad, msgs = check_config(bad_path)
            joined = "\n".join(msgs)
            check("check_config: tcp rejects allow_same_uid/allow_binaries + connect",
                  ok_bad is False
                  and "allow_same_uid" in joined and "allow_binaries" in joined
                  and "transport 'connect'" in joined, joined)
            ok_good, msgs_good = check_config(good_path)
            check("check_config: tcp token + stdio passes",
                  ok_good is True, "\n".join(msgs_good))


# --------------------------------------------------------------------------- #
async def _amain() -> int:
    await test_authorize_tcp()
    await test_tcp_round_trip()
    test_default_socket_path()
    test_tokenstore()
    test_check_config()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_amain()))
