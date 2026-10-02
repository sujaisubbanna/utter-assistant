#!/usr/bin/env python3
"""STT language threading: no hardcoded "en", both whisper backends + Apple Speech.

Hermetic: models and the Speech framework are stubbed, no model is loaded and
no audio is decoded.

    .venv-agent/bin/python tests/voice/test_stt_language.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from utter.voice import stt

AUDIO = np.zeros(1600, dtype=np.float32)


class FakeModel:
    """Records the kwargs each backend passes to the engine."""

    def __init__(self, *, information=None, text="hallo wereld"):
        self.calls: list = []
        self.information = information
        self.text = text

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        if self.information is not None:
            return [SimpleNamespace(text=self.text)], self.information
        return [SimpleNamespace(text=self.text)]


def cfg(**kw):
    base = dict(backend="whisper_cpp", model="small", device="cpu",
                compute_type="int8", language="auto")
    base.update(kw)
    return SimpleNamespace(**base)


class TestEnglishOnlyDetection(unittest.TestCase):
    def test_english_only_models(self):
        for model in ("distil-small.en", "small.en", "base.en", "tiny.en",
                      "ggml-base.en.bin", "ggml-small.en-q5_1.bin", "ggml-tiny.en" ):
            self.assertTrue(stt.is_english_only_model(model), model)

    def test_multilingual_models(self):
        for model in ("small", "base", "large-v3", "large-v3-turbo",
                      "distil-large-v3", "ggml-medium.bin", ""):
            self.assertFalse(stt.is_english_only_model(model), model)


class TestWhisperCppLanguage(unittest.TestCase):
    def test_explicit_language_is_passed_as_base_code(self):
        t = stt.Transcriber(cfg(language="de_DE"))
        t._model = FakeModel()
        text = t._transcribe_whisper_cpp(AUDIO)
        self.assertEqual(text, "hallo wereld")
        self.assertEqual(t._model.calls[0]["language"], "de")
        self.assertEqual(t.last_language, "de")

    def test_auto_does_not_send_en(self):
        t = stt.Transcriber(cfg(language="auto"))
        t._model = FakeModel()
        with patch.dict(os.environ, {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}):
            t._transcribe_whisper_cpp(AUDIO)
        self.assertIsNone(t._model.calls[0]["language"])
        self.assertNotEqual(t._model.calls[0]["language"], "en")

    def test_auto_follows_system_locale(self):
        t = stt.Transcriber(cfg(language="auto"))
        t._model = FakeModel()
        with patch.dict(os.environ, {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "de_DE.UTF-8"}):
            t._transcribe_whisper_cpp(AUDIO)
        self.assertEqual(t._model.calls[0]["language"], "de")


class TestFasterWhisperLanguage(unittest.TestCase):
    def test_explicit_language_and_detected_metadata(self):
        t = stt.Transcriber(cfg(backend="faster_whisper", language="de-DE"))
        t._model = FakeModel(information=SimpleNamespace(language="de"))
        text = t._transcribe_faster_whisper(AUDIO)
        self.assertEqual(text, "hallo wereld")
        self.assertEqual(t._model.calls[0]["language"], "de")
        self.assertEqual(t.last_language, "de")

    def test_auto_omits_language_rather_than_en(self):
        t = stt.Transcriber(cfg(backend="faster_whisper", language="auto"))
        t._model = FakeModel(information=SimpleNamespace(language="nl"))
        with patch.dict(os.environ, {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}):
            t._transcribe_faster_whisper(AUDIO)
        self.assertNotIn("language", t._model.calls[0])
        self.assertNotEqual(t._model.calls[0].get("language"), "en")
        self.assertEqual(t.last_language, "nl")


class TestEnglishOnlyWarning(unittest.TestCase):
    def test_warns_for_non_english_with_en_model(self):
        t = stt.Transcriber(cfg(language="de-DE", model="distil-small.en"))
        with self.assertLogs("utter.voice.stt", level="WARNING") as logs:
            t._warn_english_only("distil-small.en")
        message = "\n".join(logs.output)
        self.assertIn("English-only", message)
        self.assertIn("large-v3-turbo", message)

    def test_no_warning_when_language_english_or_model_multilingual(self):
        cases = [
            ("en-GB", "distil-small.en"),
            ("de-DE", "small"),
            (None, "distil-small.en"),
        ]
        for language_code, model in cases:
            t = stt.Transcriber(cfg(language=language_code or "auto", model=model))
            with patch.dict(os.environ, {"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}):
                with patch.object(stt.logger, "warning") as warn:
                    t._warn_english_only(model)
            self.assertFalse(warn.called, (language_code, model))


class FakeRecognizer:
    instances: list = []

    def __init__(self, locale="en-US", on_device=True):
        self.locale = locale
        self.on_device = on_device
        FakeRecognizer.instances.append(self)

    def load(self) -> None:
        pass


class TestMacosLocalePassthrough(unittest.TestCase):
    def setUp(self):
        FakeRecognizer.instances = []

    def _load(self, *, language, speech_locale="en-US", env=None):
        mac = SimpleNamespace(speech_locale=speech_locale, on_device_only=True)
        t = stt.Transcriber(cfg(language=language), macos_cfg=mac)
        with patch.dict(os.environ, env or {}), \
                patch("utter.macos.speech.AppleSpeechRecognizer", FakeRecognizer):
            t._load_apple_speech()
        return FakeRecognizer.instances[-1], t

    def test_resolved_language_becomes_the_sfspeech_locale(self):
        rec, t = self._load(language="de-DE")
        self.assertEqual(rec.locale, "de-DE")
        self.assertEqual(t.last_language, "de-DE")

    def test_auto_follows_system_locale(self):
        rec, _t = self._load(language="auto", env={
            "LC_ALL": "", "LC_MESSAGES": "", "LANG": "en_GB.UTF-8"})
        self.assertEqual(rec.locale, "en-GB")

    def test_unknown_falls_back_to_speech_locale(self):
        rec, _t = self._load(language="auto", speech_locale="fr-FR", env={
            "LC_ALL": "", "LC_MESSAGES": "", "LANG": ""})
        self.assertEqual(rec.locale, "fr-FR")


if __name__ == "__main__":
    unittest.main()