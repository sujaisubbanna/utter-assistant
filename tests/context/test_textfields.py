#!/usr/bin/env python3
"""Hermetic tests for the platform-neutral text-field detection probe.

Covers the predicate, ranking, cap, deadline, empty-result and
``detection_status()`` reasons, plus the Linux path against a synthetic AT-SPI
tree and the macOS path against a fake AX module. No real desktop, AT-SPI bus
or PyObjC/Accessibility is touched.

Usage::

    .venv-agent/bin/python tests/context/test_textfields.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utter.context import textfields  # noqa: E402
from utter.types import FocusedWindow, Rect, UIElement, WindowInfo  # noqa: E402


def el(role, *, name="", desc="", rect=(0, 0, 40, 20), states=(), path="", children=()):
    return UIElement(
        id=path or role,
        role=role,
        name=name,
        description=desc,
        rect=Rect(*rect) if rect is not None else None,
        states=list(states),
        app_id="",
        path=path or role,
        children=list(children),
    )


def focused(app_id="app", pid=11, window_id=7):
    return FocusedWindow(app_id=app_id, title="t", pid=pid, window_id=window_id)


class PredicateTest(unittest.TestCase):
    def test_text_roles_are_accepted(self):
        self.assertTrue(textfields.is_text_input("entry", ["editable", "enabled"]))
        self.assertTrue(textfields.is_text_input("text entry", ["editable"]))
        self.assertTrue(textfields.is_text_input("password text", ["editable"]))
        self.assertTrue(textfields.is_text_input("combo box", ["focusable"]))
        self.assertTrue(textfields.is_text_input("text", ["focusable"]))
        self.assertTrue(textfields.is_text_input("document text", ["focusable"]))

    def test_macos_roles_are_accepted(self):
        for role in ("AXTextField", "AXTextArea", "AXComboBox",
                     "AXSearchField", "AXSecureTextField"):
            self.assertTrue(textfields.is_text_input(role, ["editable"]), role)

    def test_non_text_roles_rejected(self):
        self.assertFalse(textfields.is_text_input("static text", ["visible"]))
        self.assertFalse(textfields.is_text_input("AXStaticText", []))
        self.assertFalse(textfields.is_text_input("push button", ["focusable"]))
        self.assertFalse(textfields.is_text_input("label", ["visible"]))
        self.assertFalse(textfields.is_text_input("", []))

    def test_blocked_states_rejected(self):
        for bad in ("disabled", "insensitive", "hidden", "invisible",
                    "defunct", "unavailable"):
            self.assertFalse(
                textfields.is_text_input("entry", ["editable", bad]), bad)

    def test_needs_editable_or_focusable(self):
        self.assertFalse(textfields.is_text_input("entry", ["enabled", "visible"]))
        self.assertFalse(textfields.is_text_input("entry", []))

    def test_role_and_state_casing_is_normalized(self):
        self.assertTrue(textfields.is_text_input("Entry", ["EDITABLE"]))
        self.assertTrue(textfields.is_text_input("text_entry", ["focusable"]))


class LinuxProbeTest(unittest.TestCase):
    def _patch(self, tree, *, other_tree=None, windows=(), atspi_ok=True,
               remaining=None):
        atspi = MagicMock()
        atspi._HAS_ATSPI = atspi_ok

        def dump(app_id=None, max_nodes=400, timeout_s=8.0):
            if app_id and other_tree is not None and app_id != "app":
                return other_tree
            return tree

        atspi.dump_tree.side_effect = dump
        patches = [
            patch.object(textfields, "_atspi", return_value=atspi),
            patch.object(textfields.platform, "is_macos", return_value=False),
            patch.object(textfields, "_focused_window_snapshot",
                         return_value=focused()),
            patch("utter.context.desktop.list_windows",
                  return_value=list(windows)),
        ]
        return atspi, patches

    # -- list_text_fields against a synthetic tree -------------------------

    def test_ranks_focused_then_other_and_maps_fields(self):
        tree = el("application", rect=None, path="app#", children=[
            el("entry", name="secondary", desc="lbl-2",
               states=["editable"], path="app#0.1"),
            el("entry", name="primary", desc="lbl-1",
               states=["editable", "focused"], path="app#0.0"),
        ])
        atspi, patches = self._patch(tree)
        with patches[0], patches[1], patches[2], patches[3]:
            out = textfields.list_text_fields()
        self.assertEqual([c.name for c in out], ["primary", "secondary"])
        first = out[0]
        self.assertTrue(first.focused)
        self.assertEqual(first.app_id, "app")
        self.assertEqual(first.pid, 11)
        self.assertEqual(first.window_id, 7)
        self.assertEqual(first.path, "app#0.0")
        self.assertEqual(first.label, "lbl-1")
        self.assertEqual(first.identity, ("app", 11, 7, "app#0.0"))

    def test_skips_hidden_zero_size_and_non_text(self):
        tree = el("application", rect=None, path="app#", children=[
            el("entry", name="hidden", states=["editable", "hidden"], path="app#0"),
            el("entry", name="zero", states=["editable"], rect=None, path="app#1"),
            el("entry", name="jsize", states=["editable"], rect=(0, 0, 0, 20), path="app#2"),
            el("static text", name="label", rect=(0, 0, 5, 5), path="app#3"),
            el("push button", name="ok", states=["focusable"], path="app#4"),
        ])
        atspi, patches = self._patch(tree)
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertEqual(textfields.list_text_fields(), [])

    def test_cap_is_respected(self):
        entries = [
            el("entry", name=f"e{i}", states=["editable"], path=f"app#{i}")
            for i in range(40)
        ]
        tree = el("application", rect=None, path="app#", children=entries)
        atspi, patches = self._patch(tree)
        with patches[0], patches[1], patches[2], patches[3]:
            out = textfields.list_text_fields()
        self.assertEqual(len(out), textfields.MAX_CANDIDATES)

    def test_other_windows_rank_after_and_focused_other_ranks_first(self):
        primary = el("application", rect=None, path="app#", children=[
            el("entry", name="mine", states=["editable"], path="app#0"),
        ])
        other = el("other", rect=None, path="other#", children=[
            el("entry", name="theirs", states=["editable"], path="other#0"),
        ])
        atspi, patches = self._patch(
            primary, other_tree=other,
            windows=[WindowInfo(id=2, app_id="other")])
        with patches[0], patches[1], patches[2], patches[3]:
            out = textfields.list_text_fields()
        self.assertEqual([c.name for c in out], ["mine", "theirs"])
        self.assertEqual(out[1].app_id, "other")

        # A focused field in a non-primary window still outranks the rest.
        other_focused = el("other", rect=None, path="other#", children=[
            el("entry", name="theirs", states=["editable", "focused"], path="other#0"),
        ])
        atspi2, patches2 = self._patch(
            primary, other_tree=other_focused,
            windows=[WindowInfo(id=2, app_id="other")])
        with patches2[0], patches2[1], patches2[2], patches2[3]:
            out2 = textfields.list_text_fields()
        self.assertEqual(out2[0].name, "theirs")

    def test_deadline_stops_further_dumps(self):
        primary = el("application", rect=None, path="app#", children=[
            el("entry", name="mine", states=["editable"], path="app#0"),
        ])
        atspi, patches = self._patch(
            primary, other_tree=primary,
            windows=[WindowInfo(id=2, app_id="other")])
        with patches[0], patches[1], patches[2], patches[3], \
                patch.object(textfields, "_remaining", return_value=0.0):
            textfields.list_text_fields(include_windows=True)
        self.assertEqual(atspi.dump_tree.call_count, 1)

    def test_dump_failure_never_raises(self):
        atspi = MagicMock()
        atspi._HAS_ATSPI = True
        atspi.dump_tree.side_effect = RuntimeError("bus died")
        with patch.object(textfields, "_atspi", return_value=atspi), \
                patch.object(textfields.platform, "is_macos", return_value=False):
            self.assertEqual(textfields.list_text_fields(), [])

    def test_focused_text_field(self):
        tree = el("application", rect=None, path="app#", children=[
            el("entry", name="plain", states=["editable"], path="app#0"),
            el("entry", name="focused", states=["editable", "focused"], path="app#1"),
        ])
        atspi, patches = self._patch(tree)
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertEqual(textfields.focused_text_field().name, "focused")

        no_focus = el("application", rect=None, path="app#", children=[
            el("entry", name="plain", states=["editable"], path="app#0"),
        ])
        atspi2, patches2 = self._patch(no_focus)
        with patches2[0], patches2[1], patches2[2], patches2[3]:
            self.assertIsNone(textfields.focused_text_field())


class DetectionStatusTest(unittest.TestCase):
    def test_atspi_unavailable(self):
        atspi = MagicMock()
        atspi._HAS_ATSPI = False
        with patch.object(textfields, "_atspi", return_value=atspi), \
                patch.object(textfields.platform, "is_macos", return_value=False):
            status = textfields.detection_status()
        self.assertEqual(status["reason"], "atspi-unavailable")
        self.assertFalse(status["available"])
        self.assertEqual(status["platform"], "linux")
        self.assertEqual(status["count"], 0)

    def test_no_a11y_tree(self):
        atspi = MagicMock()
        atspi._HAS_ATSPI = True
        atspi.dump_tree.return_value = None
        with patch.object(textfields, "_atspi", return_value=atspi), \
                patch.object(textfields.platform, "is_macos", return_value=False), \
                patch.object(textfields, "_focused_window_snapshot",
                             return_value=focused()):
            status = textfields.detection_status()
        self.assertEqual(status["reason"], "no-a11y-tree")
        self.assertTrue(status["available"])

    def test_tree_without_fields(self):
        tree = el("application", rect=None, path="app#", children=[
            el("static text", name="x", path="app#0"),
        ])
        atspi = MagicMock()
        atspi._HAS_ATSPI = True
        atspi.dump_tree.return_value = tree
        with patch.object(textfields, "_atspi", return_value=atspi), \
                patch.object(textfields.platform, "is_macos", return_value=False), \
                patch.object(textfields, "_focused_window_snapshot",
                             return_value=focused()), \
                patch("utter.context.desktop.list_windows", return_value=[]):
            status = textfields.detection_status()
        self.assertEqual(status["reason"], "no-text-fields")
        self.assertEqual(status["count"], 0)

    def test_ok(self):
        tree = el("application", rect=None, path="app#", children=[
            el("entry", name="e", states=["editable"], path="app#0"),
        ])
        atspi = MagicMock()
        atspi._HAS_ATSPI = True
        atspi.dump_tree.return_value = tree
        with patch.object(textfields, "_atspi", return_value=atspi), \
                patch.object(textfields.platform, "is_macos", return_value=False), \
                patch.object(textfields, "_focused_window_snapshot",
                             return_value=focused()), \
                patch("utter.context.desktop.list_windows", return_value=[]):
            status = textfields.detection_status()
        self.assertEqual(status["reason"], "ok")
        self.assertEqual(status["count"], 1)


class MacosProbeTest(unittest.TestCase):
    def _fake(self, *, available=(True, ""), tree=None, trees=None,
              electron=False, enable=True, front_pid=99):
        fake = MagicMock()
        fake.available.return_value = available
        fake.front_pid.return_value = front_pid
        fake.is_electron.return_value = electron
        fake.enable_manual_accessibility.return_value = enable
        if trees is not None:
            fake.dump_focused_tree.side_effect = trees
        else:
            fake.dump_focused_tree.return_value = tree
        return fake

    def _run(self, fake, *, method="list"):
        with patch.object(textfields, "_axtree", return_value=fake), \
                patch.object(textfields.platform, "is_macos", return_value=True), \
                patch.object(textfields, "_focused_window_snapshot",
                             return_value=focused("com.app", 99, 3)):
            if method == "status":
                return textfields.detection_status()
            if method == "focused":
                return textfields.focused_text_field()
            return textfields.list_text_fields()

    def test_ax_unavailable(self):
        fake = self._fake(available=(False, "ax-unavailable"))
        status = self._run(fake, method="status")
        self.assertEqual(status["reason"], "ax-unavailable")
        self.assertEqual(status["platform"], "darwin")
        self.assertFalse(status["available"])

    def test_permission_denied(self):
        fake = self._fake(available=(False, "permission-denied"))
        status = self._run(fake, method="status")
        self.assertEqual(status["reason"], "permission-denied")
        self.assertFalse(status["available"])

    def test_detects_ax_text_field_excludes_static_text(self):
        tree = el("AXWindow", rect=None, path="com.app#", children=[
            el("AXStaticText", name="label", rect=(0, 0, 30, 10), path="com.app#0"),
            el("AXTextField", name="name", desc="Name",
               states=["editable", "focusable"], path="com.app#1"),
        ])
        fake = self._fake(tree=tree)
        out = self._run(fake)
        self.assertEqual([c.role for c in out], ["AXTextField"])
        self.assertEqual(out[0].label, "Name")

    def test_focused_text_field_macos(self):
        tree = el("AXWindow", rect=None, path="com.app#", children=[
            el("AXTextArea", name="body",
               states=["editable", "focusable", "focused"], path="com.app#0"),
        ])
        fake = self._fake(tree=tree)
        self.assertEqual(self._run(fake, method="focused").name, "body")

    def test_electron_enables_flag_once_then_finds_field(self):
        empty = el("AXWindow", rect=None, path="com.app#", children=[])
        found = el("AXWindow", rect=None, path="com.app#", children=[
            el("AXTextField", name="editor",
               states=["editable", "focusable"], path="com.app#0"),
        ])
        fake = self._fake(electron=True, enable=True, trees=[empty, found])
        out = self._run(fake)
        self.assertEqual([c.name for c in out], ["editor"])
        fake.enable_manual_accessibility.assert_called_once()

    def test_electron_flag_refused_reports_reason(self):
        empty = el("AXWindow", rect=None, path="com.app#", children=[])
        fake = self._fake(electron=True, enable=False, tree=empty)
        status = self._run(fake, method="status")
        self.assertEqual(status["reason"], "electron-ax-disabled")
        self.assertTrue(status["available"])

    def test_no_ax_tree(self):
        fake = self._fake(tree=None, front_pid=0)
        status = self._run(fake, method="status")
        self.assertEqual(status["reason"], "no-ax-tree")


if __name__ == "__main__":
    unittest.main(verbosity=2)
