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
    def test_24gb_vision_tier_has_the_documented_source(self):
        s = recommend.suggest(_hw(24.0))
        self.assertEqual(s["vision"]["model"], "UI-TARS-7B")
        self.assertEqual(s["vision"]["source"], "hf:ByteDance-Seed/UI-TARS-1.5-7B")

    def test_whisper_cpp_tiers_are_pullable(self):
        cpu = recommend.suggest(_hw(0.0))
        self.assertEqual(cpu["stt"]["source"], "hf:ggerganov/whisper.cpp:ggml-base.en.bin")
        vulkan = recommend.suggest(_hw(0.0, vendor="amd"))
        self.assertEqual(vulkan["stt"]["source"], "hf:ggerganov/whisper.cpp:ggml-small.bin")

    def test_tier_without_a_known_source_omits_it(self):
        # faster-whisper models are resolved by the backend, not the store.
        s = recommend.suggest(_hw(24.0))
        self.assertNotIn("source", s["decision_llm"])
        # A 8 GB GPU suggests UI-TARS-2B, which has no documented single source.
        self.assertNotIn("source", recommend.suggest(_hw(8.0))["vision"])

    def test_human_output_prints_the_install_command(self):
        report = {"hardware": _hw(24.0), "suggestions": recommend.suggest(_hw(24.0))}
        text = recommend.human(report)
        self.assertIn("assistant models pull hf:ByteDance-Seed/UI-TARS-1.5-7B", text)

    def test_json_report_carries_the_source(self):
        report = {"hardware": _hw(24.0), "suggestions": recommend.suggest(_hw(24.0))}
        decoded = json.loads(json.dumps(report))
        self.assertEqual(decoded["suggestions"]["vision"]["source"],
                         "hf:ByteDance-Seed/UI-TARS-1.5-7B")


if __name__ == "__main__":
    unittest.main()
