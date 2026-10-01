#!/usr/bin/env python3
"""macOS native background keyboard input (``CGEventPostToPid``).

Runs hermetically on Linux: the Quartz/ApplicationServices frameworks are
stubbed in ``sys.modules`` and ``UTTER_PLATFORM=darwin`` is forced, so the
pid-post path, the timestamp fix, the no-pid (focused) behaviour, graceful
degradation without the API and the executor wiring are all asserted without a
real Mac.

Usage::

    .venv-agent/bin/python tests/platform/test_macos_background_input.py
"""
from __future__ import annotations

import contextlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.actions import keyboard
from utter.config import Config
from utter.executor import Executor
from utter.macos import desktop as mdesk
from utter.macos import inject
from utter.types import Action, ActionResult, Step, Tier


@contextlib.contextmanager
def forced_platform(name):
    orig = os.environ.get("UTTER_PLATFORM")
    os.environ["UTTER_PLATFORM"] = name
    try:
        yield
    finally:
        if orig is None:
            os.environ.pop("UTTER_PLATFORM", None)
        else:
            os.environ["UTTER_PLATFORM"] = orig


class FakeQuartz:
    """Records every Quartz call the injector makes."""

    kCGHIDEventTap = "HID"

    def __init__(self, *, pid_api: bool = True, timestamp_api: bool = True,
                 fresh_api: bool = True):
        self.calls = []
        self.events = []
        # Ensure the module is importable and the API surface is explicit.
        self.CGEventPost = lambda tap, ev: self.calls.append(("post", tap, ev))
        if pid_api:
            self.CGEventPostToPid = lambda pid, ev: self.calls.append(("post_pid", pid, ev))
        self.CGEventCreateKeyboardEvent = self._mk_key
        self.CGEventSetFlags = lambda ev, flags: self.calls.append(("flags", ev, flags))
        self.CGEventKeyboardSetUnicodeString = lambda ev, n, s: self.calls.append(("unicode", ev, s))
        if timestamp_api:
            self.CGEventGetTimestamp = lambda ev: 987654321
            self.CGEventSetTimestamp = lambda ev, ts: self.calls.append(("ts", ev, ts))
        if fresh_api:
            self.CGEventCreate = lambda src: ("fresh", src)

    def _mk_key(self, src, keycode, down):
        ev = ("ev", keycode, down)
        self.events.append(ev)
        return ev

    def kinds(self):
        return [c[0] for c in self.calls]

    def pid_posts(self):
        return [c for c in self.calls if c[0] == "post_pid"]


@contextlib.contextmanager
def fake_quartz(**kwargs):
    fake = FakeQuartz(**kwargs)
    orig = sys.modules.get("Quartz")
    sys.modules["Quartz"] = fake
    try:
        yield fake
    finally:
        if orig is None:
            sys.modules.pop("Quartz", None)
        else:
            sys.modules["Quartz"] = orig


