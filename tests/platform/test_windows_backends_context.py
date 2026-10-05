#!/usr/bin/env python3
"""Windows desktop-context / clipboard / launch backends (P0).

Two layers:

* **Linux-runnable** pure-logic + dispatch tests — app_id derivation from an exe
  path, Start-Menu ``.lnk`` discovery, permission helpers, and that the platform
  seams in ``utter.context.desktop`` / ``clipboard`` / ``textfields`` and
  ``utter.actions.launch`` select the ``utter.win32.*`` module when
  ``UTTER_PLATFORM=windows``.
* **Windows-gated** (``skipUnless sys.platform == "win32"``) shape smoke tests
  that call the real ctypes/UIA providers.

Usage::

    .venv-agent/bin/python tests/platform/test_windows_backends_context.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utter import platform  # noqa: E402
from utter.actions import launch as launch_mod  # noqa: E402
from utter.context import clipboard as clipboard_mod  # noqa: E402
from utter.context import desktop as desktop_mod  # noqa: E402
from utter.context import textfields  # noqa: E402
from utter.types import ActionResult, Action, Tier  # noqa: E402
from utter.win32 import desktop as win_desktop  # noqa: E402
from utter.win32 import launch as win_launch  # noqa: E402
from utter.win32 import permissions as win_permissions  # noqa: E402


class forced_platform:
    """Context manager forcing ``UTTER_PLATFORM`` (None = unset)."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.prev = os.environ.get("UTTER_PLATFORM")
        if self.value is None:
            os.environ.pop("UTTER_PLATFORM", None)
        else:
            os.environ["UTTER_PLATFORM"] = self.value
        return self

    def __exit__(self, *exc):
        if self.prev is None:
            os.environ.pop("UTTER_PLATFORM", None)
        else:
            os.environ["UTTER_PLATFORM"] = self.prev


