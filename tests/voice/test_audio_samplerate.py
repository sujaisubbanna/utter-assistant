#!/usr/bin/env python3
"""Audio sample-rate negotiation for the voice daemon (hermetic).

Some USB input devices (e.g. the NanoKVMPro) accept only 48000 Hz. The old
daemon opened a fixed 16 kHz stream, PortAudio raised ``PaErrorCode -9997`` and
the exception killed the whole daemon. These tests exercise the helpers that
negotiate a working rate and resample to the STT rate (16 kHz), plus the
resilient start path, all without touching a real audio device.

Usage::

    .venv-agent/bin/python tests/voice/test_audio_samplerate.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from utter.config import Config, OsdConfig, SleepConfig  # noqa: E402
from utter.daemon import Utter, _open_input_stream, _resample_linear  # noqa: E402

ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


class FakeStream:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeSd:
    """sounddevice stand-in: only ``open_rate`` succeeds (None = all fail)."""

    def __init__(self, open_rate: int | None) -> None:
        self.open_rate = open_rate
        self.attempted: list[int] = []

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": 44100.0}

    def InputStream(self, *, samplerate=None, channels=None, dtype=None,
                    device=None, callback=None):
        self.attempted.append(samplerate)
        if self.open_rate is None or samplerate != self.open_rate:
            raise RuntimeError(f"Invalid sample rate [PaErrorCode -9997] ({samplerate})")
        return FakeStream()


def make_cfg() -> Config:
    cfg = Config()
    cfg.audio.sample_rate = 16000
    cfg.audio.channels = 1
    cfg.audio.device = ""
    return cfg


# -- rate negotiation ---------------------------------------------------------
def test_open_prefers_supported_rate() -> None:
    sd = FakeSd(open_rate=48000)
    stream, rate = _open_input_stream(sd, make_cfg(), callback=lambda *a: None)
    check("opens at supported 48000", rate == 48000)
    check("returns a stream", stream is not None)
    check("tried the configured rate first", sd.attempted[0] == 16000)
    check("tried 48000", 48000 in sd.attempted)
    check("stops after the first success", sd.attempted[-1] == 48000)
    check("no duplicate attempts", len(sd.attempted) == len(set(sd.attempted)))


def test_open_all_fail_raises() -> None:
    sd = FakeSd(open_rate=None)
    raised = None
    try:
        _open_input_stream(sd, make_cfg(), callback=lambda *a: None)
    except RuntimeError as exc:
        raised = exc
    check("raises RuntimeError when every rate fails", raised is not None)
    check("error names the rates tried", "48000" in str(raised))
    check("attempted multiple rates", len(sd.attempted) >= 2)


# -- resampling ---------------------------------------------------------------
def test_resample_linear() -> None:
    src = np.linspace(-1.0, 1.0, 48000, dtype="float32")
    out = _resample_linear(src, 48000, 16000)
    check("48k -> 16k halves to 16000 samples", out.shape == (16000,))
    check("resampled output is 1-D float32", out.ndim == 1 and out.dtype == np.float32)

    same = _resample_linear(src, 16000, 16000)
    check("identity when rates match", np.array_equal(same, src))

    empty = _resample_linear(np.zeros(0, dtype="float32"), 48000, 16000)
    check("empty input stays empty", empty.size == 0)

    const = np.full(48000, 0.5, dtype="float32")
    const_out = _resample_linear(const, 48000, 16000)
    check("constant signal stays constant",
          np.allclose(const_out, 0.5, atol=1e-6))


# -- resilient start ----------------------------------------------------------
class FakeStt:
    backend = "fake"
    fallbacks: list = []

    def transcribe(self, audio):
        return ""


class FakeIdle:
    def begin(self, token) -> None:
        pass

    def end(self, token) -> None:
        pass

    def start(self):
        return None


def test_start_failure_does_not_propagate() -> None:
    """A device that refuses every rate must not raise out of run_hotkey."""
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
    fake_sd.InputStream = FakeSd(open_rate=None).InputStream
    fake_sd.query_devices = FakeSd(open_rate=None).query_devices
    sys.modules["sounddevice"] = fake_sd
    stt.Transcriber.for_platform = staticmethod(lambda cfg=None, **kw: FakeStt())
    sleep_mod.get = lambda cfg=None: types.SimpleNamespace(asleep=False, wake=lambda: None,
                                                           on_state=lambda fn: None)
    sleep_mod.idle = lambda cfg=None: FakeIdle()

    cfg = make_cfg()
    cfg.osd = OsdConfig(enabled=False)
    cfg.sleep = SleepConfig(services=[])

    def fake_listen_many(keys, **_kw):
        for on_press, on_release in keys.values():
            on_press()
            on_release()

    hotkey.listen_many = fake_listen_many

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_RUNTIME_DIR"] = tmp
        os.environ.pop("UTTER_OSD", None)
        propagated = None
        try:
            app = Utter(cfg, dry_run=False)
            app.run_hotkey()
        except Exception as exc:  # noqa: BLE001 - the whole point
            propagated = exc
        finally:
            if saved["sd"] is None:
                sys.modules.pop("sounddevice", None)
            else:
                sys.modules["sounddevice"] = saved["sd"]
            stt.Transcriber.for_platform = saved["for_platform"]
            hotkey.listen_many = saved["listen_many"]
            sleep_mod.get = saved["sleep_get"]
            sleep_mod.idle = saved["sleep_idle"]

    check("bad-device start does not propagate", propagated is None)


test_open_prefers_supported_rate()
test_open_all_fail_raises()
test_resample_linear()
test_start_failure_does_not_propagate()

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