class TestInjectPidPost(unittest.TestCase):
    def test_background_post_supported_true(self):
        with fake_quartz(pid_api=True):
            self.assertTrue(inject.background_post_supported())

    def test_background_post_supported_false_without_api(self):
        with fake_quartz(pid_api=False):
            self.assertFalse(inject.background_post_supported())

    def test_background_post_supported_false_without_quartz(self):
        orig = sys.modules.get("Quartz")
        sys.modules["Quartz"] = None  # `import Quartz` -> ImportError
        try:
            self.assertFalse(inject.background_post_supported())
        finally:
            if orig is None:
                sys.modules.pop("Quartz", None)
            else:
                sys.modules["Quartz"] = orig

    def test_send_key_with_pid_posts_to_pid_with_timestamp(self):
        with fake_quartz() as q:
            res = inject.send_key("cmd+t", pid=999)
            self.assertTrue(res.ok)
            self.assertIn("999", res.detail)
            self.assertNotIn("post", q.kinds())  # focused CGEventPost must not run
            self.assertTrue(q.pid_posts())
            self.assertEqual(q.pid_posts()[0][1], 999)
            # The Sequoia timestamp fix runs before every post.
            self.assertIn("ts", q.kinds())
            # Chord modifiers + key (down/up) all go to the pid.
            self.assertGreaterEqual(len(q.pid_posts()), 4)

    def test_send_key_without_pid_uses_focused_post(self):
        with fake_quartz() as q:
            res = inject.send_key("cmd+t")
            self.assertTrue(res.ok)
            self.assertIn("post", q.kinds())
            self.assertNotIn("post_pid", q.kinds())
            self.assertIn("ts", q.kinds())

    def test_send_key_pid_missing_api_degrades_not_raises(self):
        with fake_quartz(pid_api=False) as q:
            res = inject.send_key("cmd+t", pid=999)
            self.assertFalse(res.ok)
            self.assertTrue(res.unsupported)
            self.assertIn("unsupported", res.detail.lower())
            self.assertNotIn("post", q.kinds())       # no focus steal
            self.assertNotIn("post_pid", q.kinds())

    def test_type_text_with_pid(self):
        with fake_quartz() as q:
            res = inject.type_text("hello", pid=42)
            self.assertTrue(res.ok)
            self.assertIn("unicode", q.kinds())
            self.assertEqual(q.pid_posts()[0][1], 42)
            self.assertNotIn("post", q.kinds())
            self.assertIn("ts", q.kinds())

    def test_type_text_without_pid_uses_focused_post(self):
        with fake_quartz() as q:
            res = inject.type_text("hello")
            self.assertTrue(res.ok)
            self.assertIn("post", q.kinds())
            self.assertNotIn("post_pid", q.kinds())

    def test_type_text_pid_missing_api_degrades(self):
        with fake_quartz(pid_api=False) as q:
            res = inject.type_text("hello", pid=42)
            self.assertFalse(res.ok)
            self.assertTrue(res.unsupported)
            self.assertNotIn("post", q.kinds())

    def test_timestamp_api_missing_is_tolerated(self):
        with fake_quartz(timestamp_api=False) as q:
            res = inject.send_key("cmd+t", pid=7)
            self.assertTrue(res.ok)
            self.assertNotIn("ts", q.kinds())  # no setter available, no crash
            self.assertTrue(q.pid_posts())


class TestKeyboardDelegation(unittest.TestCase):
    def test_send_key_forwards_pid_on_macos(self):
        captured = {}

        def fake_send(chord, *, backend="quartz", pid=None):
            captured["chord"], captured["pid"] = chord, pid
            return ActionResult(True, Action.KEY, Tier.KEYBOARD, "stub")

        with forced_platform("darwin"), patch("utter.macos.inject.send_key", side_effect=fake_send):
            res = keyboard.send_key("cmd+t", pid=1234)
        self.assertTrue(res.ok)
        self.assertEqual(captured, {"chord": "cmd+t", "pid": 1234})

    def test_type_text_forwards_pid_on_macos(self):
        captured = {}

        def fake_type(text, *, backend="quartz", pid=None):
            captured["text"], captured["pid"] = text, pid
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "stub")

        with forced_platform("darwin"), patch("utter.macos.inject.type_text", side_effect=fake_type):
            res = keyboard.type_text("hi", pid=77)
        self.assertTrue(res.ok)
        self.assertEqual(captured, {"text": "hi", "pid": 77})

    def test_linux_ignores_pid_and_uses_local_backend(self):
        with forced_platform("linux"), \
             patch.object(keyboard, "_run", return_value=SimpleNamespace(returncode=0, stderr="")) as run:
            res = keyboard.send_key("ctrl+t", pid=5)
        self.assertTrue(res.ok)
        self.assertTrue(run.called)
        self.assertIn("wtype", run.call_args.args[0])


