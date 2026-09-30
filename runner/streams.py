"""Runner-side stream relay with bounded lossy queues and reliable credits.

A client ``stream.subscribe`` is proxied to a plugin's ``stream.subscribe``;
the runner assigns its own client-facing ``stream_id`` and relays the plugin's
``<method> {stream_id, seq, data}`` notifications back to the client (PROTOCOL
§5, §11).

* **lossy** — bounded queue (default 256), drop-oldest; ``seq`` gaps are the
  client's signal that frames were dropped.
* **reliable** — credit window (default 64). Delivery pauses when credits run
  out; ``stream.ack`` replenishes and flushes held frames.

``deliver`` never blocks the plugin read loop: it only enqueues (and drops /
holds) synchronously; per-stream writer tasks do the I/O.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any

from .rpc import DEGRADED, RpcError

log = logging.getLogger("runner.streams")

DEFAULT_LOSSY_QUEUE = 256
DEFAULT_CREDIT_WINDOW = 64


@dataclass
class Subscription:
    stream_id: str
    method: str
    mode: str
    plugin: Any
    plugin_stream_id: str
    peer: Any
    queue: asyncio.Queue
    credit_window: int
    credits: int
    held: list[dict] = field(default_factory=list)
    paused: bool = False
    dropped: int = 0
    delivered: int = 0
    last_seq: int = 0
    writer: asyncio.Task | None = None


class StreamManager:
    def __init__(
        self,
        *,
        lossy_queue: int = DEFAULT_LOSSY_QUEUE,
        credit_window: int = DEFAULT_CREDIT_WINDOW,
    ):
        self.lossy_queue = lossy_queue
        self.credit_window = credit_window
        self._subs: dict[str, Subscription] = {}
        self._by_plugin: dict[tuple[str, str], set[str]] = {}
        self._counter = itertools.count(1)

    # -- subscribe / stop ------------------------------------------------- #
    async def subscribe(
        self,
        plugin: Any,
        method: str,
        params: dict | None,
        mode: str,
        peer: Any,
        *,
        start_writer: bool = True,
    ) -> dict:
        result = await plugin.call(
            "stream.subscribe", {"method": method, "params": params or {}}
        )
        plugin_sid = (result or {}).get("stream_id") if isinstance(result, dict) else None
        if not plugin_sid:
            raise RpcError(DEGRADED, f"plugin {plugin.id}: stream.subscribe returned no stream_id")
        mode = "reliable" if mode == "reliable" else "lossy"
        sid = f"stream-{next(self._counter)}"
        queue: asyncio.Queue = (
            asyncio.Queue(maxsize=self.lossy_queue)
            if mode == "lossy"
            else asyncio.Queue()
        )
        sub = Subscription(
            stream_id=sid,
            method=method,
            mode=mode,
            plugin=plugin,
            plugin_stream_id=str(plugin_sid),
            peer=peer,
            queue=queue,
            credit_window=self.credit_window,
            credits=self.credit_window if mode == "reliable" else 0,
        )
        self._subs[sid] = sub
        self._by_plugin.setdefault((plugin.id, str(plugin_sid)), set()).add(sid)
        if start_writer and peer is not None:
            sub.writer = asyncio.create_task(self._writer(sub), name=f"stream-{sid}")
        return {"stream_id": sid, "mode": mode}

    async def stop(self, stream_id: str, *, plugin_gone: bool = False) -> bool:
        sub = self._subs.pop(stream_id, None)
        if sub is None:
            return False  # idempotent
        key = (sub.plugin.id, sub.plugin_stream_id)
        ids = self._by_plugin.get(key)
        if ids is not None:
            ids.discard(stream_id)
            if not ids:
                self._by_plugin.pop(key, None)
        if sub.writer is not None:
            sub.writer.cancel()
        if not plugin_gone:
            try:
                await sub.plugin.call("stream.stop", {"stream_id": sub.plugin_stream_id})
            except Exception:  # noqa: BLE001 - plugin may be gone / not implement it
                pass
        # free buffers
        sub.held.clear()
        while not sub.queue.empty():
            try:
                sub.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        return True

    async def stop_peer(self, peer: Any) -> int:
        stopped = 0
        for sid, sub in list(self._subs.items()):
            if sub.peer is peer:
                stopped += int(await self.stop(sid))
        return stopped

    async def stop_plugin(self, plugin_id: str) -> int:
        stopped = 0
        for sid, sub in list(self._subs.items()):
            if sub.plugin.id == plugin_id:
                stopped += int(await self.stop(sid, plugin_gone=True))
        return stopped

    async def stop_all(self) -> int:
        stopped = 0
        for sid in list(self._subs):
            stopped += int(await self.stop(sid, plugin_gone=True))
        return stopped

    # -- flow control ----------------------------------------------------- #
    def ack(self, stream_id: str, seq: Any = None) -> None:
        sub = self._subs.get(stream_id)
        if sub is None or sub.mode != "reliable":
            return  # idempotent / not applicable
        sub.credits = min(sub.credit_window, sub.credits + 1)
        while sub.credits > 0 and sub.held:
            sub.credits -= 1
            sub.queue.put_nowait(sub.held.pop(0))
        if not sub.held:
            sub.paused = False

    async def deliver(self, plugin_id: str, method: str, params: dict) -> None:
        plugin_sid = params.get("stream_id")
        if plugin_sid is None:
            return
        ids = self._by_plugin.get((plugin_id, str(plugin_sid)))
        if not ids:
            return
        seq = params.get("seq")
        data = params.get("data")
        for sid in list(ids):
            sub = self._subs.get(sid)
            if sub is None or sub.method != method:
                continue
            sub.last_seq = seq if isinstance(seq, int) else sub.last_seq + 1
            self._enqueue(sub, {"stream_id": sid, "seq": sub.last_seq, "data": data})

    def _enqueue(self, sub: Subscription, env: dict) -> None:
        if sub.mode == "lossy":
            if sub.queue.full():
                try:
                    sub.queue.get_nowait()
                    sub.dropped += 1
                except asyncio.QueueEmpty:  # pragma: no cover - race safety
                    pass
            sub.queue.put_nowait(env)
            return
        if sub.credits > 0:
            sub.credits -= 1
            sub.queue.put_nowait(env)
            sub.paused = False
        else:
            sub.held.append(env)
            sub.paused = True
            if len(sub.held) > sub.credit_window:
                sub.held.pop(0)
                sub.dropped += 1

    async def _writer(self, sub: Subscription) -> None:
        try:
            while True:
                env = await sub.queue.get()
                await sub.peer.notify(sub.method, env)
                sub.delivered += 1
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - client gone
            log.debug("stream %s: writer stopped", sub.stream_id)

    # -- diagnostics ------------------------------------------------------ #
    def peek(self, stream_id: str) -> list[dict]:
        """Return the currently queued envelopes (test/diagnostic helper)."""
        sub = self._subs.get(stream_id)
        if sub is None:
            return []
        return list(getattr(sub.queue, "_queue", []))

    def stats(self, stream_id: str) -> dict | None:
        sub = self._subs.get(stream_id)
        if sub is None:
            return None
        return {
            "stream_id": sub.stream_id,
            "mode": sub.mode,
            "credits": sub.credits,
            "paused": sub.paused,
            "queued": sub.queue.qsize(),
            "held": len(sub.held),
            "dropped": sub.dropped,
            "delivered": sub.delivered,
            "last_seq": sub.last_seq,
        }

    @property
    def active(self) -> int:
        return len(self._subs)
