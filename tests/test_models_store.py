"""The model store must live outside the install tree.

The web installer removes ``$PREFIX/share/utter`` on uninstall; with the default
prefix that is ``$XDG_DATA_HOME/utter``, so a store at ``.../utter/models`` would
be deleted with the core tree. This pins the decoupled path, the one-time legacy
migration, and the no-data-loss fallback.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import util  # noqa: E402


class ModelsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-models-test-"))
        self._saved = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "UTTER_MODELS")}
        os.environ["XDG_DATA_HOME"] = str(self.tmp)
        os.environ.pop("UTTER_MODELS", None)
        util._LEGACY_MIGRATION.clear()

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_legacy(self) -> pathlib.Path:
        legacy = self.tmp / "utter" / "models"
        blob = legacy / "blobs" / "sha256-abc"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"weights")
        manifest = legacy / "manifests" / "huggingface.co" / "org" / "name" / "latest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({
            "name": "name", "tag": "latest",
            "files": [{"path": str(blob), "bytes": 7}],
        }))
        return legacy

    def test_default_store_is_outside_the_install_tree(self):
        # Default prefix ~/.local => the install tree is $XDG_DATA_HOME/utter.
        install_tree = util.xdg_data_home() / "utter"
        root = util.models_root()
        self.assertEqual(root, util.xdg_data_home() / "utter-models")
        self.assertFalse(str(root).startswith(str(install_tree) + os.sep))
        self.assertNotEqual(root, install_tree / "models")

    def test_override_wins_and_does_not_migrate(self):
        self._write_legacy()
        os.environ["UTTER_MODELS"] = str(self.tmp / "elsewhere")
        self.assertEqual(util.models_root(), self.tmp / "elsewhere")
        self.assertTrue((self.tmp / "utter" / "models").is_dir())

    def test_legacy_store_is_moved_once_and_manifests_rewritten(self):
        legacy = self._write_legacy()
        root = util.models_root()
        new_root = self.tmp / "utter-models"
        self.assertEqual(root, new_root)
        self.assertFalse(legacy.exists())
        self.assertTrue((new_root / "blobs" / "sha256-abc").is_file())
        manifest = json.loads(
            (new_root / "manifests" / "huggingface.co" / "org" / "name" / "latest.json")
            .read_text(encoding="utf-8"))
        self.assertTrue(manifest["files"][0]["path"].startswith(str(new_root)))
        self.assertEqual(util.models_status()["migrated_from"], str(legacy))
        # A second call is a no-op: the canonical store now has content.
        self.assertEqual(util.models_root(), new_root)

    def test_failed_move_keeps_legacy_models(self):
        legacy = self._write_legacy()
        with mock.patch.object(util.shutil, "move", side_effect=OSError("cross-device")):
            root = util.models_root()
            status = util.models_status()
        self.assertEqual(root, legacy)
        self.assertTrue((legacy / "blobs" / "sha256-abc").is_file())
        self.assertEqual(status["fallback_to"], str(legacy))

    def test_status_reports_both_locations(self):
        status = util.models_status()
        self.assertEqual(status["root"], str(self.tmp / "utter-models"))
        self.assertEqual(status["legacy_root"], str(self.tmp / "utter" / "models"))
        self.assertFalse(status["legacy_present"])


if __name__ == "__main__":
    unittest.main()
