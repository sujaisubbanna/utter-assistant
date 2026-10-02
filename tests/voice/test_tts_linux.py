#!/usr/bin/env python3
"""Linux TTS backend: engine selection, argv, voice mapping — never a real engine.

Hermetic: ``shutil.which`` and ``subprocess.Popen`` are stubbed, so no audio is
produced and no external binary is required.

    .venv-agent/bin/python tests/voice/test_tts_linux.py
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.voice import tts


def which_map(mapping):
    return lambda name: mapping.get(name)


class RecordingPopen:
    calls: list = []

    def __init__(self, argv, **kwargs):
        RecordingPopen.calls.append((list(argv), kwargs))
        self.argv = list(argv)
        self.stdout = io.BytesIO()
        self.stdin = io.BytesIO()

    def poll(self):
        return 0  # treat as finished so _reap() drops it

    def terminate(self):
        pass


def cfg(**kw):
    base = dict(engine="auto", language="auto", voice="")
    base.update(kw)
    return SimpleNamespace(**base)


class TestEngineSelection(unittest.TestCase):
    def test_prefers_espeak_ng_then_espeak_then_spd(self):
        self.assertEqual(
            tts.select_engine("auto", which=which_map({"espeak-ng": "/x", "espeak": "/y", "spd-say": "/z"})),
            "espeak-ng")
        self.assertEqual(
            tts.select_engine("auto", which=which_map({"espeak": "/y", "spd-say": "/z"})),
            "espeak")
        self.assertEqual(
            tts.select_engine("auto", which=which_map({"spd-say": "/z"})),
            "spd-say")

    def test_piper_is_preferred_only_with_a_voice_model(self):
        present = which_map({"piper": "/p", "espeak-ng": "/e"})
        self.assertEqual(tts.select_engine("auto", which=present, piper_model="/v.onnx"), "piper")
        self.assertEqual(tts.select_engine("auto", which=present, piper_model=None), "espeak-ng")

    def test_none_and_missing(self):
        self.assertEqual(tts.select_engine("none", which=which_map({"espeak-ng": "/e"})), "none")
        self.assertEqual(tts.select_engine("auto", which=which_map({})), "none")
        # An explicitly requested but missing engine degrades to the auto order.
        self.assertEqual(
            tts.select_engine("espeak", which=which_map({"espeak-ng": "/e"})), "espeak-ng")

    def test_backend_for(self):
        self.assertEqual(tts.backend_for("darwin", SimpleNamespace(tts_backend="say")), "say")
        self.assertEqual(tts.backend_for("darwin", SimpleNamespace(tts_backend="AVSpeech")), "avspeech")
        self.assertEqual(tts.backend_for("linux", None, which=which_map({})), "none")
        self.assertEqual(
            tts.backend_for("linux", None, tts_cfg=cfg(), which=which_map({"espeak-ng": "/e"})),
            "espeak-ng")


class TestVoiceMapping(unittest.TestCase):
    def test_espeak_voice_for(self):
        self.assertEqual(tts.espeak_voice_for("de-DE"), "de")
        self.assertEqual(tts.espeak_voice_for("pt-BR"), "pt")
        self.assertEqual(tts.espeak_voice_for("en-GB"), "en-gb")
        self.assertEqual(tts.espeak_voice_for("en"), "en")
        self.assertEqual(tts.espeak_voice_for(""), "")
        self.assertEqual(tts.espeak_voice_for(None), "")

    def test_argv_builders(self):
        self.assertEqual(tts.espeak_argv("espeak-ng", "hola", "es"),
                         ["espeak-ng", "-v", "es", "--", "hola"])
        self.assertEqual(tts.espeak_argv("espeak", "-dash"),
                         ["espeak", "--", "-dash"])
        self.assertEqual(tts.spd_say_argv("hola", "es-ES"),
                         ["spd-say", "-l", "es", "--", "hola"])
        self.assertTrue(tts.player_argv("aplay", 16000)[-1] == "-")

    def test_piper_resolution_and_sample_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            model = directory / "de_DE-thorsten-medium.onnx"
            model.write_bytes(b"onnx")
            (directory / "de_DE-thorsten-medium.onnx.json").write_text(
                '{"audio": {"sample_rate": 16000}}')
            self.assertEqual(tts.resolve_piper_model("", "de-DE", dirs=[directory]), str(model))
            self.assertEqual(tts.resolve_piper_model("thorsten", "auto", dirs=[directory]), str(model))
            self.assertIsNone(tts.resolve_piper_model("", "fr-FR", dirs=[directory]))
            self.assertEqual(tts.piper_sample_rate(str(model)), 16000)
            self.assertEqual(tts.piper_sample_rate(str(directory / "missing.onnx")), 22050)


class TestSpeakLinux(unittest.TestCase):
    def setUp(self):
        tts._speaking.clear()
        RecordingPopen.calls.clear()

    def _speak(self, text, config, which):
        with patch.object(tts.platform, "is_macos", return_value=False), \
                patch.object(tts.platform, "is_linux", return_value=True), \
                patch.object(tts.shutil, "which", side_effect=which), \
                patch.object(tts.subprocess, "Popen", RecordingPopen):
            return tts.speak(text, SimpleNamespace(tts=config))

    def test_espeak_uses_language_derived_voice(self):
        ok = self._speak("hallo", cfg(language="de-DE"),
                         which_map({"espeak-ng": "/usr/bin/espeak-ng"}))
        self.assertTrue(ok)
        argv, kwargs = RecordingPopen.calls[0]
        self.assertEqual(argv, ["espeak-ng", "-v", "de", "--", "hallo"])
        self.assertNotIn("shell", kwargs)

    def test_explicit_voice_wins_over_language(self):
        self._speak("hello", cfg(language="de-DE", voice="en-gb"),
                    which_map({"espeak-ng": "/usr/bin/espeak-ng"}))
        self.assertEqual(RecordingPopen.calls[0][0],
                         ["espeak-ng", "-v", "en-gb", "--", "hello"])

    def test_piper_streams_to_a_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "de_DE-x.onnx"
            model.write_bytes(b"onnx")
            ok = self._speak("hallo", cfg(engine="piper", language="de-DE", voice=str(model)),
                             which_map({"piper": "/usr/bin/piper", "pw-play": "/usr/bin/pw-play"}))
        self.assertTrue(ok)
        self.assertEqual(RecordingPopen.calls[0][0],
                         ["piper", "--model", str(model), "--output-raw"])
        self.assertEqual(RecordingPopen.calls[1][0][0], "pw-play")

    def test_missing_engine_returns_false_and_logs(self):
        with self.assertLogs("utter.voice.tts", level="WARNING") as logs:
            ok = self._speak("hallo", cfg(), which_map({}))
        self.assertFalse(ok)
        self.assertEqual(RecordingPopen.calls, [])
        self.assertIn("no local speech engine", "\n".join(logs.output))

    def test_empty_text_is_false(self):
        with patch.object(tts.platform, "is_macos", return_value=False), \
                patch.object(tts.platform, "is_linux", return_value=True):
            self.assertFalse(tts.speak("   ", SimpleNamespace(tts=cfg())))


if __name__ == "__main__":
    unittest.main()