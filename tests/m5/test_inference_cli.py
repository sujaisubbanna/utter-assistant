#!/usr/bin/env python3
"""`assistant inference`: NDJSON framing + model-dir status. Hermetic.

The install path streams a subprocess, so the subprocess is stubbed — no
network, no pip, no real download. ``status`` runs against a throwaway models
dir via the same ``UTTER_*_MODEL_PATH`` overrides the shell provisioner uses.

    .venv-agent/bin/python tests/m5/test_inference_cli.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from assistant import inference  # noqa: E402


class _FakeProc:
    """Stand-in for subprocess.Popen: a line stream plus an exit code."""

    def __init__(self, lines: list[str], rc: int) -> None:
        self.stdout = iter([f"{line}\n" for line in lines])
        self.returncode = rc

    def wait(self) -> int:
        return self.returncode


def _run_install(json_progress: bool, lines: list[str], rc: int) -> tuple[int, str]:
    out = io.StringIO()
    with mock.patch("assistant.inference.subprocess.Popen",
                    return_value=_FakeProc(lines, rc)):
        with contextlib.redirect_stdout(out):
            code = inference.install(json_progress=json_progress)
    return code, out.getvalue()


class InstallNdjsonTests(unittest.TestCase):
    def test_start_progress_done_framing(self):
        code, raw = _run_install(True, ["creating .venv", "downloading vision"], 0)
        self.assertEqual(code, 0)
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        self.assertEqual(events[0], {"event": "start"})
        self.assertEqual(events[-1], {"event": "done", "ok": True})
        progress = [e for e in events if e["event"] == "progress"]
        self.assertEqual([e["line"] for e in progress],
                         ["creating .venv", "downloading vision"])
        # Every progress event is exactly {event, line}.
        self.assertTrue(all(set(e) == {"event", "line"} for e in progress))

    def test_nonzero_exit_emits_error(self):
        code, raw = _run_install(True, ["boom"], 2)
        self.assertEqual(code, 1)
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        self.assertEqual(events[0], {"event": "start"})
        self.assertEqual(events[-1]["event"], "error")
        self.assertIn("2", events[-1]["error"])

    def test_human_mode_streams_lines_without_json(self):
        code, raw = _run_install(False, ["one", "two"], 0)
        self.assertEqual(code, 0)
        self.assertEqual(raw.splitlines(), ["one", "two"])
        self.assertNotIn('"event"', raw)

    def test_windows_is_refused(self):
        out = io.StringIO()
        with mock.patch("assistant.inference._is_windows", return_value=True):
            with contextlib.redirect_stdout(out):
                code = inference.install(json_progress=True)
        self.assertEqual(code, 1)
        events = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        self.assertEqual(events[0], {"event": "start"})
        self.assertEqual(events[-1]["event"], "error")
        self.assertIn("Windows", events[-1]["error"])


class StatusTests(unittest.TestCase):
    def test_status_reports_completeness(self):
        with tempfile.TemporaryDirectory(prefix="lav-inference-") as d:
            tmp = Path(d)
            vision = tmp / "vision"
            planner = tmp / "planner"
            vision.mkdir()
            (vision / "config.json").write_text("{}", encoding="utf-8")
            (vision / "model-00001-of-00002.safetensors").write_bytes(b"x")
            planner.mkdir()
            (planner / "config.json").write_text("{}", encoding="utf-8")  # no weights
            with mock.patch.dict(os.environ, {
                "UTTER_VISION_MODEL_PATH": str(vision),
                "UTTER_PLANNER_MODEL_PATH": str(planner),
            }):
                data = inference.status()
            self.assertEqual(set(data),
                             {"vision", "planner", "vision_path", "planner_path"})
            self.assertTrue(data["vision"])
            self.assertFalse(data["planner"])
            self.assertEqual(data["vision_path"], str(vision))
            self.assertEqual(data["planner_path"], str(planner))

    def test_sharded_index_counts_as_present(self):
        with tempfile.TemporaryDirectory(prefix="lav-inference-") as d:
            planner = Path(d) / "planner"
            planner.mkdir()
            (planner / "config.json").write_text("{}", encoding="utf-8")
            (planner / "model.safetensors.index.json").write_text("{}", encoding="utf-8")
            with mock.patch.dict(os.environ, {"UTTER_PLANNER_MODEL_PATH": str(planner)}):
                self.assertTrue(inference.model_present(planner))

    def test_human_names_the_serve_script(self):
        data = inference.status()
        text = inference.human(data)
        self.assertIn("serve:", text)

    def test_serve_script_is_platform_aware(self):
        with mock.patch("assistant.inference._is_macos", return_value=True):
            self.assertEqual(inference.serve_script(),
                             "scripts/serve_vision_transformers.py")
        with mock.patch("assistant.inference._is_macos", return_value=False):
            self.assertEqual(inference.serve_script(), "scripts/serve_vision.sh")


class ParserTests(unittest.TestCase):
    def test_cli_registers_inference_subcommands(self):
        from assistant.__main__ import build_parser

        parsed = build_parser().parse_args(["inference", "status", "--json"])
        self.assertEqual(parsed.inference_action, "status")
        self.assertTrue(parsed.json)
        parsed = build_parser().parse_args(["inference", "install", "--json"])
        self.assertEqual(parsed.inference_action, "install")
        self.assertTrue(parsed.json)


if __name__ == "__main__":
    unittest.main()
