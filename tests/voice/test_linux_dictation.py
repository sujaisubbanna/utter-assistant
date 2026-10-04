#!/usr/bin/env python3
"""Linux dictation lane: two PTT keys, target pin, clipboard fallback.

Drives ``Utter.run_hotkey`` with the audio/STT/evdev stack faked so a real
push-to-talk press can be simulated end to end:

* ``[ptt] dictation_key`` -> ``_type_dictation`` with the target captured at
  key-down (``None`` when unavailable), and the clipboard fallback on failure.
* ``[ptt] assistant_key`` / ``[hotkey] key`` -> routed through
  ``handle_utterance`` exactly as the lane did before dictation was added.

A fake ``sounddevice`` module is installed in ``sys.modules`` (as
``tests/voice/test_daemon_osd.py`` does) so the real PortAudio library is never
imported — importing it can block on a live audio server.

Usage::

    .venv-agent/bin/python tests/voice/test_linux_dictation.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from utter.config import Config, SleepConfig  # noqa: E402
from utter.daemon import (  # noqa: E402
    Utter,
    _DICTATION_FALLBACK,
    _DICTATION_FALLBACK_NOCLIP,
    _linux_ptt_keys,
)
from utter.types import Action, ActionResult, FocusedWindow, Tier  # noqa: E402
from utter.voice import hotkey  # noqa: E402


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
    backend = "faster_whisper"
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


def _target() -> FocusedWindow:
    return FocusedWindow(app_id="org.kde.konsole", title="Terminal", pid=4321, window_id=7)


def _run_linux(*, press=(), dispatch=None, target=None, text="hello world",
               type_dictation_result=None, real_type=False, clipboard_ok=True,
               dictation_key="KEY_F13", assistant_key="KEY_INSERT",
               legacy_key="", still_focused=True, handle_ok=True, asleep=False):
    """Run ``Utter.run_hotkey`` once; return the observed seams.

    ``press`` is a list of configured key names pressed in order (down -> one
    audio chunk -> up). ``dispatch`` runs instead, receiving the key map while
    the stubs are still active (for interleaved press/release sequences). With
    ``real_type`` the real ``_type_dictation`` runs against
    ``keyboard.type_text``; otherwise it is a spy mock.
    """
    _FakeStream.instances.clear()
    app = Utter.__new__(Utter)
    app.cfg = Config()
    app.cfg.sleep = SleepConfig(services=[])  # no model-loading watcher
    app.cfg.ptt.dictation_key = dictation_key
    app.cfg.ptt.assistant_key = assistant_key
    app.cfg.hotkey.key = legacy_key
    app.handle_utterance = MagicMock(return_value=handle_ok)

    calls = {"type": [], "clipboard": [], "notify": [], "refocus": [], "captures": 0}
    captured: dict = {}
    play = MagicMock()
    osd = MagicMock()
    type_dict = MagicMock(return_value=type_dictation_result or _ok())

    def fake_type(t, pid=None):
        calls["type"].append((t, pid))
        return _ok()

    def fake_copy(payload):
        calls["clipboard"].append(payload)
        return clipboard_ok

    def fake_notify(message, *_a, **_k):
        calls["notify"].append(message)

    def fake_capture():
        calls["captures"] += 1
        return target

    def fake_listen_many(keys, **_kw):
        captured["keys"] = keys
        if dispatch is not None:
            dispatch(keys)
            return
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
        patch("utter.voice.hotkey.listen_many", side_effect=fake_listen_many),
        patch("utter.daemon._play", play),
        patch("utter.daemon._notify", side_effect=fake_notify),
        patch("utter.daemon._capture_dictation_target", side_effect=fake_capture),
        patch("utter.daemon._copy_to_clipboard", side_effect=fake_copy),
        patch("utter.daemon._Osd", return_value=osd),
        patch("utter.platform.is_macos", return_value=False),
        patch("utter.sleep.get", return_value=MagicMock(asleep=asleep)),
        patch("utter.sleep.idle", return_value=MagicMock()),
    ]
    if real_type:
        patches += [
            patch("utter.daemon._still_focused", return_value=still_focused),
            patch("utter.daemon._refocus",
                  side_effect=lambda tgt: calls["refocus"].append(tgt) or True),
            patch("utter.actions.keyboard.type_text", side_effect=fake_type),
        ]
    else:
        patches.append(patch("utter.daemon._type_dictation", type_dict))

    for p in patches:
        p.start()
    try:
        Utter.run_hotkey(app)
    finally:
        for p in patches:
            p.stop()
    return SimpleNamespace(calls=calls, captured=captured, play=play, osd=osd,
                           app=app, type_dict=type_dict)


class LinuxDictationLaneTest(unittest.TestCase):
    def test_dictation_key_types_into_pinned_target(self):
        tgt = _target()
        r = _run_linux(press=["KEY_F13"], target=tgt)
        self.assertEqual(r.calls["captures"], 1)
        self.assertEqual(r.type_dict.call_args.args, ("hello world", tgt))
        r.app.handle_utterance.assert_not_called()
        r.osd.final.assert_called_once_with("hello world", True)
        plays = [c.args[0] for c in r.play.call_args_list]
        self.assertIn("dictate", plays)
        self.assertIn("typed", plays)
        self.assertNotIn("start", plays)  # assistant cue, not the dictation lane

    def test_dictation_stop_passes_none_when_no_target(self):
        r = _run_linux(press=["KEY_F13"], target=None)
        self.assertEqual(r.type_dict.call_args.args, ("hello world", None))

    def test_typing_failure_copies_and_messages(self):
        r = _run_linux(press=["KEY_F13"], target=_target(),
                       type_dictation_result=_fail(), clipboard_ok=True)
        self.assertEqual(r.calls["clipboard"], ["hello world"])
        r.osd.final.assert_called_once_with(_DICTATION_FALLBACK, False)
        self.assertEqual(r.calls["notify"], [_DICTATION_FALLBACK])

    def test_clipboard_unavailable_uses_manual_message(self):
        r = _run_linux(press=["KEY_F13"], target=_target(),
                       type_dictation_result=_fail(), clipboard_ok=False)
        self.assertEqual(r.calls["clipboard"], ["hello world"])
        r.osd.final.assert_called_once_with(_DICTATION_FALLBACK_NOCLIP, False)
        self.assertEqual(r.calls["notify"], [_DICTATION_FALLBACK_NOCLIP])

    def test_real_type_dictation_uses_captured_target(self):
        tgt = _target()
        r = _run_linux(press=["KEY_F13"], target=tgt, real_type=True,
                       still_focused=True)
        self.assertEqual(r.calls["captures"], 1)
        self.assertEqual(r.calls["refocus"], [])
        self.assertEqual(r.calls["type"], [("hello world", None)])


class LinuxAssistantLaneTest(unittest.TestCase):
    def test_both_keys_bound_and_dispatched_to_correct_lane(self):
        tgt = _target()
        r = _run_linux(press=["KEY_F13", "KEY_INSERT"], target=tgt)
        self.assertEqual(set(r.captured["keys"]), {"KEY_F13", "KEY_INSERT"})
        # dictation typed once; assistant routed once
        self.assertEqual(r.calls["captures"], 1)
        r.type_dict.assert_called_once()
        r.app.handle_utterance.assert_called_once_with("hello world")

    def test_assistant_key_routes_via_handle_utterance(self):
        r = _run_linux(press=["KEY_INSERT"], target=_target(), handle_ok=True)
        r.app.handle_utterance.assert_called_once_with("hello world")
        r.type_dict.assert_not_called()
        self.assertEqual(r.calls["captures"], 0)
        r.osd.final.assert_called_once_with("hello world", True)
        plays = [c.args[0] for c in r.play.call_args_list]
        self.assertIn("detected", plays)
        self.assertIn("start", plays)  # same key-down cue as macOS

    def test_assistant_key_down_plays_wake_then_start(self):
        r = _run_linux(press=["KEY_INSERT"], handle_ok=True, asleep=True)
        plays = [c.args[0] for c in r.play.call_args_list]
        self.assertEqual(plays[:2], ["wake", "start"])

    def test_dictation_key_down_plays_dictate(self):
        r = _run_linux(press=["KEY_F13"], target=_target(), asleep=False)
        plays = [c.args[0] for c in r.play.call_args_list]
        self.assertEqual(plays[0], "dictate")

    def test_dictation_key_down_wakes_before_dictate(self):
        r = _run_linux(press=["KEY_F13"], target=_target(), asleep=True)
        plays = [c.args[0] for c in r.play.call_args_list]
        self.assertEqual(plays[:2], ["wake", "dictate"])

    def test_key_up_sounds_unchanged(self):
        # key-up only appends the result cue; the key-down cue is untouched
        r = _run_linux(press=["KEY_INSERT"], handle_ok=True)
        self.assertEqual([c.args[0] for c in r.play.call_args_list],
                         ["start", "detected"])
        r = _run_linux(press=["KEY_F13"], target=_target())
        self.assertEqual([c.args[0] for c in r.play.call_args_list],
                         ["dictate", "typed"])

    def test_legacy_hotkey_still_drives_assistant(self):
        r = _run_linux(press=["KEY_RIGHTCTRL"], dictation_key="",
                       assistant_key="", legacy_key="KEY_RIGHTCTRL")
        self.assertEqual(set(r.captured["keys"]), {"KEY_RIGHTCTRL"})
        self.assertEqual(r.calls["captures"], 0)
        r.app.handle_utterance.assert_called_once_with("hello world")

    def test_wrong_key_release_does_not_cross_lanes(self):
        def overlap(keys):
            d_down, d_up = keys["KEY_F13"]
            a_down, a_up = keys["KEY_INSERT"]

            d_down()  # dictation open
            stream = _FakeStream.instances[-1]
            chunk = np.full((4096, 1), 0.1, dtype="float32")
            stream.callback(chunk, len(chunk), None, None)
            a_down()  # ignored: a stream is already open
            a_up()    # must not route/type the assistant lane
            d_up()    # only the owned release delivers

        r = _run_linux(dispatch=overlap, target=_target())
        r.type_dict.assert_called_once()
        r.app.handle_utterance.assert_not_called()

    def test_no_keys_configured_is_noop(self):
        r = _run_linux(press=[], dictation_key="", assistant_key="",
                       legacy_key="")
        self.assertNotIn("keys", r.captured)  # listen_many never reached
        r.app.handle_utterance.assert_not_called()


class PttKeyMapTest(unittest.TestCase):
    def test_empty_names_are_dropped(self):
        cfg = Config()
        cfg.ptt.dictation_key = ""
        cfg.ptt.assistant_key = ""
        cfg.hotkey.key = ""
        self.assertEqual(_linux_ptt_keys(cfg, MagicMock(), MagicMock()), {})

    def test_assistant_wins_a_colliding_key(self):
        cfg = Config()
        cfg.ptt.dictation_key = "KEY_F13"
        cfg.ptt.assistant_key = "KEY_F13"
        cfg.hotkey.key = ""
        started: list = []
        keys = _linux_ptt_keys(cfg,
                               lambda mode: started.append(("start", mode)),
                               lambda mode: started.append(("stop", mode)))
        self.assertEqual(list(keys), ["KEY_F13"])
        keys["KEY_F13"][0]()
        self.assertEqual(started, [("start", "assistant")])


class ListenManyTest(unittest.TestCase):
    def setUp(self):
        if hotkey.evdev is None:
            self.skipTest("python-evdev is not installed")

    def test_empty_map_rejected(self):
        with self.assertRaises(ValueError):
            hotkey.listen_many({})

    def test_empty_key_name_rejected(self):
        with self.assertRaises(ValueError):
            hotkey.listen_many({"": (lambda: None, lambda: None)})

    def test_unknown_key_name_rejected(self):
        with self.assertRaises(ValueError):
            hotkey.listen_many({"KEY_NOPE": (lambda: None, lambda: None)})

    def test_multiple_keys_accepted_and_dispatched(self):
        pressed: list = []
        captured: dict = {}

        def fake_loop(handlers, **kwargs):
            captured["handlers"] = handlers
            captured["label"] = kwargs.get("label")

        with patch.object(hotkey, "_listen_loop", side_effect=fake_loop):
            hotkey.listen_many({
                "KEY_F13": (lambda: pressed.append("f13"), lambda: None),
                "KEY_INSERT": (lambda: pressed.append("insert"), lambda: None),
            })

        handlers = captured["handlers"]
        f13 = hotkey.resolve_keycode("KEY_F13")
        insert = hotkey.resolve_keycode("KEY_INSERT")
        self.assertEqual(set(handlers), {f13, insert})
        self.assertEqual(captured["label"], "KEY_F13, KEY_INSERT")

        handlers[f13][0]()   # press
        handlers[f13][0]()   # auto-repeat is dropped by the edge guard
        handlers[f13][1]()   # release
        handlers[insert][0]()
        self.assertEqual(pressed, ["f13", "insert"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
