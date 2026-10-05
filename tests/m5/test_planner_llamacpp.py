#!/usr/bin/env python3
"""Per-platform planner selection for the inference provisioner. Hermetic.

* macOS / Windows select the llama.cpp (GGUF) planner; Linux keeps vLLM + AWQ;
* ``status`` reports ``planner_backend`` and the backend-appropriate path;
* the llama.cpp release asset names and serve flags are pinned exactly;
* the pinned build tag is honoured without any network access.

No network, pip, venv or subprocess is touched.

    .venv-agent/bin/python tests/m5/test_planner_llamacpp.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from assistant import inference  # noqa: E402

SERVE_SCRIPT = ROOT / "scripts" / "serve_planner_llamacpp.sh"


class BackendSelectionTests(unittest.TestCase):
    def test_platform_plan_selects_backend(self):
        self.assertEqual(inference.platform_plan("linux").planner_backend, "vllm")
        self.assertEqual(inference.platform_plan("macos").planner_backend, "llamacpp")
        self.assertEqual(
            inference.platform_plan("windows", cuda=False).planner_backend, "llamacpp"
        )

    def test_planner_backend_defaults_to_host(self):
        with mock.patch("assistant.inference._platform_name", return_value="macos"):
            self.assertEqual(inference.planner_backend(), "llamacpp")
        with mock.patch("assistant.inference._platform_name", return_value="windows"):
            self.assertEqual(inference.planner_backend(), "llamacpp")
        with mock.patch("assistant.inference._platform_name", return_value="linux"):
            self.assertEqual(inference.planner_backend(), "vllm")

    def test_serve_planner_script_is_backend_aware(self):
        self.assertEqual(inference.serve_planner_script("linux"), "scripts/serve_planner.sh")
        self.assertEqual(inference.serve_planner_script("macos"),
                         "scripts/serve_planner_llamacpp.sh")
        self.assertEqual(inference.serve_planner_script("windows"),
                         "scripts/serve_planner_llamacpp.sh")

    def test_planner_model_id_is_backend_aware(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(inference.planner_model_id("linux"),
                             inference.DEFAULT_PLANNER_MODEL_ID)
            self.assertEqual(inference.planner_model_id("macos"),
                             inference.LLAMACPP_PLANNER_MODEL_ID)
            self.assertEqual(inference.planner_model_id("windows"),
                             inference.LLAMACPP_PLANNER_MODEL_ID)

    def test_planner_model_id_override_wins(self):
        with mock.patch.dict(os.environ, {"UTTER_PLANNER_MODEL_ID": "me/custom"}, clear=True):
            self.assertEqual(inference.planner_model_id("macos"), "me/custom")

    def test_model_ids_matches_the_planner_backend(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(inference.model_ids("linux")[1],
                             inference.DEFAULT_PLANNER_MODEL_ID)
            self.assertEqual(inference.model_ids("macos")[1],
                             inference.LLAMACPP_PLANNER_MODEL_ID)
            self.assertEqual(inference.model_ids("windows")[1],
                             inference.LLAMACPP_PLANNER_MODEL_ID)


class AssetTests(unittest.TestCase):
    def test_macos_assets(self):
        self.assertEqual(inference.llamacpp_assets("b11146", "macos", arch="arm64"),
                         ("llama-b11146-bin-macos-arm64.tar.gz",))
        self.assertEqual(inference.llamacpp_assets("11146", "macos", arch="x86_64"),
                         ("llama-b11146-bin-macos-x64.tar.gz",))

    def test_windows_assets(self):
        self.assertEqual(
            inference.llamacpp_assets("b11146", "windows", cuda=True),
            ("llama-b11146-bin-win-cuda-12.4-x64.zip",
             "cudart-llama-bin-win-cuda-12.4-x64.zip"),
        )
        self.assertEqual(inference.llamacpp_assets("b11146", "windows", cuda=False),
                         ("llama-b11146-bin-win-cpu-x64.zip",))

    def test_linux_has_no_llamacpp_asset(self):
        self.assertEqual(inference.llamacpp_assets("b11146", "linux"), ())

    def test_resolved_tag_can_be_pinned_without_network(self):
        with mock.patch.dict(os.environ, {"UTTER_LLAMACPP_TAG": "b99999"}, clear=True):
            self.assertEqual(inference.resolve_llamacpp_tag(), "b99999")


class StatusTests(unittest.TestCase):
    def test_status_llamacpp_reports_backend_and_gguf_path(self):
        with tempfile.TemporaryDirectory(prefix="lav-plan-gguf-") as d:
            gguf = Path(d) / inference.LLAMACPP_GGUF_FILE
            gguf.write_bytes(b"GGUF")
            with mock.patch("assistant.inference._platform_name", return_value="macos"):
                with mock.patch.dict(os.environ,
                                     {"UTTER_PLANNER_MODEL_PATH": str(gguf)}, clear=False):
                    data = inference.status()
        self.assertIn("planner_backend", data)
        self.assertEqual(data["planner_backend"], "llamacpp")
        self.assertTrue(data["planner"])
        self.assertEqual(data["planner_path"], str(gguf))

    def test_status_llamacpp_missing_when_no_gguf(self):
        with tempfile.TemporaryDirectory(prefix="lav-plan-none-") as d:
            empty = Path(d) / "empty"
            empty.mkdir()
            with mock.patch("assistant.inference._platform_name", return_value="windows"):
                with mock.patch.dict(os.environ,
                                     {"UTTER_PLANNER_MODEL_PATH": str(empty)}, clear=False):
                    data = inference.status()
        self.assertEqual(data["planner_backend"], "llamacpp")
        self.assertFalse(data["planner"])

    def test_planner_gguf_path_accepts_file_or_dir(self):
        with tempfile.TemporaryDirectory(prefix="lav-plan-path-") as d:
            directory = Path(d) / "model"
            directory.mkdir()
            with mock.patch.dict(os.environ,
                                 {"UTTER_PLANNER_MODEL_PATH": str(directory)}, clear=True):
                self.assertEqual(inference.planner_gguf_path(),
                                 directory / inference.LLAMACPP_GGUF_FILE)
            file = Path(d) / "custom.gguf"
            with mock.patch.dict(os.environ,
                                 {"UTTER_PLANNER_MODEL_PATH": str(file)}, clear=True):
                self.assertEqual(inference.planner_gguf_path(), file)


class ServeFlagTests(unittest.TestCase):
    def test_serve_command_has_the_pinned_flags(self):
        cmd = inference.serve_planner_command("llama-server", "model.gguf")
        self.assertEqual(cmd[:5], ["llama-server", "--model", "model.gguf",
                                   "--alias", "qwen3-4b"])
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
        self.assertEqual(cmd[cmd.index("--port") + 1], "8001")
        self.assertEqual(cmd[cmd.index("-c") + 1], "4096")
        self.assertEqual(cmd[cmd.index("-ngl") + 1], "auto")
        self.assertEqual(cmd[cmd.index("-fa") + 1], "auto")
        self.assertEqual(cmd[cmd.index("--reasoning") + 1], "off")
        self.assertEqual(cmd[cmd.index("-np") + 1], "1")
        for flag in ("--jinja", "--no-webui"):
            self.assertIn(flag, cmd)

    def test_serve_script_contains_the_flags_and_defaults(self):
        text = SERVE_SCRIPT.read_text(encoding="utf-8")
        for token in ("--alias", "--host 127.0.0.1", "--port", "-c", "-ngl",
                      "-fa auto", "--jinja", "--reasoning off", "-np 1",
                      "--no-webui", "UTTER_PLANNER_PORT:-8001",
                      "UTTER_PLANNER_CTX:-4096", "UTTER_LLAMACPP_NGL:-auto",
                      inference.LLAMACPP_GGUF_FILE):
            self.assertIn(token, text, token)


class CheckProbeTests(unittest.TestCase):
    def test_unreachable_planner_is_a_clear_failure(self):
        with mock.patch("assistant.inference._http_json",
                        side_effect=urllib.error.URLError("connection refused")):
            data = inference.check()
        self.assertFalse(data["ok"])
        self.assertFalse(data["reachable"])
        self.assertIn("no planner server reachable", data["detail"])
        self.assertEqual(data["base_url"], "http://127.0.0.1:8001/v1")

    def test_successful_probe_checks_tool_call_and_json(self):
        calls: list[dict] = []

        def fake_http(method, url, payload=None, timeout=8.0):
            calls.append({"url": url, "payload": payload})
            if url.endswith("/models"):
                return {"data": [{"id": "qwen3-4b"}]}
            if payload and "tools" in payload:
                return {"choices": [{"finish_reason": "tool_calls",
                                     "message": {"tool_calls": [
                                         {"function": {"name": "focus_app",
                                                       "arguments": '{"app":"firefox"}'}}]}}]}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": '{"ok": true}'}}]}

        with mock.patch.dict(os.environ, {"UTTER_PLANNER_BASE_URL": "http://x/v1"}, clear=True):
            with mock.patch("assistant.inference._http_json", side_effect=fake_http):
                data = inference.check()
        self.assertTrue(data["ok"], data)
        self.assertTrue(data["tool_call"]["ok"])
        self.assertTrue(data["json_schema"]["ok"])
        self.assertEqual(data["models"], ["qwen3-4b"])
        # The check must send the nested json_schema wrapper, never the flat form.
        schema_payload = next(c["payload"] for c in calls if c["payload"] and "response_format" in c["payload"])
        self.assertEqual(schema_payload["response_format"]["type"], "json_schema")
        self.assertIn("json_schema", schema_payload["response_format"])
        self.assertNotIn("schema", schema_payload["response_format"])


if __name__ == "__main__":
    unittest.main()
