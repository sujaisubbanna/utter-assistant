#!/usr/bin/env python3
"""Windows speech/vision backends: dispatch, STT chain and lazy imports.

Runs on Linux/macOS without any Windows runtime: the Windows-only packages
(``comtypes``, ``pywin32``, ``mss``) are never imported at module import time,
so the pure logic and dispatch can be exercised anywhere. The actual SAPI/mss
calls are smoke-tested only under ``skipUnless(sys.platform == "win32")``.

    .venv-agent/bin/python tests/platform/test_windows_backends.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.config import Config
from utter.types import Rect
from utter.voice import stt, tts

WIN = "windows"


def _has_whisper(_name):
    return True


def _has_nothing(_name):
    return False


class TestWindowsSttChain(unittest.TestCase):
    """``select_backends("windows", ...)`` is pure and probe-injectable."""

    def test_default_chain_is_whisper_cpp_plus_importable_faster_whisper(self):
        chain = stt.select_backends(WIN, SimpleNamespace(backend="whisper_cpp"),
                                    has_module=_has_whisper)
        self.assertEqual(chain, ["whisper_cpp", "faster_whisper"])

    def test_fallback_omitted_when_faster_whisper_missing(self):
        chain = stt.select_backends(WIN, SimpleNamespace(backend="whisper_cpp"),
                                    has_module=_has_nothing)
        self.assertEqual(chain, ["whisper_cpp"])

    def test_explicit_faster_whisper_is_primary(self):
        chain = stt.select_backends(WIN, SimpleNamespace(backend="faster_whisper"),
                                    has_module=_has_whisper)
        self.assertEqual(chain, ["faster_whisper"])

    def test_none_disables_transcription(self):
        self.assertEqual(
            stt.select_backends(WIN, SimpleNamespace(backend="none"), has_module=_has_whisper),
            ["none"])
        self.assertEqual(
            stt.select_backends(WIN, SimpleNamespace(backend="off"), has_module=_has_whisper),
            ["none"])

    def test_macos_only_backend_falls_back_to_whisper_cpp(self):
        chain = stt.select_backends(WIN, SimpleNamespace(backend="apple_speech"),
                                    has_module=_has_whisper)
        self.assertEqual(chain, ["whisper_cpp", "faster_whisper"])

    def test_linux_and_macos_unchanged(self):
        self.assertEqual(
            stt.select_backends("linux", SimpleNamespace(backend="whisper_cpp"),
                                has_module=_has_whisper),
            ["whisper_cpp"])
        mac = SimpleNamespace(stt_backend="apple_speech", stt_fallback="whisper_cpp")
        self.assertEqual(
            stt.select_backends("darwin", SimpleNamespace(backend="whisper_cpp"), mac,
                                has_module=lambda n: n in ("Speech", "Foundation"),
                                which=lambda _n: None),
            ["apple_speech", "whisper_cpp"])

    def test_for_platform_windows_uses_whispercpp(self):
        t = stt.Transcriber.for_platform(Config(), platform_name=WIN)
        self.assertEqual(t.backend, "whisper_cpp")  # faster_whisper not installed here
        for name in t.fallbacks:
            self.assertIn(name, stt.WINDOWS_BACKENDS)


class TestWindowsTtsSelection(unittest.TestCase):
    def test_default_is_sapi(self):
        self.assertEqual(tts.backend_for(WIN, None), "sapi")
        self.assertEqual(tts.select_windows_engine(None), "sapi")

    def test_explicit_engines_and_none(self):
        self.assertEqual(tts.backend_for(WIN, None, tts_cfg=SimpleNamespace(engine="pyttsx3")),
                         "pyttsx3")
        for off in ("none", "off", "false", "0"):
            self.assertEqual(tts.backend_for(WIN, None, tts_cfg=SimpleNamespace(engine=off)),
                             "none")

    def test_unknown_engine_degrades_to_sapi(self):
        self.assertEqual(tts.backend_for(WIN, None, tts_cfg=SimpleNamespace(engine="wat")),
                         "sapi")

    def test_linux_and_macos_unchanged(self):
        self.assertEqual(tts.backend_for("darwin", SimpleNamespace(tts_backend="say")), "say")
        self.assertEqual(tts.backend_for("linux", None, which=lambda _n: None), "none")


class TestWindowsSpeechDispatch(unittest.TestCase):
    def test_speak_routes_to_win32_tts(self):
        calls = []

        def fake_speak(text, **kwargs):
            calls.append((text, kwargs))
            return True

        cfg = SimpleNamespace(tts=SimpleNamespace(enabled=True, engine="auto", voice="Zira",
                                                   rate=0))
        with patch.dict(os.environ, {"UTTER_PLATFORM": WIN}), \
                patch("utter.win32.tts.speak", side_effect=fake_speak):
            ok = tts.speak("hallo", cfg)
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], "hallo")
        self.assertEqual(calls[0][1]["backend"], "sapi")
        self.assertEqual(calls[0][1]["voice"], "Zira")

    def test_speak_disabled_by_config(self):
        cfg = SimpleNamespace(tts=SimpleNamespace(enabled=False, engine="auto", voice="", rate=0))
        with patch.dict(os.environ, {"UTTER_PLATFORM": WIN}), \
                patch("utter.win32.tts.speak") as fake:
            self.assertFalse(tts.speak("hallo", cfg))
        fake.assert_not_called()


class TestWindowsScreenshotDispatch(unittest.TestCase):
    def test_capture_routes_to_win32(self):
        sentinel = ("C:/tmp/shot.png", Rect(0, 0, 1920, 1080))
        with patch("utter.vision.screenshot.platform.is_windows", return_value=True), \
                patch("utter.win32.screenshot.capture", return_value=sentinel) as capture:
            from utter.vision import screenshot

            self.assertEqual(screenshot.capture(), sentinel)
        capture.assert_called_once()

    def test_capture_output_shape_without_mss(self):
        from utter.win32 import screenshot as ws

        monitor = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "shot-monitor-0.png"

            def fake_grab(path, mon):
                self.assertEqual(mon, monitor)
                path.write_bytes(b"\x89PNG\r\n")

            with patch.object(ws, "_SHOT_DIR", Path(tmp)), \
                    patch.object(ws, "_monitors", return_value=[{"left": 0, "top": 0,
                                                                 "width": 1920, "height": 1080},
                                                                monitor]), \
                    patch.object(ws, "_grab_to", side_effect=fake_grab):
                path, rect = ws.capture_output(0)
        self.assertEqual(Path(path), out)
        self.assertEqual(rect, Rect(0, 0, 1920, 1080))
        self.assertEqual(ws.monitor_rect(monitor), Rect(0, 0, 1920, 1080))


class TestLazyImports(unittest.TestCase):
    def test_win32_package_imports_without_windows_deps(self):
        for name in ("utter.win32", "utter.win32.tts", "utter.win32.screenshot"):
            self.assertIsNotNone(importlib.import_module(name))
        # Importing the modules must not pull in the Windows-only packages.
        self.assertNotIn("comtypes", sys.modules)
        self.assertNotIn("mss", sys.modules)
        self.assertNotIn("pyttsx3", sys.modules)

    def test_sapi_rate_mapping(self):
        from utter.win32 import tts as win_tts

        self.assertEqual(win_tts._rate_to_sapi(0), 0)
        self.assertEqual(win_tts._rate_to_sapi("bad"), 0)
        self.assertEqual(win_tts._rate_to_sapi(200), 0)
        self.assertGreater(win_tts._rate_to_sapi(400), 0)
        self.assertLess(win_tts._rate_to_sapi(100), 0)
        self.assertEqual(win_tts._rate_to_sapi(100000), 10)


@unittest.skipUnless(sys.platform == "win32", "Windows only: needs SAPI/mss")
class TestWindowsGated(unittest.TestCase):
    def test_backends_expose_the_expected_interface(self):
        from utter.win32 import screenshot, tts as win_tts

        self.assertTrue(callable(win_tts.speak))
        self.assertTrue(callable(win_tts.stop))
        self.assertTrue(callable(screenshot.capture))
        self.assertTrue(callable(screenshot.capture_output))
        self.assertTrue(callable(screenshot.total_geometry))

    def test_screenshot_capture_returns_path_and_rect(self):
        from utter.win32 import screenshot

        path, rect = screenshot.capture()
        self.assertTrue(Path(path).is_file())
        self.assertIsInstance(rect, Rect)
        self.assertGreater(rect.w, 0)
        self.assertGreater(rect.h, 0)

    def test_stt_chain_on_real_windows(self):
        t = stt.Transcriber.for_platform(Config(), platform_name=WIN)
        self.assertEqual(t.backend, "whisper_cpp")


if __name__ == "__main__":
    unittest.main()
