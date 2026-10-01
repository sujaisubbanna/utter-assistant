#!/usr/bin/env python3
"""Guard: install/utter-runner.service renders cleanly and M3 runs on python3.

* ``install/install.sh`` substitutes ``@REPO@`` with ``sed``; no placeholder may
  survive into the installed unit.
* ``config.m3.toml``'s plugin entrypoint must invoke ``python3`` (the runner
  prepends the interpreter dir to PATH; a bare ``python`` may not exist).
"""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "install" / "utter-runner.service"
CONFIG_M3 = ROOT / "config.m3.toml"


class TestInstallerContract(unittest.TestCase):
    def test_unit_has_no_placeholder_after_sed(self):
        src = UNIT.read_text(encoding="utf-8")
        self.assertIn("@REPO@", src, "unit should template @REPO@ for install.sh")
        rendered = re.sub(r"@REPO@", "/opt/utter", src)
        self.assertNotIn("@REPO@", rendered)
        # Sanity: substitution actually reached the ExecStart path.
        self.assertIn("/opt/utter/scripts/utter-wayland-ready.sh", rendered)

    def test_m3_entrypoint_uses_python3(self):
        data = tomllib.loads(CONFIG_M3.read_text(encoding="utf-8"))
        plugins = data.get("plugin", [])
        self.assertTrue(plugins, "config.m3.toml has no [[plugin]] entries")
        interpreters = [p.get("entrypoint", [None])[0] for p in plugins]
        self.assertEqual(interpreters, ["python3"], interpreters)


if __name__ == "__main__":
    unittest.main()
