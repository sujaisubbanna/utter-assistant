"""Plugin instance lifecycle: spawn, handshake, capabilities, epochs, restart.

Handshake (PROTOCOL.md §3, frozen)::

    runner -> plugin  protocol.hello {protocol, abi, runner, epoch}
    plugin -> runner  {protocol, abi, plugin{name,version,kind}, transport,
                       provides, requires, permissions}
    runner -> plugin  plugin.describe {} -> {methods, streams}
    runner -> plugin  plugin.health {}   -> {status, detail}

M1 transports (§12): ``stdio`` or ``connect``/``listen`` over
``$XDG_RUNTIME_DIR/utter/plugins/<id>.sock``. Capability rules (§8):
unknown capability -> warning; an unsatisfiable require -> error (fail closed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket as _socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import security
from .rpc import (
    RpcError,
    RpcPeer,
    DEGRADED,
    INCOMPATIBLE_VERSION,
    INVALID_PARAMS,
    PLUGIN_ERROR,
    TIMEOUT,
)

log = logging.getLogger("runner.plugin")

PROTOCOL_VERSION = "1.0"
ABI = 1
RUNNER_NAME = "utter-runner-py"

DEFAULT_CAPS_PATH = Path(__file__).resolve().parent.parent / "protocol" / "capabilities.json"

# capabilities the runner itself can always satisfy
RUNNER_CAPS = {"host.audio.ringbuffer@1", "host.fd.pass@1", "fs.tmp@1"}

SOCKET_TRANSPORTS = ("connect", "listen")


@dataclass
class PluginConfig:
    id: str
    kind: str = "action"
    runtime: str = "subprocess"
    transport: str = "stdio"
    entrypoint: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    enabled: bool = True
    # optional spawn overrides (M3): working directory + extra environment
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    # declared sandbox filesystem needs (applied by runner.security.plugin_argv)
    read_paths: list[str] = field(default_factory=list)
    write_paths: list[str] = field(default_factory=list)


def load_capabilities(path: str | os.PathLike | None = None) -> dict[str, dict]:
    p = Path(path) if path else DEFAULT_CAPS_PATH
    with open(p, "rb") as fh:
        data = json.load(fh)
    return dict(data.get("capabilities") or {})


def capability_report(
    provides: list[str],
    requires: list[str],
    available: set[str] | None = None,
    registry: dict[str, dict] | None = None,
) -> dict[str, list[str]]:
    """Classify capabilities: unknown (warning) and unsatisfiable requires."""
    registry = registry if registry is not None else load_capabilities()
    satisfiable = set(available or ()) | RUNNER_CAPS | set(provides)
    unknown = [
        c for c in list(provides) + list(requires)
        if c not in registry and not c.startswith("experimental/")
    ]
    missing = [c for c in requires if c not in satisfiable]
    return {"unknown_capabilities": unknown, "missing_requires": missing}


def validate_capabilities(
    provides: list[str],
    requires: list[str],
    available: set[str] | None = None,
    registry: dict[str, dict] | None = None,
) -> list[str]:
    """Return warnings; raise RpcError(DEGRADED) if a require cannot be met."""
    report = capability_report(provides, requires, available, registry)
    if report["missing_requires"]:
        raise RpcError(
            DEGRADED,
            "missing required capabilities: " + ", ".join(report["missing_requires"]),
            {"missing": report["missing_requires"]},
        )
    return [f"unknown capability {c!r}" for c in report["unknown_capabilities"]]


def plugin_socket_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    directory = Path(base) / "utter" / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def plugin_socket_path(plugin_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(plugin_id))[:128] or "plugin"
    return str(plugin_socket_dir() / f"{safe}.sock")


class PluginInstance:
    """One supervised plugin process (stdio or unix-socket transport)."""

    def __init__(self, spec: PluginConfig):
        self.spec = spec
        self.id = spec.id
        self.kind = spec.kind
        self.epoch = 0
        self.status = "created"
        self.provides: list[str] = []
        self.requires: list[str] = []
        self.permissions: list[str] = list(spec.permissions)
        self.methods: list[str] = []
        self.streams: list[str] = []
        self.health: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.info: dict[str, Any] = {}
        # async (plugin_id, method, params) -> None, set by the host for streams
        self.notify_handler: Any = None
        self._proc: asyncio.subprocess.Process | None = None
        self._peer: RpcPeer | None = None
        self._stderr_task: asyncio.Task | None = None
        self._listener: _socket.socket | None = None
        self._wrapper: security.Wrapper | None = None
        self._stopping = False

    # -- lifecycle -------------------------------------------------------- #
    async def start(
        self,
        *,
        available: set[str] | None = None,
        timeout_ms: int = 10000,
        wrapper: security.Wrapper | None = None,
    ) -> None:
        self._stopping = False
        self._wrapper = wrapper
        if self.spec.runtime != "subprocess":
            raise RpcError(INVALID_PARAMS, f"plugin {self.id}: runtime {self.spec.runtime!r} unsupported")
        if self.spec.transport not in ("stdio",) + SOCKET_TRANSPORTS:
            raise RpcError(INVALID_PARAMS, f"plugin {self.id}: transport {self.spec.transport!r} unsupported")
        if not self.spec.entrypoint:
            raise RpcError(INVALID_PARAMS, f"plugin {self.id}: empty entrypoint")
        self.status = "starting"
        try:
            if self.spec.transport == "stdio":
                await self._open_stdio(timeout_ms)
            else:
                await self._open_socket(timeout_ms)
            await self._handshake(available=available, timeout_ms=timeout_ms)
        except Exception:
            self.status = "error"
            await self.stop()
            raise

    async def restart(
        self,
        *,
        available: set[str] | None = None,
        timeout_ms: int = 10000,
        wrapper: security.Wrapper | None = None,
    ) -> None:
        await self.stop()
        self.epoch += 1
        log.info("plugin %s: restarting as epoch %d", self.id, self.epoch)
        await self.start(available=available, timeout_ms=timeout_ms, wrapper=wrapper)

    # -- transports ------------------------------------------------------- #
    def _base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        root = str(DEFAULT_CAPS_PATH.parent.parent)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        env.update({str(k): str(v) for k, v in (self.spec.env or {}).items()})
        return env

    async def _spawn(self, argv: list[str], env: dict[str, str], *, pipes: bool) -> asyncio.subprocess.Process:
        try:
            return await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if pipes else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE if pipes else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.spec.cwd or None,
            )
        except OSError as exc:
            raise RpcError(PLUGIN_ERROR, f"plugin {self.id}: spawn failed: {exc}") from exc

    def _new_peer(self, reader: Any, writer: Any, timeout_ms: int) -> RpcPeer:
        peer = RpcPeer(
            reader,
            writer,
            epoch=self.epoch,
            name=self.id,
            default_timeout_ms=timeout_ms,
            on_notification=self._handle_notification,
        )
        peer.start()
        return peer

    async def _open_stdio(self, timeout_ms: int) -> None:
        argv = security.plugin_argv(
            self.spec.entrypoint,
            self._wrapper,
            plugin_id=self.id,
            permissions=self.permissions,
            read_paths=self.spec.read_paths,
            write_paths=self.spec.write_paths,
        )
        self._proc = await self._spawn(argv, self._base_env(), pipes=True)
        self._stderr_task = asyncio.create_task(self._pump_stderr(), name=f"stderr-{self.id}")
        assert self._proc.stdout is not None and self._proc.stdin is not None
        self._peer = self._new_peer(self._proc.stdout, self._proc.stdin, timeout_ms)

    async def _open_socket(self, timeout_ms: int) -> None:
        transport = self.spec.transport
        path = plugin_socket_path(self.id)
        _unlink(path)
        env = self._base_env()
        env["UTTER_PLUGIN_ID"] = self.id
        env["UTTER_PLUGIN_SOCKET"] = path
        env["UTTER_PLUGIN_TRANSPORT"] = transport
        argv = security.plugin_argv(
            self.spec.entrypoint,
            self._wrapper,
            plugin_id=self.id,
            permissions=self.permissions,
            read_paths=self.spec.read_paths,
            write_paths=self.spec.write_paths,
        )
        if transport == "listen":
            self._proc = await self._spawn(argv, env, pipes=False)
            self._stderr_task = asyncio.create_task(self._pump_stderr(), name=f"stderr-{self.id}")
            reader, writer = await self._connect_retry(path, timeout_ms)
        else:  # connect: runner listens, plugin dials in
            self._listener = self._listen(path)
            self._proc = await self._spawn(argv, env, pipes=False)
            self._stderr_task = asyncio.create_task(self._pump_stderr(), name=f"stderr-{self.id}")
            reader, writer = await self._accept(self._listener, timeout_ms)
        self._peer = self._new_peer(reader, writer, timeout_ms)

    @staticmethod
    def _listen(path: str) -> _socket.socket:
        srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)
        srv.listen(1)
        srv.setblocking(False)
        return srv

    async def _accept(self, srv: _socket.socket, timeout_ms: int) -> tuple[Any, Any]:
        loop = asyncio.get_running_loop()
        try:
            conn, _ = await asyncio.wait_for(loop.sock_accept(srv), timeout_ms / 1000)
        except asyncio.TimeoutError:
            raise RpcError(TIMEOUT, f"plugin {self.id}: no socket connection within {timeout_ms} ms") from None
        conn.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=conn)
        return reader, writer

    async def _connect_retry(self, path: str, timeout_ms: int) -> tuple[Any, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000
        last: Exception | None = None
        while loop.time() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                raise RpcError(PLUGIN_ERROR, f"plugin {self.id}: exited before its socket was ready")
            try:
                return await asyncio.open_unix_connection(path)
            except OSError as exc:
                last = exc
                await asyncio.sleep(0.05)
        raise RpcError(TIMEOUT, f"plugin {self.id}: socket {path} not ready ({last})") from None

    async def stop(self, *, drain_timeout: float = 2.0) -> None:
        self._stopping = True
        peer, self._peer = self._peer, None
        if peer is not None:
            try:
                await peer.aclose()
            except Exception:
                pass
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        if self.spec.transport in SOCKET_TRANSPORTS:
            _unlink(plugin_socket_path(self.id))
        proc = self._proc
        if proc is not None and proc.returncode is None:
            stdio = self.spec.transport == "stdio"
            stdin = proc.stdin
            if stdio and stdin is not None and not stdin.is_closing():
                try:
                    stdin.close()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), drain_timeout if stdio else min(drain_timeout, 1.0))
            except asyncio.TimeoutError:
                log.warning("plugin %s: drain timed out, terminating", self.id)
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 1.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        self._proc = None
        if self.status not in ("error",):
            self.status = "stopped"

    async def wait_exit(self) -> int | None:
        proc = self._proc
        if proc is None:
            return None
        return await proc.wait()

    # -- handshake -------------------------------------------------------- #
    async def _handshake(self, *, available: set[str] | None, timeout_ms: int) -> None:
        assert self._peer is not None
        hello = await self._peer.call(
            "protocol.hello",
            {"protocol": PROTOCOL_VERSION, "abi": ABI, "runner": RUNNER_NAME, "epoch": self.epoch},
            timeout_ms=timeout_ms,
        )
        if not isinstance(hello, dict):
            raise RpcError(INCOMPATIBLE_VERSION, f"plugin {self.id}: bad hello result")
        negotiated = hello.get("protocol")
        if negotiated != PROTOCOL_VERSION:
            raise RpcError(
                INCOMPATIBLE_VERSION,
                f"plugin {self.id}: unsupported protocol {negotiated!r}",
                {"negotiated": negotiated},
            )
        if hello.get("abi") != ABI:
            raise RpcError(
                INCOMPATIBLE_VERSION,
                f"plugin {self.id}: unsupported abi {hello.get('abi')!r}",
            )
        self.info = hello
        self.provides = sorted(set(hello.get("provides") or []) | set(self.spec.provides))
        self.requires = sorted(set(hello.get("requires") or []) | set(self.spec.requires))
        self.permissions = sorted(set(hello.get("permissions") or []) | set(self.spec.permissions))

        describe = await self._peer.call("plugin.describe", {}, timeout_ms=timeout_ms)
        self.methods = list((describe or {}).get("methods") or [])
        self.streams = list((describe or {}).get("streams") or [])

        health = await self._peer.call("plugin.health", {}, timeout_ms=timeout_ms)
        self.health = health if isinstance(health, dict) else {}
        self.warnings = validate_capabilities(self.provides, self.requires, available)
        for warning in self.warnings:
            log.warning("plugin %s: %s", self.id, warning)
        self.status = "ok" if self.health.get("status") == "ok" else "degraded"

    # -- api -------------------------------------------------------------- #
    async def call(self, method: str, params: dict | None = None, *, timeout_ms: int | None = None) -> Any:
        if self._peer is None:
            raise RpcError(PLUGIN_ERROR, f"plugin {self.id}: not running")
        return await self._peer.call(method, params, timeout_ms=timeout_ms)

    def exposes(self, method: str) -> bool:
        return method in self.methods

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "epoch": self.epoch,
            "status": self.status,
            "provides": list(self.provides),
            "requires": list(self.requires),
        }

    async def _handle_notification(self, method: str, params: dict) -> None:
        if self.notify_handler is not None:
            await self.notify_handler(self.id, method, params)

    async def _pump_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                log.info("[%s] %s", self.id, line.decode("utf-8", "replace").rstrip())
        except (asyncio.CancelledError, Exception):
            return


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
