#!/usr/bin/env python3
"""Windows backends: pure-logic tests (run anywhere) + import smoke (Windows).

Linux/macOS can exercise all the pure parts — key-name/virtual-key mapping,
the push-to-talk edge detector, chord parsing, Unicode event generation and the
dispatch seams — without Windows and without importing ``ctypes.windll``. The
``Win32SmokeTest`` class is skipped unless the interpreter is actually on
Windows.

Usage::

    .venv-agent/bin/python tests/voice/test_windows_backends.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utter.types import Action, ActionResult, Tier  # noqa: E402
from utter.win32 import hotkey as whotkey  # noqa: E402
from utter.win32 import inject as winject  # noqa: E402
from utter.win32 import pointer as wpointer  # noqa: E402


class KeyMappingTest(unittest.TestCase):
    def test_windows_names(self):
        self.assertEqual(whotkey.resolve_keycode("f13"), 0x7C)
        self.assertEqual(whotkey.resolve_keycode("insert"), 0x2D)
        self.assertEqual(whotkey.resolve_keycode("rightctrl"), 0xA3)
        self.assertEqual(whotkey.resolve_keycode("a"), 0x41)
        self.assertEqual(whotkey.resolve_keycode("A"), 0x41)
        # A bare digit is a numeric virtual-key code (macOS precedent); the
        # digit *key* is reached through its evdev/named spelling.
        self.assertEqual(whotkey.resolve_keycode("5"), 5)
        self.assertEqual(whotkey.resolve_keycode("KEY_5"), 0x35)
        self.assertEqual(whotkey.resolve_keycode("Return"), 0x0D)

    def test_evdev_names_from_shared_config(self):
        # The [ptt]/[hotkey] defaults are evdev names; Windows must resolve them.
        self.assertEqual(whotkey.resolve_keycode("KEY_F13"), 0x7C)
        self.assertEqual(whotkey.resolve_keycode("KEY_INSERT"), 0x2D)
        self.assertEqual(whotkey.resolve_keycode("KEY_RIGHTCTRL"), 0xA3)
        self.assertEqual(whotkey.resolve_keycode("KEY_RIGHTALT"), 0xA5)
        self.assertEqual(whotkey.resolve_keycode("KEY_LEFTMETA"), 0x5B)
        self.assertEqual(whotkey.resolve_keycode("KEY_ESC"), 0x1B)

    def test_macos_style_aliases(self):
        self.assertEqual(whotkey.resolve_keycode("right_option"), 0xA5)
        self.assertEqual(whotkey.resolve_keycode("right_command"), 0x5C)
        self.assertEqual(whotkey.resolve_keycode("cmd"), 0x5B)

    def test_bare_integer_and_normalize(self):
        self.assertEqual(whotkey.resolve_keycode("190"), 190)
        self.assertEqual(whotkey.normalize_key("KEY_F13"), "key_f13")
        self.assertEqual(whotkey.normalize_key("Right_Option"), "rightalt")
        self.assertEqual(whotkey.normalize_key("page-up"), "page_up")

    def test_unknown_and_empty_raise(self):
        with self.assertRaises(ValueError):
            whotkey.resolve_keycode("KEY_NOPE")
        with self.assertRaises(ValueError):
            whotkey.resolve_keycode("")
        with self.assertRaises(ValueError):
            whotkey.normalize_key("   ")

    def test_modifier_classification(self):
        self.assertTrue(whotkey.is_modifier(0xA3))
        self.assertTrue(whotkey.is_modifier(0x5B))
        self.assertFalse(whotkey.is_modifier(0x41))


class PTTStateTest(unittest.TestCase):
    def test_press_release_edges(self):
        state = whotkey.PTTState(0x7C)
        self.assertEqual(state.feed("down", 0x7C), "press")
        # Auto-repeat while held must be ignored.
        self.assertIsNone(state.feed("down", 0x7C))
        self.assertEqual(state.feed("up", 0x7C), "release")
        self.assertIsNone(state.feed("up", 0x7C))
        # A second full cycle still works.
        self.assertEqual(state.feed("down", 0x7C), "press")
        self.assertEqual(state.feed("up", 0x7C), "release")

    def test_other_key_and_raw_message_ids(self):
        state = whotkey.PTTState(0x7C)
        self.assertIsNone(state.feed("down", 0x41))
        self.assertEqual(state.feed(0x0100, 0x7C), "press")   # WM_KEYDOWN
        self.assertIsNone(state.feed(0x0100, 0x7C))           # repeat
        self.assertEqual(state.feed(0x0101, 0x7C), "release")  # WM_KEYUP
        self.assertEqual(state.feed(0x0104, 0x7C), "press")    # WM_SYSKEYDOWN
        self.assertEqual(state.feed(0x0105, 0x7C), "release")  # WM_SYSKEYUP

    def test_release_without_press_is_none(self):
        self.assertIsNone(whotkey.PTTState(0x7C).feed("up", 0x7C))


class DispatchTest(unittest.TestCase):
    def test_dispatch_maps_edges_to_handlers(self):
        calls: list = []
        states = {0x7C: (whotkey.PTTState(0x7C),
                         (lambda: calls.append("press"), lambda: calls.append("release")))}
        whotkey._dispatch(states, "down", 0x7C)
        whotkey._dispatch(states, "down", 0x7C)
        whotkey._dispatch(states, "up", 0x7C)
        whotkey._dispatch(states, "down", 0x41)  # not watched
        self.assertEqual(calls, ["press", "release"])

    def test_dispatch_swallows_handler_errors(self):
        def boom() -> None:
            raise RuntimeError("handler blew up")

        states: dict = {0x7C: (whotkey.PTTState(0x7C), (boom, boom))}
        with patch.object(whotkey.logger, "exception"):
            whotkey._dispatch(states, "down", 0x7C)  # must not raise
            whotkey._dispatch(states, "up", 0x7C)


class ChordTest(unittest.TestCase):
    def test_parse_chords(self):
        self.assertEqual(winject.parse_chord("ctrl+t"), ([0xA2], 0x54))
        self.assertEqual(winject.parse_chord("ctrl+shift+Return"), ([0xA2, 0xA0], 0x0D))
        self.assertEqual(winject.parse_chord("super+space"), ([0x5B], 0x20))
        self.assertEqual(winject.parse_chord("Enter"), ([], 0x0D))

    def test_parse_errors(self):
        with self.assertRaises(ValueError):
            winject.parse_chord("")
        with self.assertRaises(ValueError):
            winject.parse_chord("hyper+t")
        with self.assertRaises(ValueError):
            winject.parse_chord("ctrl+KEY_NOPE")

    def test_unicode_events_plain_and_surrogate(self):
        events = winject._text_events("A")
        self.assertEqual(events, [
            (0, 0x41, winject.KEYEVENTF_UNICODE),
            (0, 0x41, winject.KEYEVENTF_UNICODE | winject.KEYEVENTF_KEYUP),
        ])
        # U+1F600 is encoded as the surrogate pair D83D DE00.
        emoji = winject._text_events("\U0001F600")
        units = [scan for (_vk, scan, _flags) in emoji]
        self.assertEqual(units, [0xD83D, 0xD83D, 0xDE00, 0xDE00])

    def test_chord_events_order_and_keyup(self):
        events = winject._chord_events([0xA2], 0x54)
        self.assertEqual([(vk, flags) for vk, _scan, flags in events], [
            (0xA2, 0), (0x54, 0),
            (0x54, winject.KEYEVENTF_KEYUP),
            (0xA2, winject.KEYEVENTF_KEYUP),
        ])
        # Right-control is an extended key.
        right = winject._chord_events([], 0xA3)
        self.assertTrue(right[0][2] & winject.KEYEVENTF_EXTENDEDKEY)


class PointerTablesTest(unittest.TestCase):
    def test_button_and_scroll_tables(self):
        self.assertIn("left", wpointer._BUTTONS)
        self.assertIn("right", wpointer._BUTTONS)
        self.assertIn("middle", wpointer._BUTTONS)
        self.assertEqual(wpointer._SCROLL_DIR["up"], (0, 1))
        self.assertEqual(wpointer._SCROLL_DIR["down"], (0, -1))


class SeamDispatchTest(unittest.TestCase):
    """The OS seams must route to the Win32 backends on Windows and nowhere else."""

    def test_voice_hotkey_delegates_on_windows(self):
        from utter.voice import hotkey as vhotkey

        sentinel = object()
        with patch("utter.platform.is_windows", return_value=True), \
             patch("utter.win32.hotkey.listen_many", return_value=sentinel) as listen:
            self.assertIs(vhotkey.listen_many({"KEY_F13": (lambda: None, lambda: None)}),
                          sentinel)
            listen.assert_called_once()

    def test_voice_hotkey_stays_evdev_off_windows(self):
        from utter.voice import hotkey as vhotkey

        with patch("utter.platform.is_windows", return_value=False), \
             patch.object(vhotkey, "evdev", None):
            with self.assertRaises(RuntimeError):  # evdev absent -> cannot listen
                vhotkey.listen_many({"KEY_F13": (lambda: None, lambda: None)})

    def test_keyboard_actions_delegate_on_windows(self):
        from utter.actions import keyboard

        expected = ActionResult(True, Action.KEY, Tier.KEYBOARD, "win32")
        with patch("utter.platform.is_windows", return_value=True), \
             patch("utter.win32.inject.send_key", return_value=expected) as send:
            self.assertIs(keyboard.send_key("ctrl+t"), expected)
            send.assert_called_once_with("ctrl+t", pid=None)

    def test_mouse_actions_delegate_on_windows(self):
        from utter.actions import mouse

        expected = ActionResult(True, Action.CLICK_POINT, Tier.KEYBOARD, "win32")
        with patch("utter.platform.is_windows", return_value=True), \
             patch("utter.win32.pointer.click_point", return_value=expected) as click:
            self.assertIs(mouse.click_point(10, 20), expected)
            click.assert_called_once_with(10, 20, "left")

    def test_run_windows_no_keys_returns_cleanly(self):
        """run_windows' prologue must run without a real audio/STT stack."""
        import utter.daemon as daemon
        from utter.config import Config

        app = daemon.Utter.__new__(daemon.Utter)
        app.cfg = Config()
        fake_sd = types.ModuleType("sounddevice")
        with patch.dict(sys.modules, {"sounddevice": fake_sd}), \
             patch("utter.voice.stt.Transcriber.for_platform",
                   return_value=MagicMock(backend="fake", fallbacks=[])), \
             patch("utter.daemon._Osd"), \
             patch("utter.daemon._linux_ptt_keys", return_value={}), \
             patch("utter.sleep.get", return_value=MagicMock(asleep=False)), \
             patch("utter.sleep.idle", return_value=MagicMock()), \
             patch("utter.daemon._play"):
            daemon.Utter.run_windows(app)  # no keys -> logs and returns

    def test_daemon_dispatches_run_windows(self):
        import utter.daemon as daemon

        calls: list = []
        saved = (daemon.Utter.setup, daemon.Utter.run_windows,
                 daemon.Utter.run_macos, daemon.Utter.run_hotkey)
        daemon.Utter.setup = lambda self: None
        daemon.Utter.run_windows = lambda self: calls.append("windows")
        daemon.Utter.run_macos = lambda self: calls.append("macos")
        daemon.Utter.run_hotkey = lambda self: calls.append("hotkey")
        try:
            with patch("utter.platform.is_windows", return_value=True):
                rc = daemon.main([])
        finally:
            (daemon.Utter.setup, daemon.Utter.run_windows,
             daemon.Utter.run_macos, daemon.Utter.run_hotkey) = saved
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["windows"])