class TestExecutorWiring(unittest.TestCase):
    def _ex(self):
        return Executor(lambda **kw: None, Config())

    def test_macos_target_pid_from_window_id(self):
        win = SimpleNamespace(id=11, pid=4242, is_focused=False)
        with forced_platform("darwin"), \
             patch("utter.macos.inject.background_post_supported", return_value=True), \
             patch("utter.context.desktop.list_windows", return_value=[win]):
            pid = self._ex()._macos_target_pid(Step(Action.KEY, {"chord": "cmd+t", "window_id": 11}))
        self.assertEqual(pid, 4242)

    def test_macos_target_pid_from_app_prefers_focused(self):
        bg = SimpleNamespace(id=1, pid=111, is_focused=False)
        fg = SimpleNamespace(id=2, pid=222, is_focused=True)
        with forced_platform("darwin"), \
             patch("utter.macos.inject.background_post_supported", return_value=True), \
             patch("utter.context.desktop.find_windows", return_value=[bg, fg]):
            pid = self._ex()._macos_target_pid(Step(Action.KEY, {"chord": "cmd+t", "app": "Safari"}))
        self.assertEqual(pid, 222)

    def test_macos_no_target_returns_none(self):
        with forced_platform("darwin"), \
             patch("utter.macos.inject.background_post_supported", return_value=True):
            pid = self._ex()._macos_target_pid(Step(Action.KEY, {"chord": "cmd+t"}))
        self.assertIsNone(pid)

    def test_macos_unsupported_api_returns_none(self):
        win = SimpleNamespace(id=11, pid=4242, is_focused=False)
        with forced_platform("darwin"), \
             patch("utter.macos.inject.background_post_supported", return_value=False), \
             patch("utter.context.desktop.list_windows", return_value=[win]):
            pid = self._ex()._macos_target_pid(Step(Action.KEY, {"chord": "cmd+t", "window_id": 11}))
        self.assertIsNone(pid)

    def test_linux_short_circuits_before_desktop(self):
        with forced_platform("linux"), \
             patch("utter.context.desktop.list_windows", side_effect=AssertionError("must not run")):
            pid = self._ex()._macos_target_pid(Step(Action.KEY, {"chord": "cmd+t", "window_id": 11}))
        self.assertIsNone(pid)

    def test_do_key_passes_pid_to_keyboard(self):
        captured = {}

        def fake_send(chord, *, pid=None):
            captured["chord"], captured["pid"] = chord, pid
            return ActionResult(True, Action.KEY, Tier.KEYBOARD, "stub")

        with forced_platform("darwin"), \
             patch.object(Executor, "_macos_target_pid", return_value=4242), \
             patch("utter.actions.keyboard.send_key", side_effect=fake_send):
            res = self._ex()._do_key(Step(Action.KEY, {"chord": "cmd+t", "window_id": 11}))
        self.assertTrue(res.ok)
        self.assertEqual(captured, {"chord": "cmd+t", "pid": 4242})

    def test_do_type_text_passes_pid_to_keyboard(self):
        captured = {}

        def fake_type(text, *, pid=None):
            captured["text"], captured["pid"] = text, pid
            return ActionResult(True, Action.TYPE_TEXT, Tier.KEYBOARD, "stub")

        with forced_platform("darwin"), \
             patch.object(Executor, "_macos_target_pid", return_value=99), \
             patch("utter.actions.keyboard.type_text", side_effect=fake_type):
            res = self._ex()._do_type_text(Step(Action.TYPE_TEXT, {"text": "hi", "app": "Safari"}))
        self.assertTrue(res.ok)
        self.assertEqual(captured, {"text": "hi", "pid": 99})


class TestMacosCloseWindow(unittest.TestCase):
    def _mock_as(self, perform=0):
        return SimpleNamespace(
            AXUIElementCreateApplication=lambda pid: "app",
            AXUIElementCopyAttributeValue=lambda app, attr, val: (0, ["w1"]),
            _AXUIElementGetWindow=lambda win, val: (0, 501),
            AXUIElementPerformAction=lambda win, action: perform,
            kAXWindowsAttribute="AXWindows",
            kAXCloseAction="AXClose",
        )

    def test_close_window_success(self):
        as_mod = self._mock_as(perform=0)
        orig = sys.modules.get("ApplicationServices")
        sys.modules["ApplicationServices"] = as_mod
        try:
            with patch.object(mdesk, "_raw_windows",
                              return_value=[{"id": 501, "pid": 777, "title": "t"}]):
                out = mdesk.close_window(501)
            self.assertTrue(out.ok)
            self.assertFalse(out.unsupported)
        finally:
            if orig is None:
                sys.modules.pop("ApplicationServices", None)
            else:
                sys.modules["ApplicationServices"] = orig

    def test_close_window_ax_failure_is_not_faked(self):
        as_mod = self._mock_as(perform=1)
        orig = sys.modules.get("ApplicationServices")
        sys.modules["ApplicationServices"] = as_mod
        try:
            with patch.object(mdesk, "_raw_windows",
                              return_value=[{"id": 501, "pid": 777, "title": "t"}]):
                out = mdesk.close_window(501)
            self.assertFalse(out.ok)
        finally:
            if orig is None:
                sys.modules.pop("ApplicationServices", None)
            else:
                sys.modules["ApplicationServices"] = orig

    def test_close_window_unsupported_without_pyobjc(self):
        orig = sys.modules.get("ApplicationServices")
        sys.modules["ApplicationServices"] = None  # `import ApplicationServices` -> ImportError
        try:
            out = mdesk.close_window(1)
            self.assertFalse(out.ok)
            self.assertTrue(out.unsupported)
        finally:
            if orig is None:
                sys.modules.pop("ApplicationServices", None)
            else:
                sys.modules["ApplicationServices"] = orig


if __name__ == "__main__":
    unittest.main()
