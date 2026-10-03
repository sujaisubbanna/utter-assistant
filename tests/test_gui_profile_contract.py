#!/usr/bin/env python3
"""GUI backend contract: the profile scripts carry the opt-in gate (R6/R7).

The GUI never parses YAML itself; it runs the Rust-embedded ``LIST_SCRIPT`` /
``SAVE_SCRIPT`` with the assistant's interpreter. These tests extract those
exact strings from ``profiles.rs`` and execute them, so the contract cannot
drift silently.

Run directly::

    .venv-agent/bin/python tests/test_gui_profile_contract.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILES_RS = ROOT / "gui-tauri" / "src-tauri" / "src" / "profiles.rs"

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _script(name: str) -> str:
    src = PROFILES_RS.read_text(encoding="utf-8")
    m = re.search(r'pub const ' + name + r': &str = r##"(.*?)"##;', src, re.S)
    assert m, f"{name} not found in profiles.rs"
    return m.group(1)


class GuiProfileContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-gui-contract-"))
        self.user = self.tmp / "config" / "utter" / "profiles"
        self.env = dict(os.environ)
        self.env.update({
            "PYTHONPATH": str(ROOT),
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_DATA_HOME": str(self.tmp / "data"),
            "XDG_STATE_HOME": str(self.tmp / "state"),
        })

    def _run(self, script: str, *args: str):
        return subprocess.run(
            [sys.executable, "-c", script, *args],
            cwd=str(ROOT), env=self.env, capture_output=True, text=True, timeout=60,
        )

    def test_list_script_includes_gate_fields(self):
        out = self._run(_script("LIST_SCRIPT"), str(self.user))
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout.strip())
        self.assertTrue(payload["profiles"], "loader returned no profiles")
        for entry in payload["profiles"]:
            self.assertIsInstance(entry.get("enabled"), bool, entry)
            self.assertIsInstance(entry.get("preselected"), bool, entry)
        by_id = {e["id"]: e for e in payload["profiles"]}
        self.assertTrue(by_id["firefox"]["enabled"])
        self.assertTrue(by_id["firefox"]["preselected"])

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_save_script_round_trips_enabled_false(self):
        out = self._run(_script("SAVE_SCRIPT"), str(self.user), "spotify",
                        json.dumps({"enabled": False}))
        self.assertEqual(out.returncode, 0, out.stderr)
        target = self.user / "spotify.yaml"
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        self.assertEqual(data["id"], "spotify")
        self.assertIs(data["enabled"], False)

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_save_script_carries_enabled_across_shortcut_edit(self):
        self._run(_script("SAVE_SCRIPT"), str(self.user), "spotify",
                  json.dumps({"enabled": False}))
        # A shortcut edit that omits enabled must not silently re-enable it.
        out = self._run(_script("SAVE_SCRIPT"), str(self.user), "spotify",
                        json.dumps({"shortcuts": {"next_track": "ctrl+Right"}}))
        self.assertEqual(out.returncode, 0, out.stderr)
        data = yaml.safe_load((self.user / "spotify.yaml").read_text(encoding="utf-8"))
        self.assertIs(data["enabled"], False)
        self.assertEqual(data["shortcuts"], {"next_track": "ctrl+Right"})

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_save_script_preserves_custom_commands(self):
        # Disabling (or editing) an app must keep its custom command phrases
        # inert but present so they resurface on re-enable (R7).
        self.user.mkdir(parents=True, exist_ok=True)
        (self.user / "spotify.yaml").write_text(
            "id: spotify\ncommands:\n  next track: ctrl+Right\n", encoding="utf-8")
        out = self._run(_script("SAVE_SCRIPT"), str(self.user), "spotify",
                        json.dumps({"enabled": False}))
        self.assertEqual(out.returncode, 0, out.stderr)
        data = yaml.safe_load((self.user / "spotify.yaml").read_text(encoding="utf-8"))
        self.assertIs(data["enabled"], False)
        self.assertEqual(data["commands"], {"next track": "ctrl+Right"})

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_set_enabled_script_bulk(self):
        out = self._run(_script("SET_ENABLED_SCRIPT"), str(self.user),
                        json.dumps(["spotify", "code"]), "false")
        self.assertEqual(out.returncode, 0, out.stderr)
        for pid in ("spotify", "code"):
            data = yaml.safe_load((self.user / f"{pid}.yaml").read_text(encoding="utf-8"))
            self.assertIs(data["enabled"], False)
            self.assertEqual(data["id"], pid)
        # Invalid id is rejected before writing anything.
        bad = self._run(_script("SET_ENABLED_SCRIPT"), str(self.user),
                        json.dumps(["../evil"]), "true")
        self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
