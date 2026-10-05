#!/usr/bin/env python3
"""Regression: whisper.cpp STT + its model are mandatory in ``macos/setup.sh``.

Apple Speech is the default macOS STT backend, but whisper.cpp is the offline
fallback. The dev setup script must therefore pull ``ggml-small.en.bin``
unconditionally and fail loudly (``exit 1``) if it cannot, with no skip flag.

Hermetic: this reads the setup script as text and never executes it, touches the
network, or requires macOS.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "macos" / "setup.sh"

PULL_SRC = "hf:ggerganov/whisper.cpp:ggml-small.en.bin"
WINDOW = 15

# Tokens that would make the model download optional. None may appear.
SKIP_FLAGS = (
    "--skip-model", "--no-model", "--skip-whisper", "--skip-download",
    "--without-model", "skip_model", "no_model", "skip_whisper",
    "without_model", "download_model=0", "with_model=0",
)


class TestMacosSttModelMandatory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SETUP.read_text(encoding="utf-8")
        cls.lines = cls.script.splitlines()

    def _pull_index(self) -> int:
        for i, line in enumerate(self.lines):
            if "models pull" in line:
                return i
        self.fail("macos/setup.sh does not run `assistant models pull`")

    def _pull_block(self, window: int = WINDOW) -> str:
        idx = self._pull_index()
        return "\n".join(self.lines[idx:idx + window])

    def test_setup_pulls_the_whisper_model(self) -> None:
        self.assertIn("models pull", self.script)
        self.assertIn(PULL_SRC, self.script)

    def test_pull_is_mandatory_and_fails_loudly(self) -> None:
        block = self._pull_block()
        self.assertIn("exit 1", block)
        self.assertIn("mandatory", block.lower())
        # The download must be checked, not best-effort.
        pull_line = self.lines[self._pull_index()]
        self.assertIn("if !", pull_line)
        self.assertNotIn("|| true", block)
        self.assertNotIn("|| exit 0", block)

    def test_model_step_is_not_gated_by_a_skip_flag(self) -> None:
        lowered = self.script.lower()
        for flag in SKIP_FLAGS:
            self.assertNotIn(flag, lowered)

    def test_model_step_runs_even_without_launchd_agents(self) -> None:
        # Placed before the WITH_AGENT block, so `--no-agent` still provisions it.
        pull_idx = self._pull_index()
        gate_idx = next(
            (i for i, line in enumerate(self.lines)
             if line.startswith('if [[ "$WITH_AGENT" == "1"')),
            -1,
        )
        self.assertGreaterEqual(gate_idx, 0, "could not find the launchd-agent gate")
        self.assertLess(pull_idx, gate_idx)


if __name__ == "__main__":
    unittest.main()
