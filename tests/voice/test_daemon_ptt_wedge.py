#!/usr/bin/env python3
"""Push-to-talk must always recover: no PortAudio/rec_lock deadlock, and a
missed key-up is bounded by the watchdog.

Reproduces the live wedge with fake audio + a slow OSD transcriber, entirely
without a real device or model.

Usage::

    .venv-agent/bin/python tests/voice/test_daemon_ptt_wedge.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from utter.config import Config, OsdConfig, SleepConfig  # noqa: E402
from utter.daemon import Utter  # noqa: E402

ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


class SlowStt:
    """Stand-in transcriber; records calls and sleeps (shared by OSD + listener)."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list = []
        self._lock = threading.Lock()

    def transcribe(self, audio):
        with self._lock:
            self.calls.append(len(audio))
        if self.delay:
            time.sleep(self.delay)
        return "open youtube"


class FailingStt:
    """A backend that cannot transcribe (e.g. missing runtime)."""

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        raise RuntimeError("No module named 'faster_whisper'")


class PortAudioFakeStream:
    """Mimics PortAudio: a background thread repeatedly fires the callback.

    ``stop()`` blocks until no callback is in flight, exactly like
    ``Pa_StopStream``. If ``stop()`` is called while holding the callback's
    lock (the old bug), this never returns and wedges the key-up path.
    """

    def __init__(self, callback) -> None:
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="fake-portaudio")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            chunk = np.full((1024, 1), 0.05, dtype="float32")
            try:
                self.callback(chunk, len(chunk), None, None)
            except Exception:  # noqa: BLE001 - like PortAudio: swallow
                pass
            time.sleep(0.002)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()  # unbounded, as Pa_StopStream is

    def close(self) -> None:
        pass


def _stream_factory(*, samplerate=None, channels=None, dtype=None,
                    device=None, callback=None):
    return PortAudioFakeStream(callback)


class FakeSleeper:
    asleep = False

    def on_state(self, fn) -> None:
        pass

    def wake(self) -> None:
        self.asleep = False


class FakeIdle:
    def begin(self, token) -> None:
        pass

    def end(self, token) -> None:
        pass

    def start(self):
        return None


def install_stubs(stream_factory, transcriber):
    """Patch sounddevice, STT, sleep; return (restore, streams)."""
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
    fake_sd.InputStream = stream_factory
    fake_sd.query_devices = lambda *a, **k: {"default_samplerate": 48000.0}
    sys.modules["sounddevice"] = fake_sd
    stt.Transcriber.for_platform = staticmethod(lambda cfg=None, **kw: transcriber)
    sleep_mod.get = lambda cfg=None: FakeSleeper()
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

    return restore


def _read_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    return json.loads(path.read_text()).get("state", "missing")


def _make_cfg(stream: bool) -> Config:
    cfg = Config()
    cfg.osd = OsdConfig(enabled=True, dismiss_ms=50, stream=stream,
                        stream_interval_ms=40, window_s=1)
    cfg.sleep = SleepConfig(services=[])
    return cfg


def test_slow_osd_cannot_block_stop() -> None:
    """A key-up must clear 'listening' even while a slow OSD decode runs."""
    import utter.voice.hotkey as hotkey

    cfg = _make_cfg(stream=True)  # worst case: windowed partials ON
    stt = SlowStt(delay=0.4)

    restore = install_stubs(_stream_factory, stt)

    def fake_listen_many(keys, **_kw):
        on_press, on_release = keys[cfg.ptt.assistant_key]
        on_press()
        time.sleep(0.15)  # let the audio callback + OSD worker run
        on_release()

    hotkey.listen_many = fake_listen_many

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        path = Path(tmp) / "utter" / "osd.json"
        try:
            app = Utter(cfg, dry_run=False)
            app.handle_utterance = lambda text: True
            worker = threading.Thread(target=app.run_hotkey, daemon=True,
                                      name="run-hotkey")
            worker.start()
            worker.join(timeout=8.0)
            check("key-up stop completed (no deadlock)", not worker.is_alive())
            time.sleep(0.3)  # let final dismiss
            check("listening cleared after key-up", _read_state(path) != "listening")
            check("OSD window transcription did run", len(stt.calls) >= 1)
        finally:
            restore()


def test_missed_key_up_is_bounded() -> None:
    """If key-up is never seen, the watchdog force-stops the lane."""
    import utter.daemon as daemon
    import utter.voice.hotkey as hotkey

    original = daemon._PTT_MAX_HOLD_S
    daemon._PTT_MAX_HOLD_S = 0.3
    cfg = _make_cfg(stream=False)
    stt = SlowStt(delay=0.0)
    restore = install_stubs(_stream_factory, stt)

    def fake_listen_many(keys, **_kw):
        on_press, _on_release = keys[cfg.ptt.assistant_key]
        on_press()  # key-up is never delivered

    hotkey.listen_many = fake_listen_many

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        path = Path(tmp) / "utter" / "osd.json"
        try:
            app = Utter(cfg, dry_run=False)
            app.handle_utterance = lambda text: True
            app.run_hotkey()          # returns immediately: no release
            check("lane is listening right after press", _read_state(path) == "listening")
            time.sleep(1.2)           # watchdog fires at ~0.3s
            check("watchdog force-cleared listening", _read_state(path) != "listening")
        finally:
            daemon._PTT_MAX_HOLD_S = original
            restore()


def test_transcribe_failure_does_not_kill_loop() -> None:
    """A missing/broken STT runtime must not propagate out of the key-up path."""
    import utter.voice.hotkey as hotkey

    cfg = _make_cfg(stream=False)
    stt = FailingStt()
    restore = install_stubs(_stream_factory, stt)

    def fake_listen_many(keys, **_kw):
        on_press, on_release = keys[cfg.ptt.assistant_key]
        on_press()
        time.sleep(0.15)  # capture enough audio to pass the short-clip guard
        on_release()  # stop() -> transcribe raises

    hotkey.listen_many = fake_listen_many

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        path = Path(tmp) / "utter" / "osd.json"
        errors: list = []
        try:
            app = Utter(cfg, dry_run=False)
            app.handle_utterance = lambda text: True

            def run():
                try:
                    app.run_hotkey()
                except Exception as exc:  # noqa: BLE001 - the regression
                    errors.append(exc)

            worker = threading.Thread(target=run, daemon=True, name="run-hotkey")
            worker.start()
            worker.join(timeout=5.0)
            check("transcribe failure did not propagate",
                  not worker.is_alive() and not errors)
            check("listening cleared after failed transcribe",
                  _read_state(path) != "listening")
            check("transcribe was attempted", stt.calls >= 1)
        finally:
            restore()


test_slow_osd_cannot_block_stop()
test_missed_key_up_is_bounded()
test_transcribe_failure_does_not_kill_loop()

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)