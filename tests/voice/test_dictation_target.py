#!/usr/bin/env python3
"""Dictation target pinning + clipboard fallback (hermetic; runs on Linux).

Drives ``Utter.run_macos`` with the audio/STT/hotkey stack faked so a real
push-to-talk dictation press can be simulated end to end:

* the window focused at key-down is captured and used at key-up (macOS posts to
  the captured pid; Linux re-focuses a moved target), and
* a failed/absent target copies the transcript to the clipboard and shows the
  fallback message on the OSD + native notification.

A fake ``sounddevice`` module is installed in ``sys.modules`` (as
``tests/voice/test_daemon_osd.py`` does) so the real PortAudio library is never
imported — importing it can block on a live audio server.

Usage::

    .venv-agent/bin/python tests/voice/test_dictation_target.py
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
from utter.daemon import (  # noqa: E402
    Utter,
    _DICTATION_FALLBACK,
    _DICTATION_FALLBACK_NOCLIP,
)
from utter.types import Action, ActionResult, FocusedWindow, Tier  # noqa: E402


class _FakeStream:
    """Records the stream so the test can feed one long chunk after key-down."""

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
    backend = "apple_speech"
    fallbacks: list = []

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, _audio) -> str:
        return self.text


def _ok() -> ActionResult:
    return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "typed")


def _fail() -> ActionResult:
    return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD, "injection failed")


def _fake_sounddevice() -> types.ModuleType:
    module = types.ModuleType("sounddevice")
    module.InputStream = _FakeStream  # type: ignore[attr-defined]
    return module


def _run_dictation(*, target, type_result, clipboard_ok=True, text="hello world",
                   macos=True, still_focused=True):
    """Press the dictation key down/up and return what the seams observed."""
    _FakeStream.instances.clear()
    app = Utter.__new__(Utter)
    app.cfg = Config()
    app.cfg.sleep = SleepConfig(services=[])  # no model-loading watcher
    app.handle_utterance = MagicMock(return_value=True)

    calls = {"type": [], "clipboard": [], "notify": [], "refocus": [], "captures": 0}

    def fake_type(t, pid=None):
        calls["type"].append((t, pid))
        return type_result

    def fake_copy(payload):
        calls["clipboard"].append(payload)
        return clipboard_ok

    def fake_notify(message, *_a, **_k):
        calls["notify"].append(message)

    def fake_capture():
        calls["captures"] += 1
        return target

    def fake_listen_many(keys, backend=None):
        down, up = keys[app.cfg.macos.dictation_key]
        down()  # key-down: capture target + open the stream
        stream = _FakeStream.instances[-1]
        chunk = np.full((4096, 1), 0.1, dtype="float32")  # >= 0.2 s @ 16 kHz
        stream.callback(chunk, len(chunk), None, None)
        up()  # key-up: transcribe + deliver

    osd = MagicMock()
    native = MagicMock()
    with patch.dict(sys.modules, {"sounddevice": _fake_sounddevice()}), \
         patch("utter.macos.permissions.status_all", return_value={"permissions": []}), \
         patch("utter.voice.stt.Transcriber.for_platform", return_value=_FakeStt(text)), \
         patch("utter.macos.hotkey.listen_many", side_effect=fake_listen_many), \
         patch("utter.daemon._play"), \
         patch("utter.daemon._notify", side_effect=fake_notify), \
         patch("utter.daemon._capture_dictation_target", side_effect=fake_capture), \
         patch("utter.daemon._copy_to_clipboard", side_effect=fake_copy), \
         patch("utter.actions.keyboard.type_text", side_effect=fake_type), \
         patch("utter.platform.is_macos", return_value=macos), \
         patch("utter.dictation._still_focused", return_value=still_focused), \
         patch("utter.dictation._refocus",
               side_effect=lambda tgt: calls["refocus"].append(tgt) or True), \
         patch("utter.daemon._Osd", return_value=osd), \
         patch("utter.daemon._NativeOverlay", return_value=native), \
         patch("utter.sleep.get", return_value=MagicMock(asleep=False)), \
         patch("utter.sleep.idle", return_value=MagicMock()):
        Utter.run_macos(app)
    return calls, osd, native


def _target() -> FocusedWindow:
    return FocusedWindow(app_id="com.apple.Safari", title="Docs", pid=4321, window_id=7)


class DictationTargetPinTest(unittest.TestCase):
    def test_target_captured_at_start_and_pid_used_at_stop(self):
        calls, osd, native = _run_dictation(target=_target(), type_result=_ok())
        self.assertEqual(calls["captures"], 1)
        self.assertEqual(calls["type"], [("hello world", 4321)])
        self.assertEqual(calls["clipboard"], [])
        self.assertEqual(calls["notify"], [])
        osd.final.assert_called_once_with("hello world", True)
        self.assertEqual(native.final.call_args.args[:2], ("hello world", True))

    def test_typing_failure_copies_and_messages(self):
        calls, osd, native = _run_dictation(
            target=_target(), type_result=_fail(), clipboard_ok=True)
        self.assertEqual(calls["clipboard"], ["hello world"])
        osd.final.assert_called_once_with(_DICTATION_FALLBACK, False)
        self.assertEqual(calls["notify"], [_DICTATION_FALLBACK])
        self.assertEqual(native.final.call_args.args[0], _DICTATION_FALLBACK)

    def test_no_target_copies_and_messages(self):
        calls, osd, native = _run_dictation(target=None, type_result=_ok())
        self.assertEqual(calls["type"], [])
        self.assertEqual(calls["clipboard"], ["hello world"])
        osd.final.assert_called_once_with(_DICTATION_FALLBACK, False)
        self.assertEqual(calls["notify"], [_DICTATION_FALLBACK])

    def test_clipboard_unavailable_uses_manual_message(self):
        calls, osd, native = _run_dictation(
            target=None, type_result=_ok(), clipboard_ok=False)
        self.assertEqual(calls["clipboard"], ["hello world"])
        osd.final.assert_called_once_with(_DICTATION_FALLBACK_NOCLIP, False)
        self.assertEqual(calls["notify"], [_DICTATION_FALLBACK_NOCLIP])

    def test_linux_refocuses_when_focus_moved(self):
        calls, osd, native = _run_dictation(
            target=_target(), type_result=_ok(), macos=False, still_focused=False)
        self.assertEqual(calls["refocus"], [_target()])
        self.assertEqual(calls["type"], [("hello world", None)])
        osd.final.assert_called_once_with("hello world", True)

    def test_linux_skips_refocus_when_still_focused(self):
        calls, osd, native = _run_dictation(
            target=_target(), type_result=_ok(), macos=False, still_focused=True)
        self.assertEqual(calls["refocus"], [])
        self.assertEqual(calls["type"], [("hello world", None)])
        osd.final.assert_called_once_with("hello world", True)


class LinuxClipboardSetTest(unittest.TestCase):
    def test_set_clipboard_uses_wl_copy(self):
        from utter.context import clipboard
        with patch("utter.context.clipboard.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            self.assertTrue(clipboard.set_clipboard("hi"))
            self.assertEqual(run.call_args.args[0], ["wl-copy"])
            self.assertEqual(run.call_args.kwargs["input"], "hi")

    def test_set_clipboard_missing_tool_is_false(self):
        from utter.context import clipboard
        with patch("utter.context.clipboard.subprocess.run", side_effect=OSError):
            self.assertFalse(clipboard.set_clipboard("hi"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
