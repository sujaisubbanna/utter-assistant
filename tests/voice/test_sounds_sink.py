#!/usr/bin/env python3
"""UI sounds can target a specific output sink (hermetic).

On this machine the system default sink is Sunshine's virtual sink, so the
activation sound never reaches the user's speakers. ``_player`` must pass the
configured sink to the player (``pw-play --target`` / ``paplay --device``) and
keep the old, untargeted behaviour when no sink is set.

No player runs and no real device is touched: ``shutil.which`` is patched.

Usage::

    .venv-agent/bin/python tests/voice/test_sounds_sink.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter import sounds  # noqa: E402
from utter.config import load_config  # noqa: E402


def _which_only(*names: str):
    """A ``shutil.which`` stub reporting only ``names`` as installed."""
    def which(cmd, *args, **kwargs):
        return f"/usr/bin/{cmd}" if cmd in names else None
    return which


class TestPlayerSink(unittest.TestCase):
    def _player(self, tools: tuple[str, ...], env: dict):
        with patch.object(sounds.shutil, "which", _which_only(*tools)), \
                patch.dict(os.environ, env, clear=False):
            return sounds._player()

    def test_pw_play_targets_env_sink(self):
        player = self._player(("pw-play", "paplay"),
                              {"UTTER_SOUND_SINK": "my.sink"})
        self.assertIsNotNone(player)
        assert player is not None
        self.assertEqual(player[:3], ["pw-play", "--volume=0.35", "--target"])
        self.assertEqual(player[3], "my.sink")

    def test_pw_play_no_target_when_unset(self):
        player = self._player(("pw-play", "paplay"), {"UTTER_SOUND_SINK": ""})
        self.assertEqual(player, ["pw-play", "--volume=0.35"])

    def test_pw_play_no_target_when_env_missing(self):
        env = {k: v for k, v in os.environ.items() if k != "UTTER_SOUND_SINK"}
        with patch.object(sounds.shutil, "which", _which_only("pw-play")), \
                patch.dict(os.environ, env, clear=True):
            self.assertEqual(sounds._player(), ["pw-play", "--volume=0.35"])

    def test_paplay_uses_device(self):
        player = self._player(("paplay",), {"UTTER_SOUND_SINK": "my.sink"})
        self.assertEqual(player, ["paplay", "--volume=11500",
                                  "--device", "my.sink"])

    def test_paplay_no_device_when_unset(self):
        player = self._player(("paplay",), {"UTTER_SOUND_SINK": ""})
        self.assertEqual(player, ["paplay", "--volume=11500"])

    def test_explicit_argument_wins(self):
        with patch.object(sounds.shutil, "which", _which_only("pw-play")), \
                patch.dict(os.environ, {"UTTER_SOUND_SINK": "from.env"},
                           clear=False):
            player = sounds._player("from.arg")
        assert player is not None
        self.assertEqual(player[3], "from.arg")


class TestConfigSink(unittest.TestCase):
    def test_sounds_sink_parses(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text('[sounds]\nsink = "x"\n', encoding="utf-8")
            cfg = load_config(cfg_path)
        self.assertEqual(cfg.sounds.sink, "x")

    def test_sounds_sink_defaults_empty(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text("", encoding="utf-8")
            cfg = load_config(cfg_path)
        self.assertEqual(cfg.sounds.sink, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
