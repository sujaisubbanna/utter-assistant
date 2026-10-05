#!/usr/bin/env python3
"""Guard: install/utter-runner.service renders cleanly and M3 runs on python3.

* ``install/install.sh`` substitutes ``@REPO@`` with ``sed``; no placeholder may
  survive into the installed unit.
* ``config.m3.toml``'s plugin entrypoint must invoke ``python3`` (the runner
  prepends the interpreter dir to PATH; a bare ``python`` may not exist).
* the agent venv must be built ``--system-site-packages`` from a gi-capable
  interpreter so distro Atspi/context detection works on remote installs
  (a11y silently degrades otherwise).
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "install" / "utter-runner.service"
CONFIG_M3 = ROOT / "config.m3.toml"
CONFIG_RUNNER = ROOT / "config.runner.toml"
WRAPPER = ROOT / "scripts" / "utter-wayland-ready.sh"
PLIST = ROOT / "macos" / "com.utter.runner.plist"
INSTALL = ROOT / "install.sh"


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

    def test_runner_unit_enables_real_actions(self):
        src = UNIT.read_text(encoding="utf-8")
        self.assertIn("Environment=UTTER_DRY_RUN=0", src,
                      "the production unit must turn the plugin dry-run off")

    def test_macos_plist_enables_real_actions(self):
        src = PLIST.read_text(encoding="utf-8")
        self.assertIn("<key>UTTER_DRY_RUN</key>", src)
        self.assertIn("<string>0</string>", src)
        self.assertIn("@REPO@/config.runner.toml", src)
        self.assertNotIn("config.m3.toml", src)

    def test_production_config_exists_and_is_safe(self):
        self.assertTrue(CONFIG_RUNNER.is_file(), "config.runner.toml is missing")
        data = tomllib.loads(CONFIG_RUNNER.read_text(encoding="utf-8"))
        plugins = data.get("plugin", [])
        self.assertTrue(plugins, "config.runner.toml has no [[plugin]] entries")
        matches = [p for p in plugins if p.get("id") == "utter"]
        self.assertTrue(matches, "config.runner.toml does not enable the utter plugin")
        utter = matches[0]
        self.assertTrue(utter.get("enabled", True), "the utter plugin must be enabled")
        # No machine-specific entrypoint: mirror what fix_plugin_python rewrites.
        entrypoint = utter.get("entrypoint", [])
        self.assertEqual(entrypoint, ["python3", "-m", "plugin"], entrypoint)
        # Dangerous ops stay off (TRUST.md §4).
        enabled = (data.get("policy", {}) or {}).get("enabled_ops", []) or []
        self.assertNotIn("action.terminal", enabled)
        self.assertNotIn("action.input", enabled)

    def test_wrapper_prefers_production_config(self):
        src = WRAPPER.read_text(encoding="utf-8")
        runner = src.index('elif [[ -f "$REPO/config.runner.toml" ]]')
        m3 = src.index('elif [[ -f "$REPO/config.m3.toml" ]]')
        self.assertLess(runner, m3,
                        "config.runner.toml must resolve before config.m3.toml")
        # $UTTER_CONFIG stays highest, so tests can still select config.m3.toml.
        self.assertLess(src.index("UTTER_CONFIG"), runner)
        self.assertTrue(CONFIG_M3.is_file())

    def test_agent_venv_uses_system_site_packages(self):
        script = INSTALL.read_text(encoding="utf-8")
        self.assertIn("--system-site-packages", script,
                      "agent venv must see distro gi/Atspi")
        # An isolated venv must be recreated, not left broken.
        self.assertIn("venv_is_isolated", script)
        self.assertIn("--clear", script)
        # gi-capable interpreter selection prefers the distro python.
        self.assertIn("/usr/bin/python3", script)
        self.assertIn("py_has_gi", script)


    def test_release_lookup_survives_api_rate_limit(self):
        script = INSTALL.read_text(encoding="utf-8")
        self.assertIn("_latest_tag()", script)
        self.assertIn("GITHUB_TOKEN", script)
        self.assertIn("/releases/latest", script)
        self.assertIn("/releases/tag/", script)
        # Both resolve paths use the shared helper, not a direct API call.
        self.assertNotIn('curl -fsSL "$api" | sed', script)

    def test_latest_tag_falls_back_to_redirect(self):
        script = INSTALL.read_text(encoding="utf-8")
        match = re.search(r"^_latest_tag\(\) \{.*?^\}", script, re.S | re.M)
        assert match is not None, "_latest_tag not found in install.sh"
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            bindir.mkdir()
            fake = bindir / "curl"
            fake.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                "  *api.github.com*) exit 22 ;;\n"
                "  *) printf 'HTTP/2 302\\r\\nlocation: "
                "https://github.com/o/r/releases/tag/v9.9.9\\r\\n\\r\\n' ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            runner = Path(d) / "run.sh"
            runner.write_text(match.group(0) + "\n_latest_tag\n", encoding="utf-8")
            env = dict(os.environ)
            env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
            env["UTTER_REPO"] = "o/r"
            env.pop("GITHUB_TOKEN", None)
            env.pop("GH_TOKEN", None)
            out = subprocess.run(["bash", str(runner)], capture_output=True,
                                 text=True, env=env)
            self.assertEqual(out.stdout.strip(), "v9.9.9", out.stderr)


    def test_installer_restarts_units_on_upgrade(self):
        # `enable --now` leaves an already-running unit on the old core, so an
        # upgrade must restart the units for the new wrapper/config to apply.
        root = INSTALL.read_text(encoding="utf-8")
        minimal = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl --user restart", root)
        self.assertIn("systemctl --user restart", minimal)
        self.assertNotIn('enable --now "${names[@]}"', root)
        self.assertNotIn("enable --now utter-runner.service utter.service", minimal)


if __name__ == "__main__":
    unittest.main()
