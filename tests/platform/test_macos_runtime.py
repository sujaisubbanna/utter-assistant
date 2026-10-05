#!/usr/bin/env python3
"""Platform-aware runtime resolution and detection tests.

Verifies:
  - macOS runtime resolution: Metal GPU, Ollama LLM, Ollama Vision, Apple Speech / whisper.cpp, say.
  - Linux runtime resolution: CUDA/ROCm GPU, vLLM LLM/Vision, whisper.cpp, espeak-ng.
  - Graceful degradation when external tools (Ollama, VocaMac) are unavailable or not installed.
  - Config parsing for [macos.runtime] and synchronization with [macos].
  - CLI settings resolution for macos.runtime keys.

Runs hermetically on Linux by forcing UTTER_PLATFORM=darwin/linux.
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter import platform, runtime
from utter.config import (Config, MacosConfig, MacosRuntimeConfig, RouterConfig,
                          VisionConfig, load_config)


@contextlib.contextmanager
def forced_platform(name: str):
    orig = os.environ.get("UTTER_PLATFORM")
    os.environ["UTTER_PLATFORM"] = name
    try:
        yield
    finally:
        if orig is None:
            os.environ.pop("UTTER_PLATFORM", None)
        else:
            os.environ["UTTER_PLATFORM"] = orig


class TestMacosRuntime(unittest.TestCase):
    def test_probe_macos_gpu(self):
        with forced_platform("darwin"):
            info = runtime.probe_macos_gpu()
            self.assertTrue(info["available"])
            self.assertEqual(info["runtime"], "metal")
            self.assertIn("Metal", info["name"])
            self.assertGreaterEqual(info.get("unified_memory_gb", 0), 1.0)

    def test_probe_ollama_unavailable_path(self):
        """When Ollama is not running, it must return a structured result with no exceptions."""
        with patch.object(runtime.urllib.request, "urlopen", side_effect=OSError("Connection refused")):
            with patch("shutil.which", return_value=None):
                info = runtime.probe_ollama("http://127.0.0.1:11434/v1", timeout=0.1)
                self.assertFalse(info["installed"])
                self.assertFalse(info["running"])
                self.assertEqual(info["models"], [])
                self.assertEqual(info["status"], "not_installed")

            with patch("shutil.which", return_value="/usr/local/bin/ollama"):
                info = runtime.probe_ollama("http://127.0.0.1:11434/v1", timeout=0.1)
                self.assertTrue(info["installed"])
                self.assertFalse(info["running"])
                self.assertEqual(info["models"], [])
                self.assertEqual(info["status"], "stopped")

    def test_probe_ollama_ready_path(self):
        """When Ollama answers /v1/models, models are parsed and status is ready."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"data": [{"id": "qwen2.5:3b"}, {"id": "llama3.2-vision:11b"}]}'
        mock_resp.__enter__.return_value = mock_resp

        with patch.object(runtime.urllib.request, "urlopen", return_value=mock_resp):
            with patch("shutil.which", return_value="/usr/local/bin/ollama"):
                info = runtime.probe_ollama("http://127.0.0.1:11434/v1", timeout=0.1)
                self.assertTrue(info["installed"])
                self.assertTrue(info["running"])
                self.assertEqual(info["models"], ["qwen2.5:3b", "llama3.2-vision:11b"])
                self.assertEqual(info["status"], "ready")

    def test_probe_vocamac_detection(self):
        with patch.object(runtime.Path, "is_file", return_value=False), patch("shutil.which", return_value=None):
            info = runtime.probe_vocamac()
            self.assertFalse(info["installed"])
            self.assertEqual(info["status"], "not_installed")

        with patch.object(runtime.Path, "is_file", return_value=True):
            info = runtime.probe_vocamac()
            self.assertTrue(info["installed"])
            self.assertEqual(info["status"], "installed")

    def test_probe_runtime_macos_structure_and_degradation(self):
        """Full probe_runtime on macOS must report all roles without hanging or crashing."""
        with forced_platform("darwin"):
            with patch.object(runtime, "probe_http_models", return_value=(False, [], "Connection refused")):
                with patch("shutil.which", return_value=None):
                    rep = runtime.probe_runtime()
                    self.assertEqual(rep["platform"], "darwin")
                    self.assertEqual(rep["device"], "metal")
                    self.assertEqual(rep["gpu"]["runtime"], "metal")

                    # LLM role
                    self.assertIn("llm", rep)
                    self.assertEqual(rep["llm"]["provider"], "ollama")
                    self.assertFalse(rep["llm"]["available"])
                    self.assertEqual(rep["llm"]["status"], "not_installed")

                    # Vision role
                    self.assertIn("vision", rep)
                    self.assertFalse(rep["vision"]["available"])

                    # STT role
                    self.assertIn("stt", rep)
                    self.assertEqual(rep["stt"]["primary"], "whisper_cpp")
                    self.assertEqual(rep["stt"]["fallback"], "apple_speech")

                    # TTS role
                    self.assertIn("tts", rep)
                    self.assertEqual(rep["tts"]["engine"], "say")

    def test_probe_runtime_linux_structure(self):
        with forced_platform("linux"):
            # Hermetic: pass an explicit config so the probe never reads the
            # developer's ~/.config/utter/config.toml.
            rep = runtime.probe_runtime(cfg=Config())
            self.assertEqual(rep["platform"], "linux")
            self.assertIn(rep["device"], ("cuda", "rocm", "cpu"))
            self.assertEqual(rep["llm"]["provider"], "vllm")
            self.assertEqual(rep["vision"]["provider"], "vllm")
            self.assertEqual(rep["stt"]["primary"], "whisper_cpp")

    def test_resolve_router_platform_aware(self):
        cfg = Config()
        # Linux resolution -> unchanged vLLM defaults
        with forced_platform("linux"):
            r_linux = runtime.resolve_router(cfg)
            self.assertEqual(r_linux.llm_base_url, "http://127.0.0.1:8001/v1")
            self.assertEqual(r_linux.llm_model, "qwen3-4b")

        # macOS resolution -> Metal Ollama defaults
        with forced_platform("darwin"):
            r_mac = runtime.resolve_router(cfg)
            self.assertEqual(r_mac.llm_base_url, "http://127.0.0.1:11434/v1")
            self.assertEqual(r_mac.llm_model, "qwen2.5:3b")

    def test_resolve_vision_platform_aware(self):
        cfg = Config()
        # Linux resolution -> unchanged UI-TARS vLLM defaults
        with forced_platform("linux"):
            v_linux = runtime.resolve_vision(cfg)
            self.assertEqual(v_linux.base_url, "http://127.0.0.1:8000/v1")
            self.assertEqual(v_linux.model, "uitars")
            self.assertEqual(v_linux.cuda_visible_devices, "1")

        # macOS resolution -> Metal VLM defaults with CUDA cleared
        with forced_platform("darwin"):
            v_mac = runtime.resolve_vision(cfg)
            self.assertEqual(v_mac.base_url, "http://127.0.0.1:11434/v1")
            self.assertEqual(v_mac.model, "llama3.2-vision:11b")
            self.assertEqual(v_mac.cuda_visible_devices, "")

    def test_resolve_router_accepts_a_router_config(self):
        # The planner passes cfg.router; the resolver must return it as-is on
        # every platform. Regression: Linux read ``cfg.router`` on a RouterConfig
        # and raised AttributeError, which crashed the voice daemon.
        rc = RouterConfig()
        self.assertIs(runtime.resolve_router(rc, platform_name="linux"), rc)

    def test_resolve_vision_accepts_a_vision_config(self):
        vc = VisionConfig()
        self.assertIs(runtime.resolve_vision(vc, platform_name="linux"), vc)

    def test_config_macos_runtime_toml_merging(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.toml"
            p.write_text("""
[macos.runtime]
llm_provider = "lm_studio"
llm_base_url = "http://127.0.0.1:1234/v1"
llm_model = "qwen2.5-coder:7b"
vision_model = "qwen2.5-vl:7b"
""")
            cfg = load_config(p)
            self.assertEqual(cfg.macos.runtime.llm_provider, "lm_studio")
            self.assertEqual(cfg.macos.runtime.llm_base_url, "http://127.0.0.1:1234/v1")
            self.assertEqual(cfg.macos.runtime.llm_model, "qwen2.5-coder:7b")
            self.assertEqual(cfg.macos.runtime.vision_model, "qwen2.5-vl:7b")
            # Flat attributes synced
            self.assertEqual(cfg.macos.llm_model, "qwen2.5-coder:7b")

            with forced_platform("darwin"):
                r = runtime.resolve_router(cfg)
                self.assertEqual(r.llm_base_url, "http://127.0.0.1:1234/v1")
                self.assertEqual(r.llm_model, "qwen2.5-coder:7b")

                v = runtime.resolve_vision(cfg)
                self.assertEqual(v.model, "qwen2.5-vl:7b")

    def test_cli_setting_spec_macos_runtime(self):
        from utter.cli import _setting_spec
        spec = _setting_spec("macos.runtime.llm_model")
        self.assertIsNotNone(spec)
        section, key, typ, default = spec
        self.assertEqual(section, "macos.runtime")
        self.assertEqual(key, "llm_model")
        self.assertEqual(typ, str)
        self.assertEqual(default, "qwen2.5:3b")

        # Flat macos.llm_model also works
        spec_flat = _setting_spec("macos.llm_model")
        self.assertIsNotNone(spec_flat)
        self.assertEqual(spec_flat[0], "macos")
        self.assertEqual(spec_flat[1], "llm_model")


class TestMacosDefaultsDoNotRequireVocamac(unittest.TestCase):
    """Regression: VocaMac is an opt-in backend, never a default or a prompt.

    A default macOS install must chain whisper.cpp -> Apple Speech, and an
    absent VocaMac.app must not show up as a missing dependency (which the
    settings app renders as "install VocaMac") nor in the STT guidance text.
    """

    def test_default_stt_chain_is_whisper_then_apple(self):
        from utter.voice import stt
        chain = stt.select_backends(
            "darwin", Config().stt, Config().macos,
            has_module=lambda _n: False, which=lambda _n: None,
        )
        self.assertEqual(chain, ["whisper_cpp", "apple_speech"])

    def test_deps_omit_vocamac_when_absent(self):
        from assistant import deps as deps_mod
        with forced_platform("darwin"):
            with patch.object(deps_mod, "_vocamac_installed", return_value=False):
                report = deps_mod.probe_deps()
        self.assertNotIn("vocamac", report)
        self.assertNotIn("vocamac", deps_mod.missing_deps(report))

    def test_deps_include_vocamac_when_installed(self):
        from assistant import deps as deps_mod
        with forced_platform("darwin"):
            with patch.object(deps_mod, "_vocamac_installed", return_value=True):
                report = deps_mod.probe_deps()
        self.assertTrue(report.get("vocamac"))
        self.assertNotIn("vocamac", deps_mod.missing_deps(report))

    def test_stt_unavailable_message_never_requires_vocamac(self):
        with forced_platform("darwin"):
            with patch.object(runtime, "probe_http_models",
                              return_value=(False, [], "Connection refused")), \
                    patch.object(runtime.platform, "has_module", return_value=False), \
                    patch.object(runtime.shutil, "which", return_value=None), \
                    patch.object(runtime.Path, "is_file", return_value=False):
                rep = runtime.probe_runtime(cfg=Config())
        stt_role = rep["stt"]
        self.assertFalse(stt_role["available"])
        self.assertNotIn("vocamac", stt_role["message"].lower())
        self.assertEqual(stt_role["primary"], "whisper_cpp")
        self.assertEqual(stt_role["fallback"], "apple_speech")

    def test_runner_start_hint_is_macos_specific(self):
        from assistant import doctor
        with forced_platform("darwin"):
            hint = doctor._runner_start_hint()
        self.assertIn("brew services start utter", hint)
        self.assertIn("launchctl kickstart", hint)
        self.assertNotIn("systemctl", hint)

    def test_status_socket_error_is_actionable_and_macos_aware(self):
        import argparse
        import io
        from assistant import __main__ as cli_main
        from assistant.runner_client import RunnerClient

        class _Boom(RunnerClient):
            def connect(self):  # noqa: D401 - test double
                raise FileNotFoundError(2, "No such file or directory")

        with forced_platform("darwin"):
            with patch.object(cli_main, "RunnerClient", _Boom):
                buf = io.StringIO()
                with contextlib.redirect_stderr(buf):
                    rc = cli_main.cmd_status(
                        argparse.Namespace(json=False, timeout=0.1))
        message = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("runner isn't running", message)
        self.assertIn("brew services start utter", message)
        self.assertNotIn("systemctl", message)


if __name__ == "__main__":
    unittest.main()
