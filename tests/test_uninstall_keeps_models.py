"""Uninstall must not delete the model store unless --purge is given.

``install/uninstall.sh`` records ``$XDG_DATA_HOME/utter-models`` and only removes
it with ``--purge``; ``--purge`` must announce the removal. The core install
tree is gone either way, so models surviving proves the decoupling.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNINSTALL = ROOT / "install" / "uninstall.sh"


class UninstallKeepsModelsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-uninstall-test-"))
        self.env = dict(os.environ)
        self.env["HOME"] = str(self.tmp)
        self.env["XDG_DATA_HOME"] = str(self.tmp / "data")
        self.env["XDG_CONFIG_HOME"] = str(self.tmp / "config")
        self.env["XDG_STATE_HOME"] = str(self.tmp / "state")
        self.env.pop("UTTER_MODELS", None)
        self.models = self.tmp / "data" / "utter-models"
        blob = self.models / "blobs" / "sha256-abc"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"weights")
        # A stub systemctl so a real (--yes) run never touches the host.
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        fake = self.bin / "systemctl"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(UNINSTALL), *args],
            cwd=str(ROOT), env=self.env, capture_output=True, text=True, timeout=60,
        )

    def test_apply_uninstall_keeps_models(self):
        out = self._run("--yes")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.models / "blobs" / "sha256-abc").is_file(),
                        "models were deleted by a default uninstall")

    def test_dry_run_never_removes_models(self):
        out = self._run("--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn(f"rm -rf {self.models}", out.stdout)

    def test_purge_announces_models_removal(self):
        out = self._run("--purge", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"rm -rf {self.models}", out.stdout)


if __name__ == "__main__":
    unittest.main()