class RunWindowsCycleTest(unittest.TestCase):
    """Drive the whole Windows PTT dictation cycle with a faked audio/STT stack."""

    def test_dictation_press_types_transcript(self):
        import numpy as np

        import utter.daemon as daemon
        from utter.config import Config, SleepConfig
        from utter.types import FocusedWindow

        class FakeStream:
            def __init__(self, *, callback=None, **_kw):
                self.callback = callback

            def start(self) -> None:
                pass

            def stop(self) -> None:
                pass

            def close(self) -> None:
                pass

        streams: list = []

        def make_stream(**kwargs):
            stream = FakeStream(**kwargs)
            streams.append(stream)
            return stream

        fake_sd = types.ModuleType("sounddevice")
        fake_sd.InputStream = make_stream  # type: ignore[attr-defined]

        class FakeStt:
            backend = "fake"
            fallbacks: list = []

            def transcribe(self, _audio) -> str:
                return "hello world"

        app = daemon.Utter.__new__(daemon.Utter)
        app.cfg = Config()
        app.cfg.sleep = SleepConfig(services=[])
        app.handle_utterance = MagicMock(return_value=True)

        typed: list = []

        def fake_type(text, pid=None):
            typed.append((text, pid))
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "ok")

        def fake_listen(keys, **_kw):
            down, up = keys[app.cfg.ptt.dictation_key]  # KEY_F13
            down()  # key-down: open stream + pin target
            chunk = np.full((4096, 1), 0.1, dtype="float32")
            streams[-1].callback(chunk, len(chunk), None, None)
            up()  # key-up: transcribe + deliver

        target = FocusedWindow(app_id="win.app", title="Docs", pid=99, window_id=1)
        with patch.dict(sys.modules, {"sounddevice": fake_sd}), \
             patch("utter.voice.hotkey.listen_many", side_effect=fake_listen), \
             patch("utter.voice.stt.Transcriber.for_platform",
                   return_value=FakeStt()), \
             patch("utter.daemon._Osd"), \
             patch("utter.daemon._play"), \
             patch("utter.daemon._capture_dictation_target", return_value=target), \
             patch("utter.actions.keyboard.type_text", side_effect=fake_type), \
             patch("utter.dictation._still_focused", return_value=True), \
             patch("utter.sleep.get", return_value=MagicMock(asleep=False)), \
             patch("utter.sleep.idle", return_value=MagicMock()):
            daemon.Utter.run_windows(app)

        self.assertEqual(typed, [("hello world", None)])


@unittest.skipUnless(sys.platform == "win32", "requires Windows")
class Win32SmokeTest(unittest.TestCase):
    """Import/shape smoke: only runs on a real Windows interpreter."""

    def test_modules_import_and_expose_api(self):
        for fn in (whotkey.listen, whotkey.listen_many, whotkey.resolve_keycode):
            self.assertTrue(callable(fn))
        for fn in (winject.send_key, winject.type_text, winject.parse_chord):
            self.assertTrue(callable(fn))
        for fn in (wpointer.move_to, wpointer.click_point, wpointer.scroll):
            self.assertTrue(callable(fn))

    def test_listen_many_empty_raises(self):
        with self.assertRaises(ValueError):
            whotkey.listen_many({})


if __name__ == "__main__":
    unittest.main(verbosity=2)
