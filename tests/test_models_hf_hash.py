#!/usr/bin/env python3
"""``hf:`` pulls must verify against the file's true content sha256.

Regression: ``assistant models pull hf:...`` downloaded the whole file, then
rejected it with a sha256 mismatch, because ``head()`` followed HF's ``/resolve``
302 to the CDN and read the CDN's Xet ``ETag`` as if it were the content sha256.
huggingface.co sends the real hash in ``X-Linked-ETag`` (with the real length in
``X-Linked-Size``) on the 302 itself; the CDN sends neither.

This test fakes that two-hop shape locally so it is deterministic and offline.
It fails on the old code (which returned the Xet hash) and passes on the fix.

    .venv-agent/bin/python tests/test_models_hf_hash.py
"""
from __future__ import annotations

import hashlib
import http.server
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from assistant import models, util  # noqa: E402

# HF's Xet dedup hash: what the CDN's ETag is, and what the old code pinned.
XET_HASH = "0d57184d34ae7d736e5bb2db5bf83debe730bd53dcefa235a0979b9dcfd33fb3"
BODY = b"utter-hf-xet-regression-body\n" * 64
TRUE_SHA = hashlib.sha256(BODY).hexdigest()
CDN_PATH = "/cdn/object"


class _HfFake(http.server.BaseHTTPRequestHandler):
    """``/resolve/*`` redirects like HF; the CDN target carries only the Xet ETag."""

    def log_message(self, format, *args):  # noqa: A002 - match the base signature
        pass

    def _send(self, code, headers, body=b""):
        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_HEAD(self):
        self._dispatch(head=True)

    def do_GET(self):
        self._dispatch(head=False)

    def _dispatch(self, head: bool):
        if self.path.startswith("/resolve/"):
            self._send(302, {
                "Location": CDN_PATH,
                "X-Linked-ETag": f'"{TRUE_SHA}"',
                "X-Linked-Size": str(len(BODY)),
                "ETag": f'"{XET_HASH}"',
                "Content-Length": "0",
            })
            return
        if self.path.split("?")[0] != CDN_PATH:
            self._send(404, {"Content-Length": "0"})
            return
        start = 0
        if head:
            self._send(200, {"ETag": f'"{XET_HASH}"',
                             "Content-Length": str(len(BODY))})
            return
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[len("bytes="):].split("-")[0] or 0)
        chunk = BODY[start:]
        headers = {
            "ETag": f'"{XET_HASH}"',
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(chunk)),
        }
        if start:
            headers["Content-Range"] = f"bytes {start}-{len(BODY) - 1}/{len(BODY)}"
            self._send(206, headers, chunk)
        else:
            self._send(200, headers, chunk)


class _Server:
    def __enter__(self):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HfFake)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class HfHashTests(unittest.TestCase):
    def test_head_prefers_x_linked_etag_over_cdn_etag(self):
        with _Server() as srv:
            size, sha, _etag = models.head(srv.url + "/resolve/main/model.bin")
        self.assertEqual(size, len(BODY))
        self.assertEqual(sha, TRUE_SHA)
        self.assertNotEqual(sha, XET_HASH, "must not pin the CDN's Xet hash")

    def test_pull_verifies_and_content_addresses_the_true_digest(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-hf-pull-"))
        saved = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "UTTER_MODELS")}
        os.environ["XDG_DATA_HOME"] = str(tmp)
        os.environ.pop("UTTER_MODELS", None)
        util._LEGACY_MIGRATION.clear()
        try:
            with _Server() as srv:
                result = models.pull(srv.url + "/resolve/main/model.bin", quiet=True)
            self.assertEqual(result["sha256"], TRUE_SHA)
            blob = pathlib.Path(result["path"])
            self.assertTrue(blob.is_file())
            self.assertEqual(blob.name, f"sha256-{TRUE_SHA}")
            self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), TRUE_SHA)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