class env:
    """Set/remove env vars for the duration of a block, then restore."""

    def __init__(self, **kw):
        self.kw = kw
        self.saved: dict = {}

    def __enter__(self):
        for key, value in self.kw.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AppIdDerivationTest(unittest.TestCase):
    def test_windows_path(self):
        self.assertEqual(
            win_desktop.app_id_from_exe(
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            "chrome")

    def test_posix_separator(self):
        self.assertEqual(win_desktop.app_id_from_exe("/usr/bin/foot"), "foot")

    def test_uppercase_exe_and_quoting(self):
        self.assertEqual(
            win_desktop.app_id_from_exe('"C:\\Windows\\System32\\notepad.EXE"'),
            "notepad")

    def test_no_extension_is_kept(self):
        self.assertEqual(win_desktop.app_id_from_exe(r"C:\Apps\MyTool"), "mytool")

    def test_empty_inputs(self):
        for value in ("", None, "   ", '"'):
            self.assertEqual(win_desktop.app_id_from_exe(value), "")


class LnkDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        (self.base / "Programs").mkdir()
        (self.base / "Programs" / "Google Chrome.lnk").write_text("")
        (self.base / "Programs" / "Sub").mkdir()
        (self.base / "Programs" / "Sub" / "Notepad.lnk").write_text("")

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_stem_match(self):
        found = win_launch.find_lnk("Notepad", dirs=[self.base / "Programs"])
        self.assertEqual(found.name, "Notepad.lnk")

    def test_case_insensitive_substring_match(self):
        found = win_launch.find_lnk("chrome", dirs=[self.base / "Programs"])
        self.assertEqual(found.name, "Google Chrome.lnk")

    def test_lnk_suffix_accepted(self):
        found = win_launch.find_lnk("notepad.lnk", dirs=[self.base / "Programs"])
        self.assertEqual(found.name, "Notepad.lnk")

    def test_missing_and_empty_return_none(self):
        self.assertIsNone(win_launch.find_lnk("nope", dirs=[self.base / "Programs"]))
        self.assertIsNone(win_launch.find_lnk("", dirs=[self.base / "Programs"]))

    def test_exact_wins_over_substring_across_dirs(self):
        (self.base / "Other").mkdir()
        (self.base / "Other" / "chrome helper.lnk").write_text("")
        found = win_launch.find_lnk(
            "chrome", dirs=[self.base / "Programs", self.base / "Other"])
        # "Google Chrome.lnk" is an exact stem match despite the first dir's
        # substring candidate.
        self.assertEqual(found.name, "Google Chrome.lnk")

    def test_start_menu_dirs_from_env(self):
        with env(APPDATA=str(self.base / "roaming"),
                 PROGRAMDATA=str(self.base / "programdata")):
            dirs = win_launch._start_menu_dirs()
        self.assertEqual(dirs[0], self.base / "roaming" / "Microsoft" / "Windows"
                         / "Start Menu" / "Programs")
        self.assertEqual(dirs[1], self.base / "programdata" / "Microsoft" / "Windows"
                         / "Start Menu" / "Programs")


class PermissionsPureTest(unittest.TestCase):
    def test_settings_url(self):
        self.assertEqual(win_permissions.settings_url("microphone"),
                         "ms-settings:privacy-microphone")
        with self.assertRaises(KeyError):
            win_permissions.settings_url("nope")

    def test_permission_table_shape(self):
        self.assertEqual(win_permissions.PERMISSION_IDS, ["microphone"])
        for entry in win_permissions.PERMISSIONS:
            self.assertTrue({"id", "label", "why"} <= set(entry))

    def test_checks_are_unknown_off_windows(self):
        with forced_platform("linux"):
            self.assertEqual(win_permissions.check("microphone"),
                             win_permissions.UNKNOWN)

    def test_status_all_is_advisory(self):
        with tempfile.TemporaryDirectory() as td, forced_platform("linux"), env(
                UTTER_PERMISSIONS_FILE=str(Path(td) / "permissions.json")):
            doc = win_permissions.status_all(write=True)
            self.assertEqual(doc["platform"], "linux")
            self.assertTrue(doc["advisory"])
            self.assertFalse(doc["all_granted"])
            self.assertEqual(len(doc["permissions"]), 1)
            self.assertEqual(win_permissions.read_state()["permissions"][0]["id"],
                             "microphone")

    def test_state_file_honours_localappdata(self):
        with tempfile.TemporaryDirectory() as td, env(
                LOCALAPPDATA=td, UTTER_PERMISSIONS_FILE=None):
            self.assertEqual(win_permissions.state_file(),
                             Path(td) / "utter" / "permissions.json")


class LazyImportTest(unittest.TestCase):
    def test_require_windows_raises_off_windows(self):
        with forced_platform("linux"):
            with self.assertRaises(win_desktop.WindowsUnavailable):
                win_desktop.require_windows()

    def test_providers_degrade_on_linux(self):
        with forced_platform("linux"):
            self.assertIsNone(win_desktop.focused_window())
            self.assertEqual(win_desktop.list_windows(), [])
            self.assertEqual(win_desktop.list_monitors(), [])
            self.assertFalse(win_desktop.focus_window(1))
            self.assertEqual(win_desktop.build_context().windows, [])
            self.assertTrue(win_launch.find_lnk("x") is None)
            self.assertEqual(__import__("utter.win32.clipboard", fromlist=["x"])
                             .get_clipboard(), "")

    def test_axtree_available_off_windows(self):
        from utter.win32 import axtree
        with forced_platform("linux"):
            ok, reason = axtree.available()
        self.assertFalse(ok)
        self.assertEqual(reason, "win-unavailable")


class DispatchTest(unittest.TestCase):
    def test_desktop_provider_and_backend_select_win32(self):
        with forced_platform("windows"):
            self.assertIs(desktop_mod.provider(), win_desktop)
            self.assertIs(desktop_mod.backend(), win_desktop)

    def test_clipboard_delegates_to_win32(self):
        with forced_platform("windows"), \
                patch("utter.win32.clipboard.get_clipboard", return_value="SENT") as get, \
                patch("utter.win32.clipboard.set_clipboard", return_value=True) as put:
            self.assertEqual(clipboard_mod.get_clipboard(), "SENT")
            self.assertTrue(clipboard_mod.set_clipboard("x"))
        get.assert_called_once()
        put.assert_called_once_with("x")

    def test_actions_launch_delegates_to_win32(self):
        sentinel = ActionResult(True, Action.LAUNCH_APP, Tier.APP, "sentinel")
        with forced_platform("windows"), \
                patch("utter.win32.launch.launch_app", return_value=sentinel) as fn, \
                patch("utter.win32.launch.open_url", return_value=sentinel) as url:
            self.assertIs(launch_mod.launch_app("chrome"), sentinel)
            self.assertIs(launch_mod.open_url("youtube.com", browser_app_id="zen"),
                          sentinel)
        fn.assert_called_once_with("chrome")
        url.assert_called_once_with("youtube.com", browser_app_id="zen")

    def test_textfields_probes_win32_axtree(self):
        fake = MagicMock()
        fake.available.return_value = (False, "uiautomation-unavailable")
        with forced_platform("windows"), patch.object(textfields, "_winaxtree",
                                                      return_value=fake):
            result = textfields.probe()
            status = textfields.detection_status()
        self.assertFalse(result.available)
        self.assertEqual(result.reason, "uiautomation-unavailable")
        self.assertEqual(status["platform"], "windows")
        self.assertEqual(status["reason"], "uiautomation-unavailable")
        self.assertEqual(status["count"], 0)


class LinuxDispatchUnchangedTest(unittest.TestCase):
    def test_macos_not_selected_on_linux(self):
        with forced_platform("linux"), patch.object(
                platform, "is_macos", return_value=False):
            from utter.context.backends import fallback
            # provider() may be niri or the fallback depending on the session;
            # it must never be the Windows module.
            self.assertIsNot(desktop_mod.provider(), win_desktop)
            self.assertIsNotNone(fallback)


@unittest.skipUnless(sys.platform == "win32", "requires a real Windows host")
class WindowsShapeSmokeTest(unittest.TestCase):
    def test_desktop_shapes(self):
        focused = win_desktop.focused_window()
        if focused is not None:
            self.assertTrue(hasattr(focused, "app_id"))
            self.assertTrue(hasattr(focused, "window_id"))
        for window in win_desktop.list_windows():
            self.assertIsInstance(window.id, int)
            self.assertIsInstance(window.app_id, str)
            self.assertIsInstance(window.is_focused, bool)
        self.assertIsInstance(win_desktop.find_windows(app_id="x"), list)
        self.assertIsInstance(win_desktop.list_monitors(), list)

    def test_clipboard_round_trip(self):
        from utter.win32 import clipboard as win_clipboard
        self.assertTrue(win_clipboard.set_clipboard("utter-test"))
        self.assertEqual(win_clipboard.get_clipboard(), "utter-test")

    def test_axtree_and_permissions(self):
        from utter.win32 import axtree
        ok, reason = axtree.available()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)
        self.assertIn(win_permissions.check("microphone"),
                      {"granted", "denied", "not_determined", "unknown"})

    def test_launch_unknown_app_returns_result(self):
        result = win_launch.launch_app("utter-app-that-does-not-exist-xyz")
        self.assertIsInstance(result, ActionResult)
        self.assertIs(result.action, Action.LAUNCH_APP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
