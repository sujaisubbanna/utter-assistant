#!/usr/bin/env python3
"""Dictation pending record + ``assistant dictation`` target picker (hermetic).

Covers the post-hoc dictation path added on top of the daemon fallback:

* the pending record at ``$XDG_RUNTIME_DIR/utter/dictation-pending.json``
  (write/read/clear, empty shape when absent),
* ``assistant dictation --pending --json`` / ``--dismiss``,
* target-spec resolution (``<window-id>`` | ``pid:<n>`` | ``app_id:<s>``) and
  re-delivery through the extracted typing helper.

Everything runs offline: the window list and text injection are stubbed, and
``XDG_RUNTIME_DIR`` points at a throwaway directory.

Usage::

    .venv-agent/bin/python tests/test_dictation_pending.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import __main__ as assistant_cli  # noqa: E402
from utter import dictation  # noqa: E402
from utter.types import Action, ActionResult, Tier, WindowInfo  # noqa: E402


def _windows() -> list[WindowInfo]:
    return [
        WindowInfo(id=7, app_id="org.kde.konsole", title="Terminal", pid=4321),
        WindowInfo(id=9, app_id="firefox", title="Docs", pid=5555, is_focused=True),
        WindowInfo(id=11, app_id="firefox", title="Other", pid=5556),
    ]


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = assistant_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class PendingRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {"XDG_RUNTIME_DIR": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_path_lives_under_the_runtime_dir(self):
        self.assertEqual(dictation.pending_path(),
                         pathlib.Path(self._tmp.name) / "utter" / "dictation-pending.json")

    def test_read_absent_is_empty(self):
        self.assertEqual(dictation.read_pending(), {})

    def test_write_read_clear_round_trip(self):
        record = dictation.write_pending("hello world", "no dictation target", ts=123)
        self.assertEqual(record, {"text": "hello world", "reason": "no dictation target",
                                  "ts": 123})
        self.assertTrue(dictation.pending_path().is_file())
        self.assertEqual(dictation.read_pending(), record)
        self.assertTrue(dictation.clear_pending())
        self.assertEqual(dictation.read_pending(), {})
        self.assertFalse(dictation.pending_path().exists())

    def test_clear_when_absent_is_false(self):
        self.assertFalse(dictation.clear_pending())

    def test_malformed_record_reads_empty(self):
        path = dictation.pending_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(dictation.read_pending(), {})


class ResolveTargetTest(unittest.TestCase):
    def test_plain_window_id(self):
        target = dictation.resolve_target("7", windows=_windows())
        self.assertIsNotNone(target)
        self.assertEqual((target.window_id, target.pid, target.app_id),
                         (7, 4321, "org.kde.konsole"))

    def test_id_prefix(self):
        self.assertEqual(dictation.resolve_target("id:9", windows=_windows()).window_id, 9)

    def test_pid_spec(self):
        target = dictation.resolve_target("pid:5555", windows=_windows())
        self.assertEqual(target.window_id, 9)

    def test_app_id_prefers_focused(self):
        target = dictation.resolve_target("app_id:firefox", windows=_windows())
        self.assertEqual(target.window_id, 9)  # focused firefox, not the first

    def test_unknown_specs_are_none(self):
        for spec in ("", "42", "pid:9999", "app_id:missing", "pid:abc", "app_id:"):
            with self.subTest(spec=spec):
                self.assertIsNone(dictation.resolve_target(spec, windows=_windows()))


class DeliverToSpecTest(unittest.TestCase):
    def test_delivers_to_matched_window(self):
        typed: list = []

        def fake_type(text, target):
            typed.append((text, target.window_id))
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "typed")

        with patch("utter.context.desktop.list_windows", return_value=_windows()), \
             patch("utter.dictation._type_dictation", side_effect=fake_type):
            result = dictation.deliver_to_spec("pid:4321", "hello", cfg=None)
        self.assertTrue(result.ok)
        self.assertEqual(typed, [("hello", 7)])

    def test_unmatched_spec_fails_without_typing(self):
        with patch("utter.context.desktop.list_windows", return_value=_windows()), \
             patch("utter.dictation._type_dictation") as type_mock:
            result = dictation.deliver_to_spec("pid:9999", "hello", cfg=None)
        self.assertFalse(result.ok)
        self.assertIn("no window matched", result.detail)
        type_mock.assert_not_called()


class DictationCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {"XDG_RUNTIME_DIR": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pending_json_shape(self):
        dictation.write_pending("draft text", "type_text failed: nope", ts=99)
        code, raw, err = _run_cli(["dictation", "--pending", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(raw),
                         {"text": "draft text", "reason": "type_text failed: nope", "ts": 99})

    def test_pending_json_empty_when_absent(self):
        code, raw, _ = _run_cli(["dictation", "--pending", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(raw), {})

    def test_dismiss_clears_record(self):
        dictation.write_pending("draft", "no dictation target")
        code, raw, err = _run_cli(["dictation", "--dismiss", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(json.loads(raw)["ok"])
        self.assertEqual(dictation.read_pending(), {})

    def test_deliver_types_clears_and_reports(self):
        dictation.write_pending("draft text", "no dictation target")
        typed: list = []

        def fake_type(text, target):
            typed.append((text, target.window_id))
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "typed")

        with patch("utter.context.desktop.list_windows", return_value=_windows()), \
             patch("utter.dictation._type_dictation", side_effect=fake_type):
            code, raw, err = _run_cli(["dictation", "--deliver", "--text", "draft text",
                                       "--target", "9", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(raw), {"ok": True, "detail": "typed"})
        self.assertEqual(typed, [("draft text", 9)])
        self.assertEqual(dictation.read_pending(), {})

    def test_deliver_failure_keeps_record(self):
        dictation.write_pending("draft text", "no dictation target")
        with patch("utter.context.desktop.list_windows", return_value=_windows()):
            code, raw, err = _run_cli(["dictation", "--deliver", "--text", "draft text",
                                       "--target", "pid:9999", "--json"])
        self.assertEqual((code, err), (1, ""))
        self.assertFalse(json.loads(raw)["ok"])
        self.assertEqual(dictation.read_pending()["text"], "draft text")

    def test_deliver_without_text_and_target_is_usage_error(self):
        code, _raw, err = _run_cli(["dictation", "--deliver", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("requires --text and --target", err)

    def test_no_action_is_usage_error(self):
        code, _raw, err = _run_cli(["dictation", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("--pending", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
