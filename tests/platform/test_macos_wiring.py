#!/usr/bin/env python3
"""Regression: macOS runner/daemon wiring.

* The launchd runner agent must point at the production ``config.runner.toml``
  (real ``plugins/utter_py``), not ``runner/config.example.toml`` (echo stubs).
* The agent must export ``UTTER_DRY_RUN=0`` so it performs real desktop actions.
* ``run_macos`` must idle-sleep and wake the sleeper on push-to-talk, like
  ``run_hotkey``; historically it never called ``idle.start()`` /
  ``idle.begin()`` / ``sleeper.wake()``.

Runs hermetically on Linux by faking the hotkey/STT/audio stack.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utter.config import Config
from utter.daemon import Utter


class TestRunnerPlistConfig(unittest.TestCase):
    def test_runner_agent_uses_production_config(self):
        plist = (ROOT / "macos" / "com.utter.runner.plist").read_text()
        self.assertIn("@REPO@/config.runner.toml", plist)
        self.assertNotIn("config.example.toml", plist)

    def test_runner_agent_enables_real_actions(self):
        plist = (ROOT / "macos" / "com.utter.runner.plist").read_text()
        self.assertIn("<key>UTTER_DRY_RUN</key>", plist)
        self.assertIn("<string>0</string>", plist)


class _FakeStream:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def _fake_sounddevice() -> types.ModuleType:
    """A stand-in module so the real PortAudio library is never imported
    (importing it can block on a live audio server)."""
    module = types.ModuleType("sounddevice")
    module.InputStream = _FakeStream  # type: ignore[attr-defined]
    return module


class _FakeStt:
    backend = "apple_speech"
    fallbacks = ["whisper_cpp"]

    def transcribe(self, _audio):
        return "open youtube"


class TestMacosSleepWiring(unittest.TestCase):
    def _run(self, *, asleep: bool):
        app = Utter.__new__(Utter)
        app.cfg = Config()
        app.handle_utterance = MagicMock(return_value=True)

        calls = {"begin": [], "end": [], "start": 0, "wake": 0, "keys": None}

        idle = MagicMock()
        idle.begin.side_effect = lambda tok: calls["begin"].append(tok)
        idle.end.side_effect = lambda tok: calls["end"].append(tok)
        idle.start.side_effect = lambda: calls.__setitem__("start", calls["start"] + 1)

        sleeper = MagicMock()
        sleeper.asleep = asleep
        sleeper.wake.side_effect = lambda: calls.__setitem__("wake", calls["wake"] + 1)

        def fake_listen_many(keys, backend=None):
            calls["keys"] = keys
            # Simulate the assistant key: down then up.
            down, up = keys[app.cfg.macos.assistant_key]
            down()
            up()

        with patch("utter.macos.permissions.status_all", return_value={"permissions": []}), \
             patch("utter.voice.stt.Transcriber.for_platform", return_value=_FakeStt()), \
             patch.dict(sys.modules, {"sounddevice": _fake_sounddevice()}), \
             patch("utter.macos.hotkey.listen_many", side_effect=fake_listen_many), \
             patch("utter.daemon._play"), patch("utter.daemon._notify"), \
             patch("utter.sleep.get", return_value=sleeper), \
             patch("utter.sleep.idle", return_value=idle):
            Utter.run_macos(app)
        return calls, app

    def test_idle_wraps_listen_and_wakes(self):
        calls, app = self._run(asleep=True)
        # idle watcher started at loop entry (before listen_many).
        self.assertEqual(calls["start"], 1)
        # key-down begins the listen idle window and wakes the sleeper.
        self.assertEqual(calls["begin"], ["listen"])
        self.assertEqual(calls["wake"], 1)
        # key-up ends the window even though this clip is too short to route.
        self.assertEqual(calls["end"], ["listen"])
        self.assertFalse(app.handle_utterance.called)

    def test_does_not_wake_when_already_awake(self):
        calls, _ = self._run(asleep=False)
        self.assertEqual(calls["begin"], ["listen"])
        self.assertEqual(calls["wake"], 0)
        self.assertEqual(calls["end"], ["listen"])


if __name__ == "__main__":
    unittest.main()
