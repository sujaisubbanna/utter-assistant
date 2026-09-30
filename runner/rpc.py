"""JSON-RPC 2.0 peer: id correlation, per-request timeouts, ``$/cancel``.

Error taxonomy (PROTOCOL.md §7):

======  ==================================================
-32000  plugin error
-32001  timeout
-32002  cancelled
-32003  permission denied
-32004  incompatible version
-32005  degraded / unavailable
-32006  untrusted-argument rejected by policy
======  ==================================================

Standard JSON-RPC codes (-32600..-32603, -32700) are also used.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any, Awaitable, Callable

from . import framing

log = logging.getLogger("runner.rpc")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
PLUGIN_ERROR = -32000
TIMEOUT = -32001
CANCELLED = -32002
PERMISSION_DENIED = -32003
INCOMPATIBLE_VERSION = -32004
DEGRADED = -32005
UNTRUSTED_ARG = -32006
HANDLE_TOO_LARGE = -32007

# Returned by a request handler that has already written its own (raw) reply,
# e.g. an ``fd.pass`` response carrying SCM_RIGHTS ancillary data.
NO_RESPONSE = object()


class RpcError(Exception):
    """A JSON-RPC error object (ours or received from a peer)."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


RequestHandler = Callable[[str, dict, Any], Awaitable[Any]]
NotificationHandler = Callable[[str, dict], Awaitable[None]]


