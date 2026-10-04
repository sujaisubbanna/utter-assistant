#!/usr/bin/env python3
"""STT must find a whisper.cpp model pulled into the ``assistant`` model store.

The store keeps content-addressed blobs (``blobs/sha256-<hex>``) and records the
original filename in a manifest, so the loader cannot find a pulled model by
filename alone. Hermetic: a temp store + manifest, no model is loaded and no
audio is decoded.

    .venv-agent/bin/python tests/voice/test_stt_store.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.voice import stt


def _write_store(root: Path, *, name: str, filename: str, payload: bytes = b"ggml") -> Path:
    blob = root / "blobs" / "sha256-deadbeef"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(payload)
    manifest = root / "manifests" / "huggingface.co" / "ggerganov" / "whisper.cpp" / "latest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "name": name,
        "tag": "latest",
        "files": [{"name": filename, "path": str(blob), "bytes": len(payload)}],
    }), encoding="utf-8")
    return blob


class TestStoreCandidates(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="utter-stt-store-"))
        self._saved = {k: os.environ.get(k) for k in
                       ("UTTER_MODELS", "UTTER_MODELS_DIR", "UTTER_WHISPER_MODEL")}
        for key in self._saved:
            os.environ.pop(key, None)
        os.environ["UTTER_MODELS"] = str(self.tmp)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_store_blob_is_a_candidate(self):
        blob = _write_store(self.tmp, name="whisper.cpp", filename="ggml-small.en.bin")
        paths = [Path(p) for p in stt._candidate_model_paths("ggml-small.en.bin")]
        self.assertIn(blob, paths)
        # The blob path is the concrete file the loader will hand to pywhispercpp.
        self.assertTrue(blob.is_file())

    def test_friendly_model_name_resolves_to_store_blob(self):
        # `[stt] model = "small.en"` texts the same blob without the ggml filename.
        blob = _write_store(self.tmp, name="whisper.cpp", filename="ggml-small.en.bin")
        paths = [Path(p) for p in stt._candidate_model_paths("small.en")]
        self.assertIn(blob, paths)

    def test_resolver_uses_the_store_blob(self):
        blob = _write_store(self.tmp, name="whisper.cpp", filename="ggml-small.en.bin")
        cfg = type("Cfg", (), {"backend": "whisper_cpp", "model": "ggml-small.en.bin"})()
        t = stt.Transcriber(cfg)
        self.assertEqual(t._resolve_whispercpp_model(), str(blob))

    def test_existing_dir_override_still_wins_over_the_store(self):
        _write_store(self.tmp, name="whisper.cpp", filename="ggml-small.en.bin")
        d = self.tmp / "explicit"
        d.mkdir()
        local = d / "ggml-small.en.bin"
        local.write_bytes(b"local")
        os.environ["UTTER_MODELS_DIR"] = str(d)
        paths = [Path(p) for p in stt._candidate_model_paths("ggml-small.en.bin")]
        # The explicit override is searched before the content-addressed blob.
        self.assertLess(paths.index(local), paths.index(self.tmp / "blobs" / "sha256-deadbeef"))

    def test_assistant_import_failure_falls_back_to_xdg(self):
        with patch.dict(os.environ, {"UTTER_MODELS": ""}):
            os.environ.pop("UTTER_MODELS", None)
            xdg = self.tmp / "data"
            os.environ["XDG_DATA_HOME"] = str(xdg)
            self.assertEqual(stt._store_root(), xdg / "utter-models")


if __name__ == "__main__":
    unittest.main()
