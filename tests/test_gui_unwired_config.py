#!/usr/bin/env python3
"""Regression tests for settings that were previously written but never read.

Each check pins one "documented but unwired" key to the code that now reads it:
  * [actions] confirm_enabled          -> plugins/utter_py/plugin.py
  * [router] decision_head_enabled     -> utter/router/decide.py + runtime.resolve_router
  * [perception] accessibility_enabled -> utter/executor.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from utter.config import Config, load_config  # noqa: E402
from utter.executor import Executor  # noqa: E402
from utter.router import decide as decide_mod  # noqa: E402
from utter.runtime import resolve_router  # noqa: E402

PLUGIN_PY = REPO / "plugins" / "utter_py" / "plugin.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("utter_py_plugin_unwired", PLUGIN_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigDefaultsTests(unittest.TestCase):
    def test_new_fields_have_safe_defaults(self):
        cfg = Config()
        self.assertTrue(cfg.actions.confirm_enabled)
        self.assertTrue(cfg.router.decision_head_enabled)
        self.assertTrue(cfg.perception.accessibility_enabled)

    def test_load_config_merges_the_new_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "[actions]\nconfirm_enabled = false\n"
                "[router]\ndecision_head_enabled = false\n"
                "[perception]\naccessibility_enabled = false\n",
                encoding="utf-8",
            )
            cfg = load_config(path)
        self.assertFalse(cfg.actions.confirm_enabled)
        self.assertFalse(cfg.router.decision_head_enabled)
        self.assertFalse(cfg.perception.accessibility_enabled)


class DecisionHeadTests(unittest.TestCase):
    def test_disabled_head_abstains_before_touching_the_network(self):
        cfg = Config()
        cfg.router.decision_head_enabled = False
        # A bogus ctx/profiles is fine: the gate returns before they are used.
        self.assertIsNone(decide_mod.decide("open firefox", None, {}, cfg))

    def test_resolve_router_preserves_the_switch_on_macos(self):
        cfg = Config()
        cfg.router.decision_head_enabled = False
        resolved = resolve_router(cfg, platform_name="macos")
        self.assertFalse(resolved.decision_head_enabled)


class ConfirmEnabledTests(unittest.TestCase):
    def setUp(self):
        self.plugin = _load_plugin_module()
        self._saved = self.plugin._CFG

    def tearDown(self):
        self.plugin._CFG = self._saved

    def test_master_switch_gates_the_discretionary_list(self):
        cfg = Config()
        cfg.actions.confirm_enabled = True
        self.plugin._CFG = cfg
        self.assertTrue(self.plugin._needs_confirm("key", {"text": "send now"}))
        cfg.actions.confirm_enabled = False
        self.assertFalse(self.plugin._needs_confirm("key", {"text": "send now"}))

    def test_consequential_ops_always_confirm(self):
        cfg = Config()
        cfg.actions.confirm_enabled = False
        self.plugin._CFG = cfg
        # The runner independently enforces these; the plugin must not downgrade.
        self.assertTrue(self.plugin._needs_confirm("terminal", {}))


class AccessibilityGateTests(unittest.TestCase):
    def test_disabled_accessibility_skips_the_a11y_tier(self):
        cfg = Config()
        cfg.perception.accessibility_enabled = False
        executor = Executor(lambda **_: None, cfg)
        self.assertIsNone(executor._try_a11y_click("Send"))


if __name__ == "__main__":
    unittest.main()
