"""Host handle endpoints: content-addressed store + fd.pass data plane.

Extracted from ``runner.host`` (behavior-preserving) as a mixin so ``Host`` keeps
exposing ``handle.create``/``handle.fetch``/``handle.stat``/``fd.pass`` unchanged.
The RPC method names, wire shapes and error codes are frozen.
"""

from __future__ import annotations

import base64
import logging
import os

from . import fdpass
from .handles import HandleError
from .plugin import PluginInstance
from .rpc import INVALID_PARAMS, RpcError

# Keep the historical logger name: these are Host methods and previously logged
# through runner/host.py.
log = logging.getLogger("runner.host")


class HandlesApiMixin:
    """Handle/fd endpoints. Mixed into ``Host``; relies on ``self.handles`` and
    ``self.config.rpc_timeout_ms`` provided by the host."""

    def handle_create(self, params: dict) -> dict:
        """Client-facing handle creation (runner-owned content-addressed store)."""
        raw: bytes
        b64 = params.get("data_b64")
        if isinstance(b64, str):
            try:
                raw = base64.b64decode(b64, validate=True)
            except Exception:  # noqa: BLE001
                raise RpcError(INVALID_PARAMS, "handle.create: bad data_b64") from None
        else:
            data = params.get("data")
            if isinstance(data, str):
                raw = data.encode("utf-8")
            elif isinstance(data, (bytes, bytearray)):
                raw = bytes(data)
            else:
                try:
                    size = int(params.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                raw = b"\x00" * max(0, size)
        handle = self.handles.create(raw, scope=str(params.get("scope") or "runner"))
        return {"handle": handle, "sha256": handle.rsplit("/", 1)[-1], "size": len(raw)}

    async def _adopt_handle(self, plugin: PluginInstance, handle: str) -> None:
        try:
            fetched = await plugin.call(
                "handle.fetch", {"handle": handle}, timeout_ms=self.config.rpc_timeout_ms
            )
            b64 = fetched.get("data_b64") if isinstance(fetched, dict) else None
            if b64:
                self.handles.create(base64.b64decode(b64), scope="adopted")
        except Exception:  # noqa: BLE001 - adoption is best-effort
            log.debug("could not adopt handle %s from %s", handle, plugin.id)

    def handle_fetch(self, params: dict) -> dict:
        handle = params.get("handle")
        if not isinstance(handle, str) or not handle:
            raise RpcError(INVALID_PARAMS, "handle.fetch requires 'handle'")
        scope = params.get("scope")
        try:
            return self.handles.fetch_inline(handle, scope if isinstance(scope, str) else None)
        except HandleError as exc:
            raise RpcError(exc.code, exc.message, exc.data) from None

    def handle_stat(self, params: dict) -> dict:
        handle = params.get("handle")
        if not isinstance(handle, str) or not handle:
            raise RpcError(INVALID_PARAMS, "handle.stat requires 'handle'")
        scope = params.get("scope")
        try:
            return self.handles.stat_scoped(handle, scope if isinstance(scope, str) else None)
        except HandleError as exc:
            raise RpcError(exc.code, exc.message, exc.data) from None

    def fd_pass(self, params: dict) -> fdpass.FdReply:
        kind = params.get("kind")
        meta = params.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        if kind == "handle":
            handle = meta.get("handle")
            if not isinstance(handle, str) or not handle:
                raise RpcError(INVALID_PARAMS, "fd.pass meta.handle required")
            scope = meta.get("scope")
            try:
                path = self.handles.path_for(handle, scope if isinstance(scope, str) else None)
            except HandleError as exc:
                raise RpcError(exc.code, exc.message, exc.data) from None
            return fdpass.FdReply(fd=os.open(str(path), os.O_RDONLY), result={})
        if kind in ("memfd", "memfd.ring"):
            return self._fd_pass_memfd(meta)
        raise RpcError(INVALID_PARAMS, f"unsupported fd.pass kind {kind!r}")

    @staticmethod
    def _fd_pass_memfd(meta: dict) -> fdpass.FdReply:
        data = meta.get("data")
        if isinstance(data, str):
            payload = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray)):
            payload = bytes(data)
        else:
            payload = b""
        try:
            size = int(meta.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        size = max(size, len(payload), 4096)
        if hasattr(os, "memfd_create"):
            fd = os.memfd_create("utter-fd", 0)
        else:  # pragma: no cover - non-Linux fallback
            import tempfile

            fd = os.open(tempfile.mktemp(prefix="utter-fd-"), os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        os.ftruncate(fd, size)
        if payload:
            os.write(fd, payload)
        os.lseek(fd, 0, 0)
        return fdpass.FdReply(fd=fd, result={"kind": "memfd", "size": size})
