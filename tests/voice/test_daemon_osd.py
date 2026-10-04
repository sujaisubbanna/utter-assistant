#!/usr/bin/env python3
"""Native voice path drives the OSD (waveform + final), without the bridge.

Simulates a push-to-talk press -> audio chunk -> transcript through
``Utter.run_hotkey`` (with sounddevice and the evdev listener stubbed) and
asserts the emitted ``listening`` / ``level`` / ``final`` / ``idle`` sequence,
including that a disabled emitter writes nothing.

Usage::

    .venv-agent/bin/python tests/voice/test_daemon_osd.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from utter.config import Config, OsdConfig, SleepConfig  # noqa: E402
from utter.daemon import Utter, _Osd  # noqa: E402

ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


def read(path: Path) -> dict:
    return json.loads(path.read_text())


# -- stubs --------------------------------------------------------------------
class FakeStt:
    backend = "whisper_cpp"
    fallbacks: list = []

    def transcribe(self, audio):
        return "open youtube"


class FakeStream:
    def __init__(self, *, samplerate=None, channels=None, dtype=None, device=None, callback=None):
        self.callback = callback

    def start(self) -> None:
        # >= 0.2 s @ 16 kHz so the native loop does not treat it as too short.
        chunk = np.full((4096, 1), 0.1, dtype="float32")
        self.callback(chunk, len(chunk), None, None)

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeSleeper:
    asleep = False

    def __init__(self) -> None:
        self.hooks = []

    def on_state(self, fn) -> None:
        self.hooks.append(fn)

    def wake(self) -> None:
        self.asleep = False

    def trigger(self, asleep: bool) -> None:
        self.asleep = asleep
        for fn in self.hooks:
            fn(asleep)


class FakeIdle:
    def begin(self, token) -> None:
        pass

    def end(self, token) -> None:
        pass

    def start(self):
        return None


def install_stubs():
    """Patch sounddevice, STT, hotkey and sleep; return (restore, sleeper)."""
    import utter.voice.hotkey as hotkey
    import utter.voice.stt as stt
    import utter.sleep as sleep_mod

    saved = {
        "sd": sys.modules.get("sounddevice"),
        "for_platform": stt.Transcriber.for_platform,
        "listen_many": hotkey.listen_many,
        "sleep_get": sleep_mod.get,
        "sleep_idle": sleep_mod.idle,
    }
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = FakeStream
    sys.modules["sounddevice"] = fake_sd
    stt.Transcriber.for_platform = staticmethod(lambda cfg=None, **kw: FakeStt())
    sleeper = FakeSleeper()
    sleep_mod.get = lambda cfg=None: sleeper
    sleep_mod.idle = lambda cfg=None: FakeIdle()

    def restore():
        if saved["sd"] is None:
            sys.modules.pop("sounddevice", None)
        else:
            sys.modules["sounddevice"] = saved["sd"]
        stt.Transcriber.for_platform = saved["for_platform"]
        hotkey.listen_many = saved["listen_many"]
        sleep_mod.get = saved["sleep_get"]
        sleep_mod.idle = saved["sleep_idle"]

    return restore, sleeper


def make_app(cfg):
    app = Utter(cfg, dry_run=False)
    app.handle_utterance = lambda text: True  # route-free: OSD is what we test
    return app


# -- native run: press -> chunk -> transcript -> final -> idle ---------------
def test_native_sequence() -> None:
    import utter.voice.hotkey as hotkey

    cfg = Config()
    cfg.osd = OsdConfig(enabled=True, dismiss_ms=50, stream=False)
    cfg.sleep = SleepConfig(services=[])  # no model-loading watcher to interleave

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        os.makedirs(Path(tmp) / "utter", exist_ok=True)
        path = Path(tmp) / "utter" / "osd.json"

        restore, _ = install_stubs()
        seen: dict = {}

        def fake_listen_many(keys, **_kw):
            # The legacy [hotkey] key still drives the assistant lane.
            on_press, on_release = keys[cfg.hotkey.key]
            on_press()
            doc = read(path)
            seen["press_state"] = doc["state"]
            seen["level"] = doc["level"]
            on_release()
            doc = read(path)
            seen["final_state"] = doc["state"]
            seen["final_text"] = doc["text"]
            seen["activated"] = doc["activated"]

        hotkey.listen_many = fake_listen_many
        try:
            app = make_app(cfg)
            app.run_hotkey()
        finally:
            restore()

        check("press emits listening", seen.get("press_state") == "listening")
        check("chunk emits a non-zero level", seen.get("level", 0.0) > 0.0)
        check("transcript emits final", seen.get("final_state") == "final")
        check("final carries the transcript", seen.get("final_text") == "open youtube")
        check("final marks the command as activated", seen.get("activated") is True)

        deadline = time.time() + 1.0
        while time.time() < deadline and read(path)["state"] != "idle":
            time.sleep(0.02)
        check("final dismisses to idle", read(path)["state"] == "idle")


# -- disabled emitter writes nothing ------------------------------------------
def test_disabled_writes_nothing() -> None:
    import utter.voice.hotkey as hotkey

    cfg = Config()
    cfg.osd = OsdConfig(enabled=False, dismiss_ms=50, stream=False)
    cfg.sleep = SleepConfig(services=[])

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        path = Path(tmp) / "utter" / "osd.json"

        restore, _ = install_stubs()
        hotkey.listen_many = lambda keys, **_kw: (
            keys[cfg.hotkey.key][0](), keys[cfg.hotkey.key][1]()
        )
        try:
            app = make_app(cfg)
            app.run_hotkey()
        finally:
            restore()

        check("disabled OSD writes nothing", not path.exists())


# -- loading state on cold start / wake ---------------------------------------
def test_loading_and_wake() -> None:
    import utter.voice.model_loading as ml

    cfg = Config()
    cfg.osd = OsdConfig(enabled=True, dismiss_ms=1000, stream=False)
    cfg.sleep = SleepConfig(services=["utter-vision"], model_ready_timeout_s=30)

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        os.makedirs(Path(tmp) / "utter", exist_ok=True)
        path = Path(tmp) / "utter" / "osd.json"

        saved_probes = ml.probes_for_services
        ml.probes_for_services = lambda services, cfg: [lambda: False]
        try:
            osd = _Osd(cfg)
            osd.begin_loading()
            check("cold start shows loading", read(path)["state"] == "loading")

            sleeper = FakeSleeper()
            osd.watch_sleep(sleeper)
            sleeper.trigger(False)  # wake
            check("wake re-asserts loading", read(path)["state"] == "loading")
            check("sleep hook registered once", len(sleeper.hooks) == 1)

            osd.watcher.cancel()
        finally:
            ml.probes_for_services = saved_probes


check("bridge module removed",
      importlib.util.find_spec("utter.voice.vocalinux_bridge") is None)

test_native_sequence()
test_disabled_writes_nothing()
test_loading_and_wake()

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
