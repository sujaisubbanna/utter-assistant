"""Runner self-tests (unit + optional end-to-end).

Run:  python -m runner._selftest            # unit tests
      python -m runner._selftest --e2e      # unit tests + socket demo
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import socket as _socket
import sys
import tempfile

from . import fdpass, framing, handles, policy, rpc, security
from .host import Host, RunnerConfig
from .plugin import PluginConfig, PluginInstance, RUNNER_CAPS
from .policy import ConfirmationRequired, Provenance
from .socket import SocketServer
from .streams import StreamManager

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    RESULTS.append((name, bool(cond), extra))


class _CollectWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, chunk: bytes) -> None:
        self.data += chunk

    async def drain(self) -> None:
        return None


def _reader_from(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def _peers(**kw):
    s1, s2 = _socket.socketpair()
    r1, w1 = await asyncio.open_connection(sock=s1)
    r2, w2 = await asyncio.open_connection(sock=s2)
    return r1, w1, r2, w2


# --------------------------------------------------------------------------- #
# framing
# --------------------------------------------------------------------------- #
async def test_framing() -> None:
    msg = {"text": "line\nbreak \u00e9\u4e2d\u6587", "n": 1, "nested": [1, 2, 3]}
    writer = _CollectWriter()
    await framing.write_message(writer, msg)
    check("framing: header is Content-Length", bytes(writer.data).startswith(b"Content-Length: "))
    got = await framing.read_message(_reader_from(bytes(writer.data)))
    check("framing: round-trip (\\n + non-ASCII)", got == msg)

    for label, raw in {
        "missing Content-Length": b"Foo: bar\r\n\r\n{}",
        "truncated body": b"Content-Length: 10\r\n\r\nabc",
        "bad JSON": b"Content-Length: 3\r\n\r\nabc",
        "bad Content-Length": b"Content-Length: xx\r\n\r\n{}",
    }.items():
        try:
            await framing.read_message(_reader_from(raw))
            check(f"framing: {label} raises FramingError", False)
        except framing.FramingError:
            check(f"framing: {label} raises FramingError", True)


# --------------------------------------------------------------------------- #
# rpc
# --------------------------------------------------------------------------- #
async def test_rpc_correlation() -> None:
    r1, w1, r2, w2 = await _peers()

    async def on_req(method, params, rid=None):
        if method == "echo":
            return {"echo": params}
        raise rpc.RpcError(rpc.METHOD_NOT_FOUND, "nope")

    a = rpc.RpcPeer(r1, w1, name="a")
    b = rpc.RpcPeer(r2, w2, name="b", on_request=on_req)
    a.start()
    b.start()
    res = await a.call("echo", {"x": 1}, timeout_ms=1000)
    check("rpc: id correlation", res == {"echo": {"x": 1}})
    res2 = await a.call("echo", {"y": [1, 2]}, timeout_ms=1000)
    check("rpc: sequential ids", res2 == {"echo": {"y": [1, 2]}})
    await a.aclose()
    await b.aclose()


async def test_rpc_errors() -> None:
    r1, w1, r2, w2 = await _peers()

    async def on_req(method, params, rid=None):
        if method == "boom":
            raise rpc.RpcError(rpc.PLUGIN_ERROR, "kaboom")
        if method == "echo":
            return {"echo": params}
        raise rpc.RpcError(rpc.METHOD_NOT_FOUND, f"method not found: {method}")

    a = rpc.RpcPeer(r1, w1, name="a")
    b = rpc.RpcPeer(r2, w2, name="b", on_request=on_req)
    a.start()
    b.start()
    try:
        await a.call("boom", {}, timeout_ms=1000)
        check("rpc: error propagates", False)
    except rpc.RpcError as exc:
        check("rpc: error propagates", exc.code == rpc.PLUGIN_ERROR and exc.message == "kaboom")
    try:
        await a.call("missing", {}, timeout_ms=300)
        check("rpc: method not found", False)
    except rpc.RpcError as exc:
        check("rpc: method not found", exc.code == rpc.METHOD_NOT_FOUND)
    await a.aclose()
    await b.aclose()


async def test_rpc_timeout() -> None:
    r1, w1, r2, w2 = await _peers()

    async def slow(method, params, rid=None):
        await asyncio.sleep(5)
        return "late"

    a = rpc.RpcPeer(r1, w1, name="a")
    b = rpc.RpcPeer(r2, w2, name="b", on_request=slow)
    a.start()
    b.start()
    try:
        await a.call("slow", {}, timeout_ms=60)
        check("rpc: timeout -> -32001", False)
    except rpc.RpcError as exc:
        check("rpc: timeout -> -32001", exc.code == rpc.TIMEOUT, exc.message)
    await a.aclose()
    await b.aclose()


async def test_rpc_cancel() -> None:
    r1, w1, r2, w2 = await _peers()

    async def slow(method, params, rid=None):
        await asyncio.sleep(5)
        return "late"

    a = rpc.RpcPeer(r1, w1, name="a")
    b = rpc.RpcPeer(r2, w2, name="b", on_request=slow)
    a.start()
    b.start()
    task = asyncio.create_task(a.call("slow", {}, request_id="0:1"))
    await asyncio.sleep(0.05)
    await b.notify("$/cancel", {"id": "0:1"})
    try:
        await task
        check("rpc: $/cancel -> -32002", False)
    except rpc.RpcError as exc:
        check("rpc: $/cancel -> -32002", exc.code == rpc.CANCELLED, exc.message)
    await b.notify("$/cancel", {"id": "0:1"})
    await b.notify("$/cancel", {"id": "does-not-exist"})
    check("rpc: $/cancel idempotent", True)
    await a.aclose()
    await b.aclose()


async def test_rpc_stale_epoch() -> None:
    peer = rpc.RpcPeer(None, _CollectWriter(), epoch=2, name="stale")
    peer._handle_response({"jsonrpc": "2.0", "id": "1:9", "result": 123})
    check("rpc: stale-epoch response dropped", peer.stale_rejected == 1)
    peer._handle_response({"jsonrpc": "2.0", "id": "2:9", "result": 123})
    check("rpc: current-epoch response accepted", peer.stale_rejected == 1)

    peer2 = rpc.RpcPeer(None, _CollectWriter(), epoch=1, name="stale2")
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    peer2._pending["0:1"] = fut
    peer2._handle_response({"jsonrpc": "2.0", "id": "0:1", "result": 42})
    check("rpc: stale id does not resolve pending", not fut.done())


# --------------------------------------------------------------------------- #
# handles
# --------------------------------------------------------------------------- #
async def test_handles() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = handles.HandleStore(tmp, default_ttl=100)
        payload = b"hello utter"
        handle = store.create(payload, scope="p1")
        check("handles: handle://<sha256> format",
              handle.startswith("handle://") and len(handle) == len("handle://") + 64)
        check("handles: stat size", store.stat(handle, "p1")["size"] == len(payload))
        check("handles: fetch bytes", store.fetch(handle, "p1") == b"hello utter")
        try:
            store.fetch(handle, "p2")
            check("handles: plugin-scoped (cross-scope denied)", False)
        except handles.HandleError as exc:
            check("handles: plugin-scoped (cross-scope denied)", exc.code == rpc.PLUGIN_ERROR)
        for bad in ("/etc/passwd", "handle://../../etc/passwd", "handle://deadbeef", ""):
            try:
                store.fetch(bad, "p1")
                check(f"handles: rejects {bad!r}", False)
            except handles.HandleError:
                check(f"handles: rejects {bad!r}", True)
        check("handles: refcount retained", store.stat(handle, "p1")["refcount"] == 1)
        check("handles: gc keeps referenced", store.gc() == 0)
        store.release(handle, "p1")
        check("handles: gc reclaims unreferenced", store.gc() == 1)
        try:
            store.fetch(handle, "p1")
            check("handles: gc removed bytes", False)
        except handles.HandleError:
            check("handles: gc removed bytes", True)


async def test_handle_client_api() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        host = Host(RunnerConfig(), handle_root=tmp)
        created = host.handle_create({"data": "utter inline handle"})
        handle = created["handle"]
        check("handles: client handle.create", handle.startswith("handle://"))
        fetched = host.handle_fetch({"handle": handle})
        data = base64.b64decode(fetched["data_b64"])
        check("handles: handle.fetch inline hash match",
              data == b"utter inline handle" and fetched["sha256"] == handle.rsplit("/", 1)[-1])
        check("handles: handle.stat", host.handle_stat({"handle": handle})["size"] == len(data))
        big = host.handle_create({"size": 70000})
        try:
            host.handle_fetch({"handle": big["handle"]})
            check("handles: >64KiB -> -32007", False)
        except rpc.RpcError as exc:
            check("handles: >64KiB -> -32007", exc.code == rpc.HANDLE_TOO_LARGE, exc.message)
        # fd.pass resolves a handle to a real descriptor
        reply = host.fd_pass({"kind": "handle", "meta": {"handle": handle}})
        try:
            check("handles: fd.pass handle -> fd", os.read(reply.fd, 64) == b"utter inline handle")
        finally:
            os.close(reply.fd)
        mem = host.fd_pass({"kind": "memfd", "meta": {"data": "fd payload", "size": 4096}})
        try:
            check("handles: fd.pass memfd", os.read(mem.fd, 64).startswith(b"fd payload"))
        finally:
            os.close(mem.fd)


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #
async def test_policy() -> None:
    pol = policy.Policy()
    try:
        pol.validate("ensure_url", {"url": "https://x.com"}, Provenance.SCREEN)
        check("policy: screen concrete arg -> -32006", False)
    except policy.PolicyError as exc:
        check("policy: screen concrete arg -> -32006", exc.code == rpc.UNTRUSTED_ARG, exc.message)
    pol.validate("ensure_url", {"url": "https://x.com"}, Provenance.USER)
    check("policy: user open_url allowed", True)
    try:
        pol.validate("open_url", {"url": "file:///etc/passwd"}, Provenance.USER)
        check("policy: bad scheme denied (-32003)", False)
    except policy.PolicyError as exc:
        check("policy: bad scheme denied (-32003)", exc.code == rpc.PERMISSION_DENIED)
    try:
        pol.validate("terminal", {"command": "ls"}, Provenance.USER)
        check("policy: action.terminal off by default (-32003)", False)
    except policy.PolicyError as exc:
        check("policy: action.terminal off by default (-32003)", exc.code == rpc.PERMISSION_DENIED)

    enabled = policy.Policy(enabled_ops=["action.terminal"])
    try:
        enabled.validate("terminal", {"command": "ls"}, Provenance.USER)
        check("policy: terminal requires confirmation", False)
    except ConfirmationRequired as need:
        check("policy: terminal requires confirmation",
              need.op == "terminal" and "ls" in need.summary, need.summary)
    enabled.validate("terminal", {"command": "ls"}, Provenance.USER, confirmed=True)
    check("policy: terminal allowed after confirmation", True)
    try:
        enabled.validate("terminal", {"command": "rm -rf /"}, Provenance.SCREEN)
        check("policy: screen terminal -> -32006 even when enabled", False)
    except policy.PolicyError as exc:
        check("policy: screen terminal -> -32006 even when enabled", exc.code == rpc.UNTRUSTED_ARG)
    try:
        pol.validate("nope", {}, Provenance.USER)
        check("policy: unknown op -> -32601", False)
    except policy.PolicyError as exc:
        check("policy: unknown op -> -32601", exc.code == rpc.METHOD_NOT_FOUND)


# --------------------------------------------------------------------------- #
# streams
# --------------------------------------------------------------------------- #
class _FakePlugin:
    def __init__(self, plugin_id: str = "p"):
        self.id = plugin_id
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method, params=None, *, timeout_ms=None):
        self.calls.append((method, params or {}))
        if method == "stream.subscribe":
            return {"stream_id": "ps1"}
        return {}


class _FakePeer:
    def __init__(self):
        self.messages: list[tuple[str, dict]] = []

    async def notify(self, method, params=None):
        self.messages.append((method, params or {}))


async def test_streams_lossy() -> None:
    mgr = StreamManager(lossy_queue=3)
    plugin, peer = _FakePlugin(), _FakePeer()
    sub = await mgr.subscribe(plugin, "test.frames", {}, "lossy", peer, start_writer=False)
    sid = sub["stream_id"]
    for i in range(1, 6):
        await mgr.deliver("p", "test.frames", {"stream_id": "ps1", "seq": i, "data": i})
    stats = mgr.stats(sid) or {}
    check("streams: lossy bounded queue", stats.get("queued") == 3, str(stats))
    check("streams: lossy drop-oldest", stats.get("dropped") == 2, str(stats))
    retained = [e["seq"] for e in mgr.peek(sid)]
    check("streams: lossy retains newest", retained == [3, 4, 5], str(retained))
    await mgr.stop(sid)


async def test_streams_reliable() -> None:
    mgr = StreamManager(credit_window=2)
    plugin, peer = _FakePlugin(), _FakePeer()
    sub = await mgr.subscribe(plugin, "test.frames", {}, "reliable", peer, start_writer=False)
    sid = sub["stream_id"]
    for i in range(1, 4):
        await mgr.deliver("p", "test.frames", {"stream_id": "ps1", "seq": i, "data": i})
    stats = mgr.stats(sid) or {}
    check("streams: reliable pauses at credit window",
          bool(stats.get("credits") == 0 and stats.get("queued") == 2
               and stats.get("held") == 1 and stats.get("paused")),
          str(stats))
    mgr.ack(sid, 2)
    stats = mgr.stats(sid) or {}
    check("streams: reliable resumes after ack",
          stats.get("queued") == 3 and stats.get("held") == 0 and not stats.get("paused"),
          str(stats))
    await mgr.stop(sid)


async def test_streams_relay() -> None:
    mgr = StreamManager()
    plugin, peer = _FakePlugin(), _FakePeer()
    sub = await mgr.subscribe(plugin, "test.frames", {"x": 1}, "lossy", peer)
    sid = sub["stream_id"]
    await mgr.deliver("p", "test.frames", {"stream_id": "ps1", "seq": 7, "data": "a"})
    await asyncio.sleep(0.02)
    check("streams: relayed to client",
          bool(peer.messages) and peer.messages[0][0] == "test.frames"
          and peer.messages[0][1]["stream_id"] == sid and peer.messages[0][1]["seq"] == 7,
          str(peer.messages))
    check("streams: stop calls plugin stream.stop",
          await mgr.stop(sid) and any(m == "stream.stop" for m, _ in plugin.calls))
    check("streams: stop idempotent", await mgr.stop(sid) is False)


# --------------------------------------------------------------------------- #
# security
# --------------------------------------------------------------------------- #
async def test_security() -> None:
    ok_probe = lambda argv: True  # noqa: E731
    sysd = security.detect_wrapper(
        which=lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None, probe=ok_probe)
    check("security: prefers systemd-run", sysd.kind == "systemd-run" and sysd.enforced)
    bwrap = security.detect_wrapper(
        which=lambda n: "/usr/bin/bwrap" if n == "bwrap" else None, probe=ok_probe)
    check("security: falls back to bwrap", bwrap.kind == "bwrap" and bwrap.enforced)
    fallback = security.detect_wrapper(
        which=lambda n: f"/usr/bin/{n}" if n in ("systemd-run", "bwrap") else None,
        probe=lambda argv: argv[0] == "bwrap")
    check("security: falls back when systemd-run fails", fallback.kind == "bwrap")
    none = security.detect_wrapper(which=lambda n: None, probe=ok_probe)
    check("security: no wrapper -> advisory", none.kind is None and not none.enforced)
    argv = security.plugin_argv(["python", "-m", "x"], sysd, plugin_id="p")
    check("security: wrapper argv",
          argv[0] == "systemd-run" and "--" in argv and argv[-1] == "x", str(argv))
    perms = security.permission_status(["filesystem.read", "weird"], sysd)
    check("security: permission enforced/advisory",
          perms[0]["enforced"] is True and perms[1]["enforced"] is False, str(perms))
    perms2 = security.permission_status(["filesystem.read"], none)
    check("security: unwrapped permissions advisory", perms2[0]["enforced"] is False)


# --------------------------------------------------------------------------- #
# fd passing
# --------------------------------------------------------------------------- #
async def test_fdpass() -> None:
    a, b = _socket.socketpair()
    try:
        fd = os.memfd_create("selftest-fd", 0)
        os.write(fd, b"fd-payload")
        os.lseek(fd, 0, 0)
        fdpass.send_fds(a, [fd], b"hello")
        os.close(fd)
        data, fds = fdpass.recv_fds(b)
        check("fdpass: payload + fd round trip",
              data == b"hello" and len(fds) == 1 and os.read(fds[0], 64) == b"fd-payload")
        fdpass.close_all(fds)
    finally:
        a.close()
        b.close()


async def test_fd_pass_over_socket() -> None:
    async def handler(method, params, peer):
        if method == "fd.pass":
            fd = os.memfd_create("selftest-sock", 0)
            os.write(fd, b"fd-over-socket")
            os.lseek(fd, 0, 0)
            return fdpass.FdReply(fd, {"ok": True})
        return {}

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "fd.sock")
        srv = SocketServer(path, handler, allow_same_uid=True)
        await srv.start()
        try:
            def client():
                sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(path)
                sock.sendall(framing.encode({
                    "jsonrpc": "2.0", "id": 1, "method": "fd.pass",
                    "params": {"kind": "memfd", "meta": {"data": "x"}},
                }))
                data, fds = fdpass.recv_fds(sock)
                sock.close()
                return data, fds

            data, fds = await asyncio.to_thread(client)
            ok = bool(fds) and os.read(fds[0], 64) == b"fd-over-socket"
            fdpass.close_all(fds)
            check("fdpass: fd.pass over socket (SCM_RIGHTS)", ok, f"fds={len(fds)}")
        finally:
            await srv.stop()


async def test_enforce_reporting() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        host = Host(RunnerConfig(security_enforce=True), handle_root=tmp)
        check("security: enforce=true selects a wrapper", host._security_wrapper.enforced)
        inst = PluginInstance(PluginConfig(id="p", permissions=["filesystem.read", "weird"]))
        inst.status = "ok"
        host.plugins.append(inst)
        report = host.validate_plugin({"plugin": "p"})
        perms = {p["name"]: p["enforced"] for p in report["permissions"]}
        check("security: validate_plugin reports enforced",
              perms.get("filesystem.read") is True and perms.get("weird") is False, str(perms))


async def test_enforce_spawn() -> None:
    wrapper = security.detect_wrapper()
    if not wrapper.enforced:
        check("security: enforce spawn (no wrapper available)", True)
        return
    inst = PluginInstance(PluginConfig(id="enforced", kind="action", entrypoint=_echo_entry("action")))
    try:
        await inst.start(available=RUNNER_CAPS, timeout_ms=8000, wrapper=wrapper)
        check("security: enforce=true spawns under wrapper", inst.status == "ok", inst.status)
    finally:
        await inst.stop()


# --------------------------------------------------------------------------- #
# socket auth
# --------------------------------------------------------------------------- #
async def test_socket_authorize() -> None:
    async def handler(method, params, peer):
        return {}

    uid = os.getuid()
    exe = "/usr/bin/python3.14"
    check("socket: default-deny",
          SocketServer("/tmp/x.sock", handler)._authorize_creds(1, uid, exe)[0] is False)
    check("socket: allow_same_uid accepts",
          SocketServer("/tmp/x.sock", handler, allow_same_uid=True)._authorize_creds(1, uid, exe)[0] is True)
    check("socket: allow_binaries prefix match",
          SocketServer("/tmp/x.sock", handler, allow_binaries=["python"])._authorize_creds(1, uid, exe)[0] is True)
    check("socket: unlisted binary rejected",
          SocketServer("/tmp/x.sock", handler, allow_binaries=["other"])._authorize_creds(1, uid, exe)[0] is False)
    allowed, needs_auth, _ = SocketServer("/tmp/x.sock", handler, token="t")._authorize_creds(1, uid, exe)
    check("socket: token requires auth", allowed and needs_auth)
    check("socket: uid mismatch rejected",
          SocketServer("/tmp/x.sock", handler, allow_same_uid=True)._authorize_creds(1, uid + 1, exe)[0] is False)


async def test_socket_default_deny_e2e() -> None:
    async def handler(method, params, peer):
        return {"ok": True}

    with tempfile.TemporaryDirectory() as tmp:
        deny_path = os.path.join(tmp, "deny.sock")
        srv = SocketServer(deny_path, handler)  # default-deny
        await srv.start()
        try:
            reader, writer = await asyncio.open_unix_connection(deny_path)
            peer = rpc.RpcPeer(reader, writer, name="deny")
            peer.start()
            try:
                await peer.call("runner.status", {}, timeout_ms=1000)
                check("socket: default-deny rejects client", False)
            except (rpc.RpcError, asyncio.IncompleteReadError, ConnectionError, OSError):
                check("socket: default-deny rejects client", True)
            await peer.aclose()
        finally:
            await srv.stop()

        allow_path = os.path.join(tmp, "allow.sock")
        srv2 = SocketServer(allow_path, handler, allow_same_uid=True)
        await srv2.start()
        try:
            reader, writer = await asyncio.open_unix_connection(allow_path)
            peer = rpc.RpcPeer(reader, writer, name="allow")
            peer.start()
            res = await peer.call("runner.status", {}, timeout_ms=1000)
            check("socket: allow_same_uid accepts client", res == {"ok": True})
            await peer.aclose()
        finally:
            await srv2.stop()


# --------------------------------------------------------------------------- #
# plugin handshake / restart / socket transport
# --------------------------------------------------------------------------- #
def _echo_entry(kind: str, socket_transport: bool = False) -> list[str]:
    entry = [sys.executable, "-m", "runner._test_echo_plugin", "--kind", kind]
    if socket_transport:
        entry.append("--socket-transport")
    return entry


async def test_plugin_handshake() -> None:
    inst = PluginInstance(PluginConfig(id="t-action", kind="action", entrypoint=_echo_entry("action")))
    try:
        await inst.start(available=RUNNER_CAPS, timeout_ms=5000)
        check("plugin: handshake status ok", inst.status == "ok", inst.status)
        check("plugin: provides parsed", "action.open_url@1" in inst.provides)
        check("plugin: describe methods", "action.invoke" in inst.methods)
        epoch0 = inst.epoch
        await inst.restart(available=RUNNER_CAPS, timeout_ms=5000)
        check("plugin: restart increments epoch", inst.epoch == epoch0 + 1 and inst.status == "ok")
    finally:
        await inst.stop()

    bad = PluginInstance(PluginConfig(id="t-bad", kind="router", entrypoint=[
        sys.executable, "-m", "runner._test_echo_plugin", "--kind", "bogus"]))
    try:
        await bad.start(available=RUNNER_CAPS, timeout_ms=3000)
        check("plugin: bad entrypoint fails", False)
    except Exception:
        check("plugin: bad entrypoint fails", True)
    finally:
        await bad.stop()


async def test_plugin_socket_transport() -> None:
    for transport in ("listen", "connect"):
        inst = PluginInstance(PluginConfig(
            id=f"sock-{transport}", kind="action", transport=transport,
            entrypoint=_echo_entry("action", socket_transport=True),
        ))
        try:
            await inst.start(available=RUNNER_CAPS, timeout_ms=5000)
            check(f"plugin: {transport} handshake ok", inst.status == "ok", inst.status)
            res = await inst.call(
                "action.invoke",
                {"op": "ensure_url", "args": {"url": "https://x"}, "provenance": "user"},
                timeout_ms=3000,
            )
            check(f"plugin: {transport} invoke over socket", res.get("ok") is True, str(res))
        finally:
            await inst.stop()


# --------------------------------------------------------------------------- #
# end-to-end over the unix socket
# --------------------------------------------------------------------------- #
async def run_e2e() -> None:
    tmpdir = tempfile.mkdtemp(prefix="lav-e2e-")
    cfg = RunnerConfig(enabled_ops=["action.terminal"])
    cfg.socket_path = os.path.join(tmpdir, "runner.sock")
    cfg.plugins = [
        PluginConfig(id="echo-router", kind="router", entrypoint=_echo_entry("router")),
        PluginConfig(id="echo-action", kind="action", entrypoint=_echo_entry("action")),
    ]
    host = Host(cfg)
    await host.start()
    print("== runner.status ==")
    try:
        reader, writer = await asyncio.open_unix_connection(cfg.socket_path)
        confirms: list[dict] = []
        notes: list[tuple[str, dict]] = []

        async def on_req(method, params, rid=None):
            if method == "host.confirm":
                confirms.append(params)
                return {"approved": True}
            raise rpc.RpcError(rpc.METHOD_NOT_FOUND, method)

        async def on_note(method, params):
            notes.append((method, params))

        client = rpc.RpcPeer(reader, writer, name="e2e", on_request=on_req, on_notification=on_note)
        client.start()

        status = await client.call("runner.status", {}, timeout_ms=5000)
        print(json.dumps(status, indent=2))

        print("== runner.command {utterance: 'open youtube', provenance: 'user'} ==")
        cmd = await client.call(
            "runner.command", {"utterance": "open youtube", "provenance": "user"}, timeout_ms=5000
        )
        print(json.dumps(cmd, indent=2))

        print("== runner.command {utterance: 'run echo hi', provenance: 'user'} (terminal confirmed) ==")
        cmd_confirm = await client.call(
            "runner.command", {"utterance": "run echo hi", "provenance": "user"}, timeout_ms=5000
        )
        print(json.dumps(cmd_confirm, indent=2))
        print("host.confirm requests seen:", json.dumps(confirms, indent=2))

        print("== runner.command {utterance: 'run rm -rf /', provenance: 'screen'} ==")
        cmd_screen = await client.call(
            "runner.command", {"utterance": "run rm -rf /", "provenance": "screen"}, timeout_ms=5000
        )
        print(json.dumps(cmd_screen, indent=2))

        # M1: runner.invoke + validate_plugin
        invoked = await client.call(
            "runner.invoke",
            {"plugin": "echo-action", "method": "action.invoke",
             "params": {"op": "ensure_url", "args": {"url": "https://example.com"}, "provenance": "user"}},
            timeout_ms=5000,
        )
        print("== runner.invoke action.invoke ==", json.dumps(invoked))
        validated = await client.call("runner.validate_plugin", {"plugin": "echo-action"}, timeout_ms=5000)
        print("== runner.validate_plugin ==", json.dumps(validated))

        # M1: handle.create / handle.fetch
        created = await client.call("handle.create", {"data": "e2e handle"}, timeout_ms=5000)
        fetched = await client.call("handle.fetch", {"handle": created["handle"]}, timeout_ms=5000)
        print("== handle.create/fetch ==", json.dumps({"created": created, "fetched_size": fetched["size"]}))

        # M1: stream subscribe/relay/stop
        sub = await client.call(
            "stream.subscribe", {"method": "test.frames", "params": {"count": 5}, "mode": "lossy"},
            timeout_ms=5000,
        )
        await asyncio.sleep(0.25)
        stream_notes = [n for n in notes if n[0] == "test.frames" and n[1].get("stream_id") == sub["stream_id"]]
        print("== stream.subscribe ==", json.dumps({"sub": sub, "frames": len(stream_notes)}))
        await client.call("stream.stop", {"stream_id": sub["stream_id"]}, timeout_ms=5000)
        await client.call("stream.stop", {"stream_id": sub["stream_id"]}, timeout_ms=5000)

        if isinstance(status, dict) and status.get("plugins"):
            check("e2e: status lists plugins", len(status["plugins"]) == 2)
        first = (cmd.get("results") or [{}])[0]
        check("e2e: open youtube ok", first.get("ok") is True, json.dumps(first))
        denied = (cmd_screen.get("results") or [{}])[0]
        check("e2e: screen terminal rejected -32006",
              denied.get("ok") is False and (denied.get("error") or {}).get("code") == rpc.UNTRUSTED_ARG,
              json.dumps(denied))
        check("e2e: runner.invoke ok", invoked.get("ok") is True, json.dumps(invoked))
        check("e2e: validate_plugin ok", validated.get("ok") is True, json.dumps(validated))
        check("e2e: handle.fetch inline", fetched.get("size") == len("e2e handle"))
        check("e2e: stream relayed frames", len(stream_notes) > 0, f"frames={len(stream_notes)}")
        await client.aclose()
    finally:
        await host.stop()


# --------------------------------------------------------------------------- #
async def _amain(e2e: bool) -> int:
    await test_framing()
    await test_rpc_correlation()
    await test_rpc_errors()
    await test_rpc_timeout()
    await test_rpc_cancel()
    await test_rpc_stale_epoch()
    await test_handles()
    await test_handle_client_api()
    await test_policy()
    await test_streams_lossy()
    await test_streams_reliable()
    await test_streams_relay()
    await test_security()
    await test_fdpass()
    await test_fd_pass_over_socket()
    await test_enforce_reporting()
    await test_enforce_spawn()
    await test_socket_authorize()
    await test_socket_default_deny_e2e()
    await test_plugin_handshake()
    await test_plugin_socket_transport()

    if e2e:
        await run_e2e()

    failures = [r for r in RESULTS if not r[1]]
    print()
    for name, ok, extra in RESULTS:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  [{extra}]" if extra and not ok else ""))
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} checks passed")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="runner self-tests")
    parser.add_argument("--e2e", action="store_true", help="also run the socket end-to-end demo")
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args.e2e))


if __name__ == "__main__":
    raise SystemExit(main())
