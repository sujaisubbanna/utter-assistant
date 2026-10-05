#!/usr/bin/env python3
"""`assistant recommend` must name a pullable store source for its tiers.

A user (or the settings UI) should be able to take the suggested model and run
``assistant models pull <source>``. Only real, documented repos are emitted; a
tier with no known source omits the field rather than inventing one.

The vision and decision/planner tiers are **not** store-pullable: their repos
are multi-file (sharded safetensors), and the store fetches a single file. Those
tiers carry a ``provision`` script (``scripts/install_inference.sh``) and, where
known, an ``hf_repo`` — never a ``source``.

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
                vision = recommend.suggest(_hw(vram))["vision"]
                self.assertNotIn("source", vision)
                self.assertEqual(vision["provision"], recommend.INSTALL_INFERENCE)

    def test_vision_carries_the_documented_repo(self):
        vision = recommend.suggest(_hw(8.0))["vision"]
        self.assertEqual(vision["hf_repo"], "ByteDance-Seed/UI-TARS-2B-SFT")

    def test_decision_tier_is_provisioned_not_pulled(self):
        decision = recommend.suggest(_hw(24.0))["decision_llm"]
        self.assertNotIn("source", decision)
        self.assertEqual(decision["provision"], recommend.INSTALL_INFERENCE)
        self.assertEqual(decision["hf_repo"], recommend.PLANNER_HF_REPO)

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

    def test_cpu_only_tiers_have_no_provision(self):
        # No GPU: vision is accessibility-only and the decision head runs on CPU
        # or an existing endpoint, so the vLLM provisioner does not apply.
        s = recommend.suggest(_hw(0.0))
        self.assertNotIn("provision", s["vision"])
        self.assertNotIn("provision", s["decision_llm"])

    def test_human_output_prints_the_install_command(self):
        report = {"hardware": _hw(0.0), "suggestions": recommend.suggest(_hw(0.0))}
        text = recommend.human(report)
        self.assertIn("assistant models pull hf:ggerganov/whisper.cpp:ggml-base.en.bin", text)
        # No dead vision pull is advertised on a CPU-only machine.
        self.assertNotIn("install_inference", text)

    def test_human_output_points_at_the_provisioner_for_gpu_tiers(self):
        report = {"hardware": _hw(24.0), "suggestions": recommend.suggest(_hw(24.0))}
        text = recommend.human(report)
        self.assertIn(f"provision: {recommend.INSTALL_INFERENCE}", text)
        self.assertIn(recommend.PLANNER_HF_REPO, text)
        self.assertNotIn("assistant models pull", text)

    def test_json_report_omits_the_vision_source(self):
        report = {"hardware": _hw(24.0), "suggestions": recommend.suggest(_hw(24.0))}
        decoded = json.loads(json.dumps(report))
        self.assertNotIn("source", decoded["suggestions"]["vision"])
        self.assertEqual(decoded["suggestions"]["vision"]["provision"],
                         recommend.INSTALL_INFERENCE)


if __name__ == "__main__":
    unittest.main()
