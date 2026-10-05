"""Runner host: supervision, routing, streams, invoke, validation.

Config loading lives in ``runner.config``; handle/fd endpoints in
``runner.handles_api``. The names below are re-exported from ``runner.host`` for
backwards compatibility.

Client API over ``runner.sock``::

    runner.command {utterance, provenance?}    -> {results:[{op, ok, detail}]}
    runner.status {} / runner.plugins {}       -> {plugins:[...]}
    runner.invoke {plugin, method, params}     -> plugin result (policy applied)
    runner.validate_plugin {plugin}            -> capability/permission report
    stream.subscribe/ack/stop                  -> relayed plugin streams
    handle.fetch/handle.stat                   -> inline data (<=64 KiB) or -32007
    fd.pass {kind, meta}                       -> SCM_RIGHTS descriptor
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

from . import security
from . import platform as _platform
from .config import RunnerConfig, check_config, load_config  # noqa: F401 - re-exported
from .handles import HandleStore, default_root
from .handles_api import HandlesApiMixin
from .plugin import (
    ABI,
    PROTOCOL_VERSION,
    RUNNER_CAPS,
    PluginInstance,
    capability_report,
    runner_caps,
)
from .policy import ConfirmationRequired, Policy, Provenance
from .rpc import (
    DEGRADED,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PERMISSION_DENIED,
    RpcError,
    RpcPeer,
)
from .socket import SocketServer, default_socket_path
from .streams import StreamManager

log = logging.getLogger("runner.host")

HARD_MAX_TIMEOUT_MS = 60000
SIDE_EFFECTING = {"action.invoke", "input.inject", "host.action"}

ConfirmCb = Callable[[dict], Any]


class Host(HandlesApiMixin):
    def __init__(
        self,
        config: RunnerConfig,
        *,
        confirm: ConfirmCb | None = None,
        handle_root: str | None = None,
    ):
        self.config = config
        self.plugins: list[PluginInstance] = []
        self._confirm_cb = confirm
        self.handles = HandleStore(
            handle_root or config.handle_root or default_root(),
            default_ttl=config.handle_ttl,
        )
        self.policy = Policy(
            enabled_ops=config.enabled_ops, disabled_ops=config.disabled_ops
        )
        self.streams = StreamManager(
            lossy_queue=config.lossy_queue, credit_window=config.credit_window
        )
        self._security_wrapper = self._build_wrapper(config)
        self._supervisors: list[asyncio.Task] = []
        self._stopping = False
        self._capabilities: dict[str, list[dict]] = {}
        allow_same_uid = self._effective_same_uid(config)
        self.socket = SocketServer(
            config.socket_path or default_socket_path(),
            self.handle_request,
            allow_binaries=config.allow_binaries,
            allow_same_uid=allow_same_uid,
            token=config.socket_token,
            on_disconnect=self._on_client_disconnect,
            transport=config.socket_transport,
        )
        # fd.pass only exists on the Unix transport; do not advertise it on TCP.
        self._available: set[str] = runner_caps(fd_pass=self.socket.supports_fd_pass)

    @staticmethod
    def _build_wrapper(config: RunnerConfig) -> security.Wrapper:
        if config.security_enforce:
            wrapper = security.detect_wrapper()
            if not wrapper.enforced:
                log.warning("[security] enforce=true but %s", wrapper.reason)
            return wrapper
        return security.Wrapper(None, "security.enforce=false (advisory)")

    @staticmethod
    def _effective_same_uid(config: RunnerConfig) -> bool:
        # The TCP/Windows transport has no peer credentials; same-uid is never
        # a grant there (only the token is).
        if _platform.resolve_transport(config.socket_transport) == _platform.TCP:
            return False
        if config.socket_allow_same_uid is not None:
            return config.socket_allow_same_uid
        if not config.socket_section_present:
            log.warning(
                "[socket] not configured: M0 back-compat allows any same-uid client; "
                "set allow_binaries/token for default-deny"
            )
            return True
        return False

    # -- lifecycle -------------------------------------------------------- #
    async def start(self) -> list[PluginInstance]:
        for spec in self.config.plugins:
            if not spec.enabled:
                continue
            inst = PluginInstance(spec)
            inst.notify_handler = self.streams.deliver
            self.plugins.append(inst)
            try:
                await inst.start(
                    available=self._available,
                    timeout_ms=self.config.rpc_timeout_ms,
                    wrapper=self._security_wrapper,
                )
            except RpcError as exc:
                log.error("plugin %s handshake failed: %s", spec.id, exc)
                inst.status = "error"
            if inst.status in ("ok", "degraded"):
                self._available |= set(inst.provides)
                self._supervisors.append(
                    asyncio.create_task(self._supervise(inst), name=f"sup-{inst.id}")
                )
        await self.socket.start()
        return self.plugins

    async def _supervise(self, inst: PluginInstance) -> None:
        while not self._stopping:
            code = await inst.wait_exit()
            if self._stopping:
                return
            log.warning("plugin %s exited (code=%s, epoch=%d); restarting", inst.id, code, inst.epoch)
            await self.streams.stop_plugin(inst.id)
            await asyncio.sleep(0.2)
            try:
                await inst.restart(
                    available=self._available,
                    timeout_ms=self.config.rpc_timeout_ms,
                    wrapper=self._security_wrapper,
                )
                self._available |= set(inst.provides)
            except RpcError as exc:
                log.error("plugin %s restart failed: %s", inst.id, exc)
                await asyncio.sleep(1.0)

    async def stop(self) -> None:
        self._stopping = True
        for task in self._supervisors:
            task.cancel()
        await asyncio.gather(*self._supervisors, return_exceptions=True)
        await self.streams.stop_all()
        for inst in self.plugins:
            try:
                await inst.stop()
            except Exception:
                log.exception("stopping plugin %s failed", inst.id)
        await self.socket.stop()

    async def _on_client_disconnect(self, peer: RpcPeer) -> None:
        await self.streams.stop_peer(peer)

    # -- client API ------------------------------------------------------- #
    async def handle_request(self, method: str, params: dict, peer: RpcPeer | None = None) -> Any:
        if method == "runner.command":
            return await self.command(params, peer=peer)
        if method in ("runner.status", "runner.plugins"):
            return {"plugins": [p.snapshot() for p in self.plugins]}
        if method == "runner.invoke":
            return await self.invoke(params, peer=peer)
        if method == "runner.validate_plugin":
            return self.validate_plugin(params)
        if method == "stream.subscribe":
            return await self.stream_subscribe(params, peer=peer)
        if method == "stream.ack":
            sid = params.get("stream_id")
            if isinstance(sid, str):
                self.streams.ack(sid, params.get("seq"))
            return {}
        if method == "stream.stop":
            sid = params.get("stream_id")
            if isinstance(sid, str):
                await self.streams.stop(sid)
            return {}
        if method == "handle.fetch":
            return self.handle_fetch(params)
        if method == "handle.stat":
            return self.handle_stat(params)
        if method == "handle.create":
            return self.handle_create(params)
        if method == "fd.pass":
            if not self.socket.supports_fd_pass:
                raise RpcError(
                    DEGRADED, "fd.pass unsupported over the tcp transport"
                )
            return self.fd_pass(params)
        raise RpcError(METHOD_NOT_FOUND, f"unknown method: {method}")

    async def command(self, params: dict, *, peer: RpcPeer | None = None) -> dict:
        utterance = params.get("utterance")
        if not isinstance(utterance, str) or not utterance.strip():
            raise RpcError(INVALID_PARAMS, "runner.command requires a non-empty 'utterance'")
        provenance = Provenance.parse(params.get("provenance", "user"))
        timeout_ms = self._timeout(params.get("timeout_ms"))
        router = self._find_router()
        if router is None:
            raise RpcError(DEGRADED, "no router plugin available")
        plan_params: dict[str, Any] = {"utterance": utterance, "provenance": provenance.value}
        if params.get("context") is not None:
            plan_params["context"] = params["context"]
        plan = await router.call("router.plan", plan_params, timeout_ms=timeout_ms)
        steps = list((plan or {}).get("steps") or [])
        results: list[dict] = []
        for step in steps:
            results.append(await self._run_step(step, provenance, peer=peer, timeout_ms=timeout_ms))
        return {"results": results}

    async def _run_step(
        self,
        step: Any,
        command_provenance: Provenance,
        *,
        peer: RpcPeer | None,
        timeout_ms: int,
    ) -> dict:
        if not isinstance(step, dict):
            return self._fail("", INVALID_PARAMS, "step is not an object")
        op = step.get("op")
        if not isinstance(op, str) or not op:
            return self._fail(str(op), INVALID_PARAMS, "step missing 'op'")
        args = dict(step.get("args") or {})
        # A plugin-supplied provenance may only *downgrade* trust, never escalate.
        if command_provenance is Provenance.SCREEN or step.get("provenance") == "screen":
            provenance = Provenance.SCREEN
        else:
            provenance = Provenance.USER
        try:
            await self._enforce_policy(
                op, args, provenance, peer=peer, force_confirm=bool(step.get("confirm"))
            )
        except RpcError as exc:
            return {"op": op, "ok": False, "detail": exc.message, "error": exc.to_error()}
        action = await self._action_plugin(op)
        if action is None:
            return self._fail(op, DEGRADED, f"no action plugin for op {op!r}")
        try:
            result = await action.call(
                "action.invoke",
                {"op": op, "args": args, "provenance": provenance.value},
                timeout_ms=timeout_ms,
            )
        except RpcError as exc:
            return {"op": op, "ok": False, "detail": exc.message, "error": exc.to_error()}
        if isinstance(result, dict):
            ok = bool(result.get("ok", True))
            detail = str(result.get("detail") or result.get("message") or "")
        else:
            ok, detail = True, str(result)
        return {"op": op, "ok": ok, "detail": detail}

    # -- runner.invoke / validate_plugin ---------------------------------- #
    async def invoke(self, params: dict, *, peer: RpcPeer | None = None) -> Any:
        name = params.get("plugin")
        method = params.get("method")
        call_params = params.get("params") or {}
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "runner.invoke requires 'plugin'")
        if not isinstance(method, str) or not method:
            raise RpcError(INVALID_PARAMS, "runner.invoke requires 'method'")
        if not isinstance(call_params, dict):
            raise RpcError(INVALID_PARAMS, "runner.invoke 'params' must be an object")
        target = self._find_plugin(name)
        if target is None:
            raise RpcError(DEGRADED, f"unknown plugin {name!r}")
        if method in SIDE_EFFECTING:
            if "provenance" not in call_params:
                raise RpcError(
                    PERMISSION_DENIED,
                    f"provenance required for side-effecting method {method!r}",
                )
            if method == "action.invoke":
                op = call_params.get("op")
                if not isinstance(op, str) or not op:
                    raise RpcError(INVALID_PARAMS, "action.invoke requires 'op'")
                provenance = Provenance.parse(call_params.get("provenance"))
                await self._enforce_policy(
                    op,
                    call_params.get("args") or {},
                    provenance,
                    peer=peer,
                    force_confirm=bool(call_params.get("confirm")),
                )
        # The runner owns the handle data plane: handle.create is served here so
        # handles are content-addressed and fetchable via handle.fetch.
        if method == "handle.create":
            return self.handle_create(call_params)
        timeout_ms = self._timeout(call_params.get("timeout_ms"))
        result = await target.call(method, call_params, timeout_ms=timeout_ms)
        # Adopt any handle a plugin returns so the client can fetch it inline.
        if isinstance(result, dict) and isinstance(result.get("handle"), str):
            await self._adopt_handle(target, result["handle"])
        return result

    def validate_plugin(self, params: dict) -> dict:
        name = params.get("plugin")
        target = self._find_plugin(name)
        if target is None:
            raise RpcError(INVALID_PARAMS, f"unknown plugin {name!r}")
        report = capability_report(target.provides, target.requires, self._available)
        permissions = security.permission_status(target.permissions, self._security_wrapper)
        ok = target.status in ("ok", "degraded") and not report["missing_requires"]
        return {
            "ok": ok,
            "negotiated": {"protocol": PROTOCOL_VERSION, "abi": ABI},
            "unknown_capabilities": report["unknown_capabilities"],
            "missing_requires": report["missing_requires"],
            "permissions": permissions,
        }

    # -- streams ---------------------------------------------------------- #
    async def stream_subscribe(self, params: dict, *, peer: RpcPeer | None = None) -> dict:
        method = params.get("method")
        if not isinstance(method, str) or not method:
            raise RpcError(INVALID_PARAMS, "stream.subscribe requires 'method'")
        if peer is None:
            raise RpcError(DEGRADED, "stream.subscribe requires a client connection")
        plugin = self._find_stream_plugin(method)
        if plugin is None:
            raise RpcError(DEGRADED, f"no plugin provides stream {method!r}")
        mode = params.get("mode") or "lossy"
        if mode not in ("lossy", "reliable"):
            raise RpcError(INVALID_PARAMS, f"bad stream mode {mode!r}")
        return await self.streams.subscribe(plugin, method, params.get("params"), mode, peer)

    # -- policy ----------------------------------------------------------- #
    async def _enforce_policy(
        self,
        op: str,
        args: dict,
        provenance: Provenance,
        *,
        peer: RpcPeer | None,
        force_confirm: bool,
    ) -> None:
        try:
            self.policy.validate(op, args, provenance)
            if force_confirm:
                raise ConfirmationRequired(op, args, provenance, f"confirm {op}: {args}")
        except ConfirmationRequired as need:
            request = {
                "op": op,
                "args": args,
                "provenance": provenance.value,
                "summary": need.summary,
            }
            approved = await self._ask_confirm(request, peer)
            if not approved:
                raise RpcError(PERMISSION_DENIED, f"confirmation denied: {need.summary}", request)
            self.policy.validate(op, args, provenance, confirmed=True)

    async def _ask_confirm(self, request: dict, peer: RpcPeer | None) -> bool:
        if peer is not None:
            try:
                answer = await peer.call(
                    "host.confirm", request, timeout_ms=self.config.confirm_timeout_ms
                )
            except RpcError:
                return False
            if isinstance(answer, dict):
                return bool(answer.get("approved", answer.get("ok", False)))
            return bool(answer)
        if self._confirm_cb is not None:
            result = self._confirm_cb(request)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        return False

    # -- discovery -------------------------------------------------------- #
    def _find_plugin(self, name: Any) -> PluginInstance | None:
        if not isinstance(name, str) or not name:
            return None
        for p in self.plugins:
            if p.id == name:
                return p
        for p in self.plugins:
            if p.kind == name:
                return p
        return None

    def _find_router(self) -> PluginInstance | None:
        running = [p for p in self.plugins if p.status in ("ok", "degraded")]
        for p in running:
            if p.exposes("router.plan"):
                return p
        for p in running:
            if p.kind == "router":
                return p
        return None

    def _find_stream_plugin(self, method: str) -> PluginInstance | None:
        running = [p for p in self.plugins if p.status in ("ok", "degraded")]
        for p in running:
            if method in p.streams and p.exposes("stream.subscribe"):
                return p
        for p in running:
            if p.exposes("stream.subscribe"):
                return p
        return None

    async def _action_plugin(self, op: str) -> PluginInstance | None:
        running = [p for p in self.plugins if p.status in ("ok", "degraded")]
        base = f"action.{op}"
        for p in running:
            if any(c.split("@")[0] == base for c in p.provides):
                return p
        candidates = [p for p in running if p.exposes("action.invoke")]
        if not candidates:
            candidates = [p for p in running if p.kind == "action"]
        if not candidates:
            return None
        for p in candidates:
            ops = self._capabilities.get(p.id)
            if ops is None:
                try:
                    caps = await p.call("action.capabilities", {}, timeout_ms=self.config.rpc_timeout_ms)
                    ops = list((caps or {}).get("ops") or [])
                except RpcError:
                    ops = []
                self._capabilities[p.id] = ops
            if any(o.get("op") == op for o in ops):
                return p
        return candidates[0]

    def _timeout(self, requested: Any) -> int:
        try:
            value = int(requested)
        except (TypeError, ValueError):
            return self.config.rpc_timeout_ms
        if value <= 0:
            return self.config.rpc_timeout_ms
        return min(value, HARD_MAX_TIMEOUT_MS)

    @staticmethod
    def _fail(op: str, code: int, message: str) -> dict:
        return {"op": op, "ok": False, "detail": message, "error": {"code": code, "message": message}}
