#!/usr/bin/env python3
"""OSD ``loading`` state: the additive model-startup state.

Covers the frozen-ish OSD contract (existing states unchanged, disabled = no
writes), the new ``loading``/``ready`` methods, and the readiness watcher that
drives ``loading`` -> idle on wake / cold start.

Usage::

    .venv-agent/bin/python tests/voice/test_osd_loading.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.voice.model_loading import ModelLoadingWatcher, probes_for_services  # noqa: E402
from utter.voice.osd import OsdEmitter  # noqa: E402

ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


def read(path: Path) -> dict:
    return json.loads(path.read_text())


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FlagProbe:
    def __init__(self, ready: bool = False) -> None:
        self.ready = ready
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.ready


def make_emitter(tmp: str) -> OsdEmitter:
    cfg = SimpleNamespace(enabled=True, stream=False, dismiss_ms=5000)
    return OsdEmitter(cfg, enabled=True, path=Path(tmp) / "osd.json")


with tempfile.TemporaryDirectory() as tmp:
    em = make_emitter(tmp)
    path = em.path

    # -- loading writes the correct document ---------------------------------
    em.loading("Starting models…")
    doc = read(path)
    check("loading: state is 'loading'", doc["state"] == "loading")
    check("loading: level zeroed, activated null",
          doc["level"] == 0.0 and doc["activated"] is None)
    check("loading: text carried through", doc["text"] == "Starting models…")
    check("loading: mode preserved as assistant", doc["mode"] == "assistant")
    check("loading: additive keys still present",
          set(doc) == {"state", "mode", "level", "text", "activated", "ts"})

    # -- loading never interrupts an utterance -------------------------------
    em.listening("dictation")
    em.loading("should be ignored")
    doc = read(path)
    check("loading does not clobber listening", doc["state"] == "listening")
    check("loading does not clobber listening text", doc["text"] == "")
    em.final("hello", True)
    em.loading("late")
    doc = read(path)
    check("loading does not clobber final", doc["state"] == "final")
    check("loading does not clobber final text", doc["text"] == "hello")
    em.idle()
    check("idle after final clears state", read(path)["state"] == "idle")

    # -- ready only clears loading -------------------------------------------
    em.listening("assistant")
    em.ready()
    check("ready is a no-op while listening", read(path)["state"] == "listening")
    em.idle()
    em.loading("up")
    em.ready()
    check("ready clears loading back to idle", read(path)["state"] == "idle")

    # -- existing states unchanged -------------------------------------------
    em.listening("assistant")
    doc = read(path)
    check("listening state unchanged", doc["state"] == "listening" and doc["mode"] == "assistant")
    em.final("done", False)
    doc = read(path)
    check("final state unchanged", doc["state"] == "final" and doc["activated"] is False)
    em.idle()
    check("idle state unchanged", read(path)["state"] == "idle")

    em.close()

# -- disabled => no writes ----------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "osd.json"
    off = OsdEmitter(SimpleNamespace(enabled=False), enabled=False, path=path)
    off.loading("nope")
    check("disabled: loading writes nothing", not path.exists())
    off.ready()
    check("disabled: ready writes nothing", not path.exists())

# -- watcher: wake path goes loading -> idle when ready ----------------------
with tempfile.TemporaryDirectory() as tmp:
    em = make_emitter(tmp)
    probe = FlagProbe(ready=False)
    clock = FakeClock()
    w = ModelLoadingWatcher(em, [probe], timeout_s=30.0, interval_s=0.5, clock=clock)
    w.begin(background=False)
    check("watcher: begin() shows loading", read(em.path)["state"] == "loading")
    clock.advance(1.5)
    check("watcher: tick() while not ready keeps loading",
          w.tick() is False and read(em.path)["state"] == "loading")
    probe.ready = True
    check("watcher: tick() finishes once ready", w.tick() is True)
    check("watcher: clears to idle on ready", read(em.path)["state"] == "idle")
    check("watcher: not marked timed out on readiness", w.timed_out is False)
    check("watcher: inactive after ready", w.active is False)
    em.close()

# -- watcher: already-ready is a silent no-op (no loading flash) -------------
with tempfile.TemporaryDirectory() as tmp:
    em = make_emitter(tmp)
    em.idle()
    before = read(em.path)
    w = ModelLoadingWatcher(em, [FlagProbe(ready=True)], timeout_s=30.0, clock=FakeClock())
    w.begin(background=False)
    check("watcher: ready-before-show leaves idle untouched",
          read(em.path)["state"] == "idle")
    check("watcher: ready-before-show starts no thread", w.active is False)
    em.close()

# -- watcher: bounded timeout fallback (no real readiness signal) ------------
with tempfile.TemporaryDirectory() as tmp:
    em = make_emitter(tmp)
    probe = FlagProbe(ready=False)
    clock = FakeClock()
    w = ModelLoadingWatcher(em, [probe], timeout_s=5.0, interval_s=0.5, clock=clock)
    w.begin(background=False)
    check("watcher: timeout case shows loading first", read(em.path)["state"] == "loading")
    clock.advance(4.9)
    check("watcher: still loading just before the timeout", w.tick() is False)
    clock.advance(0.2)
    check("watcher: timeout ends loading", w.tick() is True)
    check("watcher: timeout clears to idle", read(em.path)["state"] == "idle")
    check("watcher: timed_out flag set", w.timed_out is True)
    em.close()

# -- watcher: no probes => timeout fallback, never a false 'ready' -----------
with tempfile.TemporaryDirectory() as tmp:
    em = make_emitter(tmp)
    clock = FakeClock()
    w = ModelLoadingWatcher(em, [], timeout_s=2.0, clock=clock)
    w.begin(background=False)
    check("watcher: no probes still shows loading", read(em.path)["state"] == "loading")
    clock.advance(2.1)
    check("watcher: no probes ends via bounded timeout",
          w.tick() is True and w.timed_out is True)
    check("watcher: no probes clears to idle", read(em.path)["state"] == "idle")
    em.close()

# -- probes_for_services maps the configured URLs ----------------------------
cfg = SimpleNamespace(
    vision=SimpleNamespace(base_url="http://127.0.0.1:8000/v1"),
    router=SimpleNamespace(llm_base_url="http://127.0.0.1:8001/v1"),
)
probes = probes_for_services(["utter-vision", "utter-planner", "mystery"], cfg)
check("probes: vision + planner mapped, unknown skipped", len(probes) == 2)
check("probes: empty services => none", probes_for_services([], cfg) == [])

# -- native path: a voice lane drives loading/ready around a wake ------------
# The OSD emitter is driven directly by the voice lane now that the vocalinux
# bridge is gone. Use a stub lane that mirrors the wake -> loading -> ready
# sequence and assert the emitter's contract without importing any bridge.
import importlib.util  # noqa: E402

check("bridge module removed",
      importlib.util.find_spec("utter.voice.vocalinux_bridge") is None)

with tempfile.TemporaryDirectory() as tmp:
    em = make_emitter(tmp)
    probe = FlagProbe(ready=False)

    class StubLane:
        """Minimal native-lane stub: show loading on wake, clear when ready."""

        def __init__(self, emitter, ready_probe):
            self.em = emitter
            self.probe = ready_probe
            self.watcher = ModelLoadingWatcher(
                emitter, [ready_probe], timeout_s=30.0, interval_s=0.5, clock=FakeClock()
            )

        def wake(self) -> None:
            self.watcher.begin(background=False)

        def ready_tick(self) -> bool:
            return self.watcher.tick()

    lane = StubLane(em, probe)
    lane.wake()
    check("native lane: wake shows loading", read(em.path)["state"] == "loading")
    check("native lane: not ready keeps loading",
          lane.ready_tick() is False and read(em.path)["state"] == "loading")
    probe.ready = True
    check("native lane: ready finishes the watcher", lane.ready_tick() is True)
    check("native lane: ready clears to idle", read(em.path)["state"] == "idle")
    em.close()

# -- config: the bounded timeout is exposed and defaults sanely --------------
from utter.config import load_config  # noqa: E402

default = load_config(Path(__file__).resolve().parents[2] / "config.default.toml")
check("config: model_ready_timeout_s default is 30",
      default.sleep.model_ready_timeout_s == 30.0)
check("config: existing sleep keys unaffected",
      default.sleep.on_idle is True and default.sleep.idle_minutes == 15)

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
