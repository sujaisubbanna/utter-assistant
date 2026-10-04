#!/usr/bin/env python3
"""Tests for ``plugins/example_quicknote`` (the demonstration action plugin).

Drives the plugin over stdin/stdout with the *independent* conformance client
(``tests/conformance/framing_client.py``) — the same client the conformance
suite uses, deliberately not the runner's framing code. ``XDG_DATA_HOME`` is
pointed at a temp dir so the test never writes to the real inbox.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "tests" / "conformance"))

from framing_client import (  # noqa: E402
    FramingClient,
    RpcError,
    handshake_stdio,
)

PLUGIN = REPO / "plugins" / "example_quicknote" / "plugin.py"
MANIFEST = REPO / "plugins" / "example_quicknote" / "utter-plugin.toml"
OP = "action.quicknote.append"
MAX_TEXT = 2000


class QuicknotePluginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="quicknote-test-")
        self.old_xdg = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.tmp.name
        info = handshake_stdio([sys.executable, str(PLUGIN)])
        self.client: FramingClient = info["client"]
        self.hello = info["hello"]
        self.describe = info["describe"]
        self.health = info["health"]

    def tearDown(self) -> None:
        client = getattr(self, "client", None)
        if client is not None:
            proc = getattr(client, "proc", None)
            client.close()
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001 - best effort cleanup
                    proc.kill()
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except OSError:
                            pass
        if self.old_xdg is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self.old_xdg
        self.tmp.cleanup()

    # -- handshake --------------------------------------------------------- #
    def test_handshake(self) -> None:
        self.assertEqual(self.hello["protocol"], "1.0")
        self.assertEqual(self.hello["abi"], 1)
        self.assertEqual(self.hello["plugin"]["name"], "example_quicknote")
        self.assertEqual(self.hello["plugin"]["kind"], "action")
        self.assertIn("action.quicknote@1", self.hello["provides"])
        self.assertIn("experimental/example_quicknote@1", self.hello["provides"])
        self.assertEqual(self.hello["requires"], [])
        self.assertEqual(self.health["status"], "ok")
        self.assertIn("action.capabilities", self.describe["methods"])
        self.assertIn("action.invoke", self.describe["methods"])

    # -- capabilities ------------------------------------------------------ #
    def test_capabilities_advertises_one_op(self) -> None:
        caps = self.client.request("action.capabilities", {})
        ops = {o["op"]: o for o in caps["ops"]}
        self.assertIn(OP, ops)
        op = ops[OP]
        self.assertEqual(op["side_effect"], "local_write")
        self.assertFalse(op["needs_confirm"])
        self.assertEqual(op["args"]["required"], ["text"])
        self.assertIn("text", op["args"]["properties"])

    # -- invoke ------------------------------------------------------------ #
    def test_invoke_appends_line_to_temp_inbox(self) -> None:
        result = self.client.request("action.invoke", {"op": OP, "args": {"text": "buy milk"}})
        self.assertTrue(result["ok"])
        line_re = r"^- \[(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}\] buy milk$"
        self.assertRegex(result["line"], line_re)
        captured_date = re.match(line_re, result["line"]).group(1)
        # The inbox must live under the temp XDG_DATA_HOME, never the real home.
        self.assertTrue(result["path"].startswith(self.tmp.name + os.sep), result["path"])
        self.assertIn(os.path.join("utter", "quicknote"), result["path"])
        self.assertTrue(result["path"].endswith(f"{captured_date[:7]}.md"))
        content = Path(result["path"]).read_text(encoding="utf-8")
        self.assertEqual(content, result["line"] + "\n")

    def test_invoke_appends_second_line(self) -> None:
        self.client.request("action.invoke", {"op": OP, "args": {"text": "first"}})
        second = self.client.request("action.invoke", {"op": OP, "args": {"text": "second"}})
        lines = Path(second["path"]).read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[-1].endswith("second"))
        self.assertTrue(lines[-2].endswith("first"))

    def test_newlines_collapsed_to_one_line(self) -> None:
        result = self.client.request("action.invoke", {"op": OP, "args": {"text": "a\nb\r\nc"}})
        self.assertNotIn("\n", result["line"])
        self.assertTrue(result["line"].endswith("a b c"))

    # -- validation -------------------------------------------------------- #
    def test_empty_text_rejected(self) -> None:
        with self.assertRaises(RpcError) as ctx:
            self.client.request("action.invoke", {"op": OP, "args": {"text": "   "}})
        self.assertEqual(ctx.exception.code, -32602)

    def test_missing_text_rejected(self) -> None:
        with self.assertRaises(RpcError) as ctx:
            self.client.request("action.invoke", {"op": OP, "args": {}})
        self.assertEqual(ctx.exception.code, -32602)

    def test_oversized_text_rejected(self) -> None:
        with self.assertRaises(RpcError) as ctx:
            self.client.request("action.invoke", {"op": OP, "args": {"text": "x" * (MAX_TEXT + 1)}})
        self.assertEqual(ctx.exception.code, -32602)

    def test_unknown_op_rejected(self) -> None:
        with self.assertRaises(RpcError) as ctx:
            self.client.request("action.invoke", {"op": "action.nope", "args": {}})
        self.assertEqual(ctx.exception.code, -32602)


class QuicknoteManifestTest(unittest.TestCase):
    """Hand-validate the manifest against protocol/plugin.schema.json."""

    KINDS = {"stt", "router", "knowledge", "llm", "perceive", "action",
             "input", "tts", "context", "ui", "bundle"}
    CAP = re.compile(
        r"^([a-z0-9._-]+(/[A-Za-z0-9._-]+)?@\d+|experimental/[A-Za-z0-9._-]+@\d+)$"
    )

    def test_manifest(self) -> None:
        with open(MANIFEST, "rb") as fh:
            m = tomllib.load(fh)
        for key in ("name", "version", "kind", "protocol", "abi", "runtime",
                    "transport", "entrypoint"):
            self.assertIn(key, m, f"manifest missing required field {key!r}")
        self.assertRegex(m["name"], r"^[a-z0-9][a-z0-9._-]{1,63}$")
        self.assertRegex(m["version"], r"^\d+\.\d+\.\d+")
        self.assertIn(m["kind"], self.KINDS)
        self.assertRegex(m["protocol"], r"^\d+\.\d+$")
        self.assertGreaterEqual(m["abi"], 1)
        self.assertIn(m["runtime"], {"subprocess", "wasm", "native"})
        self.assertIn(m["transport"], {"stdio", "connect", "listen"})
        self.assertTrue(m["entrypoint"])
        self.assertIn("action.quicknote@1", m.get("provides", []))
        for cap in list(m.get("provides", [])) + list(m.get("requires", [])):
            self.assertRegex(cap, self.CAP, f"bad capability {cap!r}")


if __name__ == "__main__":
    unittest.main()
