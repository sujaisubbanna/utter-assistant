#!/usr/bin/env python3
"""Optional local dictation formatting (``[dictation] format``).

Hermetic: no network. ``format_transcript`` is exercised with a faked
``requests`` module, then the Linux dictation lane is driven end to end (audio,
STT and evdev stubbed, as ``test_linux_dictation.py`` does) to prove:

* the formatted text is what gets typed for the dictation lane, and
* the assistant lane is never formatted.

Usage::

    .venv-agent/bin/python tests/voice/test_dictation_formatting.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from utter.config import Config, SleepConfig  # noqa: E402
from utter.daemon import Utter  # noqa: E402
from utter.types import Action, ActionResult, FocusedWindow, Tier  # noqa: E402
from utter.voice.formatting import format_transcript  # noqa: E402


# --- fakes -----------------------------------------------------------------

class _Timeout(Exception):
    """Stand-in for requests.Timeout (the code catches any exception)."""


class _Resp:
    def __init__(self, status_code: int = 200, data=None, json_exc=None):
        self.status_code = status_code
        self._data = data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._data


class _FakeRequests(types.ModuleType):
    """Minimal ``requests`` stand-in recording ``post`` calls."""

    def __init__(self, *, response=None, exc=None):
        super().__init__("requests")
        self.response = response
        self.exc = exc
        self.calls: list = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.response


def _cfg(fmt: str = "local") -> Config:
    cfg = Config()
    cfg.dictation.format = fmt
    return cfg


def _content(text: str, status: int = 200) -> _Resp:
    return _Resp(status_code=status,
                 data={"choices": [{"message": {"content": text}}]})


class FormatTranscriptUnitTest(unittest.TestCase):
    def _call(self, text, cfg, requests_mod):
        with patch.dict(sys.modules, {"requests": requests_mod}):
            return format_transcript(text, cfg)

    def test_off_returns_original_and_makes_no_http_call(self):
        fake = _FakeRequests(response=_content("Hello, world."))
        self.assertEqual(self._call("hello world", _cfg("off"), fake), "hello world")
        self.assertEqual(fake.calls, [])

    def test_unknown_value_is_treated_as_off(self):
        fake = _FakeRequests(response=_content("Hello, world."))
        self.assertEqual(self._call("hello world", _cfg("banana"), fake), "hello world")
        self.assertEqual(fake.calls, [])

    def test_local_success_returns_formatted_text(self):
        fake = _FakeRequests(response=_content("Hello, world."))
        self.assertEqual(
            self._call("um hello world", _cfg("local"), fake), "Hello, world.")
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertTrue(call["url"].endswith("/chat/completions"))
        self.assertEqual(call["json"]["temperature"], 0.0)
        self.assertEqual(call["json"]["model"], "qwen3-4b")
        self.assertLessEqual(call["timeout"], 5.0)
        # Reformat-only instruction: no answering/translating content.
        self.assertIn("clean", call["json"]["messages"][0]["content"].lower())

    def test_configured_endpoint_and_model_are_used(self):
        cfg = _cfg("local")
        cfg.router.llm_base_url = "http://192.0.2.9:9999/v1"
        cfg.router.llm_model = "my-model"
        fake = _FakeRequests(response=_content("Hi there."))
        self._call("hi there", cfg, fake)
        self.assertEqual(fake.calls[0]["url"], "http://192.0.2.9:9999/v1/chat/completions")
        self.assertEqual(fake.calls[0]["json"]["model"], "my-model")

    def test_empty_or_whitespace_transcript_unchanged_no_call(self):
        for text in ("", "   ", "\n\t "):
            fake = _FakeRequests(response=_content("nope"))
            self.assertEqual(self._call(text, _cfg("local"), fake), text)
            self.assertEqual(fake.calls, [])

    def test_connection_error_returns_original(self):
        fake = _FakeRequests(exc=OSError("connection refused"))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_timeout_returns_original(self):
        fake = _FakeRequests(exc=_Timeout("timed out"))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_non_200_returns_original(self):
        fake = _FakeRequests(response=_content("Hello.", status=503))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_empty_body_returns_original(self):
        fake = _FakeRequests(response=_content("   "))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_malformed_body_returns_original(self):
        fake = _FakeRequests(response=_Resp(data={"nope": True}))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_unparseable_json_returns_original(self):
        fake = _FakeRequests(response=_Resp(json_exc=ValueError("bad json")))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_overlong_reply_returns_original(self):
        rambling = "Sure! Here is a long answer. " * 200
        fake = _FakeRequests(response=_content(rambling))
        self.assertEqual(self._call("hello world", _cfg("local"), fake), "hello world")

    def test_requests_unavailable_returns_original(self):
        with patch.dict(sys.modules, {"requests": None}):
            self.assertEqual(format_transcript("hello world", _cfg("local")),
                             "hello world")

    def test_never_raises_on_missing_config(self):
        with patch.dict(sys.modules, {"requests": _FakeRequests()}):
            self.assertEqual(format_transcript("hello world", None), "hello world")


# --- dictation lane wiring (Linux) -----------------------------------------

class _FakeStream:
    instances: list = []

    def __init__(self, *, samplerate=None, channels=None, dtype=None,
                 device=None, callback=None):
        self.callback = callback
        _FakeStream.instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeStt:
    backend = "faster_whisper"
    fallbacks: list = []

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, _audio) -> str:
        return self.text


def _ok() -> ActionResult:
    return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "typed")


def _fake_sounddevice() -> types.ModuleType:
    module = types.ModuleType("sounddevice")
    module.InputStream = _FakeStream  # type: ignore[attr-defined]
    return module


def _target() -> FocusedWindow:
    return FocusedWindow(app_id="org.kde.konsole", title="Terminal", pid=7, window_id=9)


def _run_linux(*, press, text="hello world"):
    """Press each configured key down/up once; return (app, typed, osd)."""
    _FakeStream.instances.clear()
    app = Utter.__new__(Utter)
    app.cfg = Config()
    app.cfg.sleep = SleepConfig(services=[])  # no model-loading watcher
    app.cfg.ptt.dictation_key = "KEY_F13"
    app.cfg.ptt.assistant_key = "KEY_INSERT"
    app.cfg.hotkey.key = ""
    app.handle_utterance = MagicMock(return_value=True)

    typed: list = []
    osd = MagicMock()

    def fake_type(t, pid=None):
        typed.append(t)
        return _ok()

    def fake_listen(keys, **_kw):
        for name in press:
            down, up = keys[name]
            down()
            stream = _FakeStream.instances[-1]
            chunk = np.full((4096, 1), 0.1, dtype="float32")  # >= 0.2 s @ 16 kHz
            stream.callback(chunk, len(chunk), None, None)
            up()

    patches = [
        patch.dict(sys.modules, {"sounddevice": _fake_sounddevice()}),
        patch("utter.voice.stt.Transcriber.for_platform", return_value=_FakeStt(text)),
        patch("utter.voice.hotkey.listen_many", side_effect=fake_listen),
        patch("utter.daemon._play"),
        patch("utter.daemon._notify"),
        patch("utter.daemon._capture_dictation_target", return_value=_target()),
        patch("utter.daemon._still_focused", return_value=True),
        patch("utter.daemon._Osd", return_value=osd),
        patch("utter.platform.is_macos", return_value=False),
        patch("utter.actions.keyboard.type_text", side_effect=fake_type),
        patch("utter.sleep.get", return_value=MagicMock(asleep=False)),
        patch("utter.sleep.idle", return_value=MagicMock()),
    ]
    for p in patches:
        p.start()
    try:
        Utter.run_hotkey(app)
    finally:
        for p in patches:
            p.stop()
    return app, typed, osd


class DictationLaneWiringTest(unittest.TestCase):
    def test_dictation_types_the_formatted_text(self):
        with patch("utter.voice.formatting.format_transcript",
                   return_value="Hello, world.") as fmt:
            app, typed, _osd = _run_linux(press=["KEY_F13"])
        fmt.assert_called_once()
        self.assertEqual(typed, ["Hello, world."])

    def test_formatter_receives_transcript_and_config(self):
        with patch("utter.voice.formatting.format_transcript",
                   return_value="x") as fmt:
            app, _typed, _osd = _run_linux(press=["KEY_F13"])
        self.assertEqual(fmt.call_args.args, ("hello world", app.cfg))

    def test_format_off_types_raw_without_calling_the_model(self):
        # Real module: format defaults to "off", so no HTTP is attempted.
        app, typed, _osd = _run_linux(press=["KEY_F13"])
        self.assertEqual(typed, ["hello world"])

    def test_assistant_lane_is_never_formatted(self):
        with patch("utter.voice.formatting.format_transcript") as fmt:
            app, typed, _osd = _run_linux(press=["KEY_INSERT"])
        fmt.assert_not_called()
        self.assertEqual(typed, [])
        app.handle_utterance.assert_called_once_with("hello world")


if __name__ == "__main__":
    unittest.main(verbosity=2)
