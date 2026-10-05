#!/usr/bin/env python3
"""`assistant recommend` must name a pullable store source for its tiers.

A user (or the settings UI) should be able to take the suggested model and run
``assistant models pull <source>``. Only real, documented repos are emitted; a
tier with no known source omits the field rather than inventing one.

    .venv-agent/bin/python tests/test_recommend_source.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assistant import recommend


def _hw(vram: float, vendor: str = "nvidia") -> dict:
    return {
        "cpu": {"model": "Test CPU", "cores": 8},
        "ram_gb": 64.0,
        "gpus": [{"name": "Test GPU", "vendor": vendor, "vram_gb": vram}],
        "vulkan": False,
        "accel_devices": [],
        "session": "x11",
    }


class TestRecommendSources(unittest.TestCase):
    def test_vision_tiers_omit_unpullable_sources(self):
        # UI-TARS repos are sharded safetensors and cannot be store-pulled, so
        # no vision tier advertises a `source` (provision with install_inference.sh).
        for vram in (24.0, 8.0):
            with self.subTest(vram=vram):
                self.assertNotIn("source", recommend.suggest(_hw(vram))["vision"])

    def test_whisper_cpp_tiers_are_pullable(self):
        cpu = recommend.suggest(_hw(0.0))
        self.assertEqual(cpu["stt"]["source"], "hf:ggerganov/whisper.cpp:ggml-base.en.bin")
        vulkan = recommend.suggest(_hw(0.0, vendor="amd"))
        self.assertEqual(vulkan["stt"]["source"], "hf:ggerganov/whisper.cpp:ggml-small.bin")

    def test_tier_without_a_known_source_omits_it(self):
        # faster-whisper models are resolved by the backend, not the store.
        s = recommend.suggest(_hw(24.0))
        self.assertNotIn("source", s["decision_llm"])
        # Sharded vision repos have no documented single-file source.
        self.assertNotIn("source", recommend.suggest(_hw(8.0))["vision"])

    def test_human_output_prints_the_install_command(self):
        report = {"hardware": _hw(0.0), "suggestions": recommend.suggest(_hw(0.0))}
        text = recommend.human(report)
        self.assertIn("assistant models pull hf:ggerganov/whisper.cpp:ggml-base.en.bin", text)
        # No dead vision pull is advertised.
        self.assertNotIn("install_inference", text)

    def test_json_report_omits_the_vision_source(self):
        report = {"hardware": _hw(24.0), "suggestions": recommend.suggest(_hw(24.0))}
        decoded = json.loads(json.dumps(report))
        self.assertNotIn("source", decoded["suggestions"]["vision"])


if __name__ == "__main__":
    unittest.main()