class RpcPeer:
    """Symmetric JSON-RPC 2.0 peer over a framed asyncio stream.

    Requests are tagged with an ``<epoch>:<n>`` id. Responses whose id belongs
    to a different epoch are dropped (a restarted plugin instance must not be
    able to answer for its successor).
    """

    def __init__(
        self,
        reader: asyncio.StreamReader | None,
        writer: Any,
        *,
        epoch: int = 0,
        name: str = "peer",
        on_request: RequestHandler | None = None,
        on_notification: NotificationHandler | None = None,
        default_timeout_ms: int | None = None,
    ):
        self.reader = reader
        self.writer = writer
        self.epoch = epoch
        self.name = name
        self.on_request = on_request
        self.on_notification = on_notification
        self.default_timeout_ms = default_timeout_ms
        self._pending: dict[str, asyncio.Future] = {}
        self._inflight: dict[Any, asyncio.Task] = {}
        self._counter = itertools.count(1)
        self._task: asyncio.Task | None = None
        self._closed = False
        self.stale_rejected = 0

    # -- lifecycle -------------------------------------------------------- #
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._read_loop(), name=f"rpc-read-{self.name}")

    async def wait_closed(self) -> None:
        if self._task is not None:
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def aclose(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await self.wait_closed()
        for task in list(self._inflight.values()):
            task.cancel()
        self._fail_all(RpcError(PLUGIN_ERROR, "peer closed"))
        try:
            self.writer.close()
        except Exception:
            pass

    def _fail_all(self, err: RpcError) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()

    # -- ids -------------------------------------------------------------- #
    def _make_id(self) -> str:
        return f"{self.epoch}:{next(self._counter)}"

    def _id_current_epoch(self, rid: Any) -> bool:
        return isinstance(rid, str) and rid.startswith(f"{self.epoch}:")

    # -- sending ---------------------------------------------------------- #
    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout_ms: int | None = None,
        request_id: str | None = None,
    ) -> Any:
        if self._closed:
            raise RpcError(PLUGIN_ERROR, "peer is closed")
        rid = request_id or self._make_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await framing.write_message(
                self.writer,
                {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
            )
            if timeout_ms is None:
                timeout_ms = self.default_timeout_ms
            if timeout_ms is None:
                return await fut
            return await asyncio.wait_for(asyncio.shield(fut), timeout_ms / 1000)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            await self._best_effort_cancel(rid)
            raise RpcError(
                TIMEOUT, f"{method}: timeout after {timeout_ms} ms", {"id": rid}
            ) from None
        except asyncio.CancelledError:
            self._pending.pop(rid, None)
            await self._best_effort_cancel(rid)
            raise

    async def notify(self, method: str, params: dict | None = None) -> None:
        if self._closed:
            return
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await framing.write_message(self.writer, msg)

    async def respond(self, rid: Any, result: Any) -> None:
        await framing.write_message(
            self.writer, {"jsonrpc": "2.0", "id": rid, "result": result}
        )

    async def respond_error(self, rid: Any, err: RpcError) -> None:
        await framing.write_message(
            self.writer, {"jsonrpc": "2.0", "id": rid, "error": err.to_error()}
        )

    async def _best_effort_cancel(self, rid: str) -> None:
        try:
            await self.notify("$/cancel", {"id": rid})
        except Exception:
            pass

    # -- receiving -------------------------------------------------------- #
    async def _read_loop(self) -> None:
        reader = self.reader
        if reader is None:
            return
        try:
            while not self._closed:
                msg = await framing.read_message(reader)
                await self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except (framing.FramingError, asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            log.debug("%s: read loop ended: %s", self.name, exc)
        finally:
            if not self._closed:
                self._fail_all(RpcError(PLUGIN_ERROR, "connection closed"))

    async def _dispatch(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        if "method" in msg:
            await self._handle_incoming(msg)
        else:
            self._handle_response(msg)

    def _handle_response(self, msg: dict) -> None:
        rid = msg.get("id")
        if rid is None:
            return
        if not self._id_current_epoch(rid):
            self.stale_rejected += 1
            log.warning(
                "%s: dropped response for stale epoch id=%r (current epoch %d)",
                self.name, rid, self.epoch,
            )
            return
        fut = self._pending.pop(rid, None)
        if fut is None or fut.done():
            return
        if "error" in msg:
            err = msg.get("error") or {}
            try:
                code = int(err.get("code", PLUGIN_ERROR))
            except (TypeError, ValueError):
                code = PLUGIN_ERROR
            fut.set_exception(RpcError(code, str(err.get("message", "plugin error")), err.get("data")))
        else:
            fut.set_result(msg.get("result"))

    async def _handle_incoming(self, msg: dict) -> None:
        method = str(msg.get("method"))
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        rid = msg.get("id")
        if method == "$/cancel":
            self._handle_cancel(params)
            return
        if rid is None:
            if self.on_notification is not None:
                try:
                    await self.on_notification(method, params)
                except Exception:
                    log.exception("%s: notification handler failed", self.name)
            return
        # Service requests in a task so $/cancel can still arrive while busy.
        task = asyncio.create_task(self._serve_request(rid, method, params), name=f"rpc-req-{self.name}")
        self._inflight[rid] = task
        task.add_done_callback(lambda _t, _rid=rid: self._inflight.pop(_rid, None))

    async def _serve_request(self, rid: Any, method: str, params: dict) -> None:
        if self.on_request is None:
            await self.respond_error(rid, RpcError(METHOD_NOT_FOUND, f"method not found: {method}"))
            return
        try:
            result = await self.on_request(method, params, rid)
            if result is NO_RESPONSE:
                return
            await self.respond(rid, result)
        except asyncio.CancelledError:
            await self._safe_respond_error(rid, RpcError(CANCELLED, "cancelled", {"id": rid}))
            raise
        except RpcError as exc:
            await self._safe_respond_error(rid, exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s: request handler failed", self.name)
            await self._safe_respond_error(rid, RpcError(PLUGIN_ERROR, str(exc)))

    async def _safe_respond_error(self, rid: Any, err: RpcError) -> None:
        try:
            await self.respond_error(rid, err)
        except Exception:
            pass

    def _handle_cancel(self, params: dict) -> None:
        rid = params.get("id")
        if rid is None:
            return
        task = self._inflight.get(rid)
        if task is not None and not task.done():
            task.cancel()
        fut = self._pending.pop(rid, None)
        if fut is not None and not fut.done():
            fut.set_exception(RpcError(CANCELLED, "cancelled", {"id": rid}))
        # idempotent: unknown / duplicate cancel is a no-op
