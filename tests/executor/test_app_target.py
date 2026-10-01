#!/usr/bin/env python3
"""App-targeted input: resolution + focus round-trip executor behaviour.

A fake compositor is monkeypatched over ``utter.context.desktop`` so these
tests never touch the real desktop. They pin:

* resolution (app_ids dedup, 0/1/N windows, close never guesses);
* the focus round-trip (same-window no-op, same-workspace focus+restore,
  cross-workspace/fullscreen confirmation, focus-never-lands abort, and
  "user moved away" no-restore);
* close never focuses, and media picks the named MPRIS player.

Run directly::

    .venv-agent/bin/python tests/executor/test_app_target.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter import executor as executor_mod  # noqa: E402
from utter.config import Config, TargetConfig, WaylandConfig, load_config  # noqa: E402
from utter.context import desktop  # noqa: E402
from utter.executor import Executor, _select_mpris  # noqa: E402
from utter.router.profiles import AppProfile  # noqa: E402
from utter.types import Action, ActionResult, FocusedWindow, Step, Tier, WindowInfo  # noqa: E402

INJECTED: list = []


def _stub_key(chord):
    INJECTED.append(("key", chord))
    return ActionResult(True, Action.KEY, Tier.KEYBOARD, "stub")


def _stub_type(text):
    INJECTED.append(("type", text))
    return ActionResult(True, Action.TYPE_TEXT, Tier.APP, "stub")


WIN_CODEX = WindowInfo(id=10, app_id="codex", workspace_id=1)
WIN_CODEX2 = WindowInfo(id=11, app_id="codex", workspace_id=3)
WIN_OTHER = WindowInfo(id=20, app_id="kitty", workspace_id=1)


class FakeBackend:
    def __init__(self):
        self.closed: list = []

    def close_window(self, window_id):
        self.closed.append(window_id)
        return mock.Mock(ok=True, detail=f"closed {window_id}", unsupported=False)


class FakeDesktop:
    """Minimal stand-in for ``utter.context.desktop``."""

    def __init__(self, windows, focused, *, focus_lands=True):
        self.windows = list(windows)
        self.focused = focused
        self.focus_lands = focus_lands
        self.calls: list = []
        self.backend_obj = FakeBackend()

    # provider surface
    def focused_window(self):
        return self.focused

    def list_windows(self):
        return list(self.windows)

    def find_windows(self, app_id=None, title_contains=None):
        self.calls.append(("find", app_id))
        needle = (app_id or "").lower()
        return [w for w in self.windows if needle in (w.app_id or "").lower()]

    def focus_window_on_workspace(self, window_id):
        self.calls.append(("focus", window_id))
        if self.focus_lands:
            for w in self.windows:
                if w.id == window_id:
                    self.focused = FocusedWindow(
                        app_id=w.app_id, title=w.title, pid=w.pid,
                        window_id=w.id, workspace_id=w.workspace_id,
                        is_fullscreen=w.is_fullscreen)
        return True

    def focus_window(self, window_id):
        return self.focus_window_on_workspace(window_id)

    def backend(self):
        return self.backend_obj


class AppTargetExecutorTest(unittest.TestCase):
    def setUp(self):
        INJECTED.clear()
        self.profiles = {
            "codex": AppProfile(id="codex", name="Codex", aliases=["codex"]),
            "steam": AppProfile(id="steam", name="Steam", aliases=["steam"],
                                app_ids=["steam", "Steam", "steam"]),
            "spotify": AppProfile(id="spotify", name="Spotify", aliases=["spotify"],
                                  app_ids=["spotify", "com.spotify.Client", "spotify"]),
        }
        self.cfg = Config()
        self.confirm_requests: list = []
        self.confirm_answer = True
        self.confirm = lambda req: (self.confirm_requests.append(req), self.confirm_answer)[1]
        self.fake = None
        self._keyboard_patches = [
            mock.patch.object(executor_mod, "_mpris", executor_mod._mpris),
            mock.patch("utter.actions.keyboard.send_key", _stub_key),
            mock.patch("utter.actions.keyboard.type_text", _stub_type),
        ]
        for p in self._keyboard_patches:
            p.start()
            self.addCleanup(p.stop)

    def _patch_desktop(self, fake: FakeDesktop):
        self.fake = fake
        for name in ("focused_window", "list_windows", "find_windows",
                     "focus_window_on_workspace", "focus_window", "backend"):
            p = mock.patch.object(desktop, name, getattr(fake, name))
            p.start()
            self.addCleanup(p.stop)

    def _executor(self, confirm=None):
        return Executor(lambda with_a11y=False: None, self.cfg,
                        profiles=self.profiles, confirm=confirm)

    def _type_step(self, app="codex", text="hello"):
        return Step(Action.TYPE_TEXT, {"text": text, "app": app}, tier=Tier.APP)

    def _run_type(self, fake, *, confirm=None, app="codex"):
        self._patch_desktop(fake)
        return self._executor(confirm=confirm).execute_step(self._type_step(app=app))

    # -- round-trip ---------------------------------------------------------
    def test_same_window_runs_without_focus(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="codex", window_id=10, workspace_id=1))
        res = self._run_type(fake)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(INJECTED, [("type", "hello")])
        self.assertEqual([c for c in fake.calls if c[0] == "focus"], [])  # no focus call

    def test_same_workspace_focuses_then_restores(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=1))
        res = self._run_type(fake, confirm=self.confirm)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(INJECTED, [("type", "hello")])
        # focus target 10, then restore previous 20; no confirmation same-ws.
        self.assertEqual(fake.calls, [("find", "codex"), ("focus", 10), ("focus", 20)])
        self.assertEqual(self.confirm_requests, [])

    def test_cross_workspace_asks_and_proceeds(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=2))
        res = self._run_type(fake, confirm=self.confirm)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(len(self.confirm_requests), 1)
        req = self.confirm_requests[0]
        self.assertEqual(req["app"], "Codex")
        self.assertEqual(req["window_id"], 10)
        self.assertEqual(req["workspace_id"], 1)
        self.assertIn("cross_workspace", req["reasons"])
        self.assertNotIn("title", req)
        self.assertEqual(INJECTED, [("type", "hello")])

    def test_cross_workspace_refuses_without_channel(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=2))
        res = self._run_type(fake, confirm=None)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])
        self.assertEqual([c for c in fake.calls if c[0] == "focus"], [])

    def test_cross_workspace_denied(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=2))
        self.confirm_answer = False
        res = self._run_type(fake, confirm=self.confirm)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_cross_workspace_allow_no_ask(self):
        self.cfg.target = TargetConfig(cross_workspace="allow")
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=2))
        res = self._run_type(fake, confirm=None)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(self.confirm_requests, [])
        self.assertEqual(INJECTED, [("type", "hello")])

    def test_cross_workspace_refuse_mode(self):
        self.cfg.target = TargetConfig(cross_workspace="refuse")
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=2))
        res = self._run_type(fake, confirm=self.confirm)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_fullscreen_prev_asks(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(
            app_id="kitty", window_id=20, workspace_id=1, is_fullscreen=True))
        res = self._run_type(fake, confirm=self.confirm)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(len(self.confirm_requests), 1)
        self.assertIn("fullscreen", self.confirm_requests[0]["reasons"])
        self.assertEqual(INJECTED, [("type", "hello")])

    def test_fullscreen_prev_refuses_without_channel(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(
            app_id="kitty", window_id=20, workspace_id=1, is_fullscreen=True))
        res = self._run_type(fake, confirm=None)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_focus_never_lands_aborts_without_injection(self):
        fake = FakeDesktop([WIN_CODEX],
                           focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=1),
                           focus_lands=False)
        self.cfg.target = TargetConfig(focus_timeout_ms=20)
        res = self._run_type(fake, confirm=self.confirm)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_user_switches_away_no_restore(self):
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=1))

        def _type_and_switch(text):
            INJECTED.append(("type", text))
            # Simulate the user moving focus while we were injecting.
            fake.focused = FocusedWindow(app_id="kitty", window_id=20, workspace_id=1)
            return ActionResult(True, Action.TYPE_TEXT, Tier.APP, "stub")

        with mock.patch("utter.actions.keyboard.type_text", _type_and_switch):
            res = self._run_type(fake, confirm=self.confirm)
        self.assertTrue(res.ok, res.detail)
        focus_calls = [c for c in fake.calls if c[0] == "focus"]
        self.assertEqual(focus_calls, [("focus", 10)])  # no restore yank

    def test_prev_none_focuses_no_confirm(self):
        fake = FakeDesktop([WIN_CODEX], focused=None)
        res = self._run_type(fake, confirm=None)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(self.confirm_requests, [])
        self.assertEqual(INJECTED, [("type", "hello")])

    def test_leave_mode_stays(self):
        self.cfg.target = TargetConfig(mode="leave")
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=1))
        res = self._run_type(fake, confirm=self.confirm)
        self.assertTrue(res.ok, res.detail)
        focus_calls = [c for c in fake.calls if c[0] == "focus"]
        self.assertEqual(focus_calls, [("focus", 10)])  # acts and stays

    def test_off_mode_refuses_targeted_input(self):
        self.cfg.target = TargetConfig(mode="off")
        fake = FakeDesktop([WIN_CODEX], focused=FocusedWindow(app_id="kitty", window_id=20, workspace_id=1))
        res = self._run_type(fake, confirm=self.confirm)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_unfocused_plain_key_unchanged(self):
        # No app/window target -> exact legacy behaviour, no focus machinery.
        ex = self._executor(confirm=self.confirm)
        res = ex.execute_step(Step(Action.KEY, {"chord": "Return"}, tier=Tier.KEYBOARD))
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(INJECTED, [("key", "Return")])

    # -- [wayland] workspace / animation policy matrix ----------------------
    def _run_cross(self, *, wayland, target_ws=1, prev_ws=2, confirm=None, fullscreen=False):
        self.cfg.wayland = wayland
        fake = FakeDesktop(
            [WindowInfo(id=10, app_id="codex", workspace_id=target_ws)],
            focused=FocusedWindow(app_id="kitty", window_id=20,
                                  workspace_id=prev_ws, is_fullscreen=fullscreen))
        return self._run_type(fake, confirm=confirm)

    def test_wayland_same_workspace_never_asks(self):
        # auto + animations on would ask cross-workspace, but same-ws is invisible.
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="auto", assume_animations_off=False),
                              target_ws=3, prev_ws=3, confirm=None)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(self.confirm_requests, [])
        self.assertEqual(INJECTED, [("type", "hello")])

    def test_wayland_auto_animations_off_cross_ws_allows(self):
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="auto", assume_animations_off=True),
                              target_ws=3, prev_ws=1, confirm=None)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(self.confirm_requests, [])
        self.assertEqual(INJECTED, [("type", "hello")])

    def test_wayland_auto_animations_on_cross_ws_asks(self):
        self.cfg.target = TargetConfig(cross_workspace="ask")
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="auto", assume_animations_off=False),
                              target_ws=3, prev_ws=1, confirm=self.confirm)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(len(self.confirm_requests), 1)
        self.assertIn("cross_workspace", self.confirm_requests[0]["reasons"])

    def test_wayland_auto_animations_on_cross_ws_refuses_without_channel(self):
        self.cfg.target = TargetConfig(cross_workspace="ask")
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="auto", assume_animations_off=False),
                              target_ws=3, prev_ws=1, confirm=None)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_wayland_allow_cross_ws_no_ask(self):
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="allow"),
                              target_ws=3, prev_ws=1, confirm=None)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(self.confirm_requests, [])

    def test_wayland_refuse_cross_ws(self):
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="refuse"),
                              target_ws=3, prev_ws=1, confirm=self.confirm)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_wayland_ask_overrides_target_allow(self):
        self.cfg.target = TargetConfig(cross_workspace="allow")
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="ask"),
                              target_ws=3, prev_ws=1, confirm=None)
        self.assertFalse(res.ok, res.detail)  # ask + no channel -> refuse

    def test_wayland_allow_overrides_target_refuse(self):
        self.cfg.target = TargetConfig(cross_workspace="refuse")
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="allow"),
                              target_ws=3, prev_ws=1, confirm=None)
        self.assertTrue(res.ok, res.detail)

    def test_wayland_auto_falls_back_to_target_refuse(self):
        self.cfg.target = TargetConfig(cross_workspace="refuse")
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="auto", assume_animations_off=False),
                              target_ws=3, prev_ws=1, confirm=self.confirm)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])

    def test_fullscreen_same_workspace_still_asks(self):
        # Fullscreen-prev remains an independent ask reason (prior design).
        res = self._run_cross(wayland=WaylandConfig(cross_workspace="auto", assume_animations_off=True),
                              target_ws=3, prev_ws=3, fullscreen=True, confirm=None)
        self.assertFalse(res.ok, res.detail)
        self.assertEqual(INJECTED, [])


class WaylandConfigParsingTest(unittest.TestCase):
    def test_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.wayland.cross_workspace, "auto")
        self.assertFalse(cfg.wayland.assume_animations_off)

    def test_toml_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.toml"
            p.write_text('[wayland]\ncross_workspace = "refuse"\nassume_animations_off = true\n')
            cfg = load_config(p)
        self.assertEqual(cfg.wayland.cross_workspace, "refuse")
        self.assertTrue(cfg.wayland.assume_animations_off)


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "steam": AppProfile(id="steam", name="Steam", aliases=["steam"],
                                app_ids=["steam", "Steam", "steam"]),
            "spotify": AppProfile(id="spotify", name="Spotify", aliases=["spotify"],
                                  app_ids=["spotify", "com.spotify.Client"]),
        }
        self.ex = Executor(lambda with_a11y=False: None, Config(), profiles=self.profiles)

    def _step(self, action, args):
        return Step(action, args, tier=Tier.APP)

    def test_candidate_ids_dedup(self):
        self.assertEqual(self.ex._candidate_ids("steam"), ["steam", "Steam"])

    def test_windows_dedup_by_id(self):
        # find_windows("steam") and find_windows("Steam") both return the same id.
        w = WindowInfo(id=1, app_id="steam")
        calls: list = []

        def find(app_id=None, title_contains=None):
            calls.append(app_id)
            return [w]

        with mock.patch.object(desktop, "find_windows", find):
            windows = self.ex._windows_for_app("steam")
        self.assertEqual([x.id for x in windows], [1])
        self.assertEqual(len(windows), 1)

    def test_zero_windows_refuses(self):
        with mock.patch.object(desktop, "find_windows", lambda app_id=None, title_contains=None: []):
            target, err = self.ex._resolve_target(self._step(Action.TYPE_TEXT, {"app": "steam"}), destructive=False)
        self.assertIsNone(target)
        self.assertIn("not running", err)

    def test_single_window(self):
        w = WindowInfo(id=5, app_id="steam", workspace_id=2)
        with mock.patch.object(desktop, "find_windows", lambda app_id=None, title_contains=None: [w]):
            target, err = self.ex._resolve_target(self._step(Action.TYPE_TEXT, {"app": "steam"}), destructive=False)
        self.assertEqual(target.id, 5)
        self.assertEqual(err, "")

    def test_multi_prefers_focused_then_workspace_then_id(self):
        wins = [WindowInfo(id=3, app_id="steam", workspace_id=1),
                WindowInfo(id=2, app_id="steam", workspace_id=1),
                WindowInfo(id=1, app_id="steam", workspace_id=1, is_focused=True)]
        with mock.patch.object(desktop, "find_windows", lambda app_id=None, title_contains=None: wins):
            target, _ = self.ex._resolve_target(self._step(Action.TYPE_TEXT, {"app": "steam"}), destructive=False)
        self.assertEqual(target.id, 1)  # focused wins
        wins = [WindowInfo(id=9, app_id="steam", workspace_id=4),
                WindowInfo(id=2, app_id="steam", workspace_id=1)]
        with mock.patch.object(desktop, "find_windows", lambda app_id=None, title_contains=None: wins):
            target, _ = self.ex._resolve_target(self._step(Action.TYPE_TEXT, {"app": "steam"}), destructive=False)
        self.assertEqual(target.id, 2)  # lowest workspace

    def test_multi_close_refuses(self):
        wins = [WindowInfo(id=3, app_id="steam"), WindowInfo(id=2, app_id="steam")]
        with mock.patch.object(desktop, "find_windows", lambda app_id=None, title_contains=None: wins):
            target, err = self.ex._resolve_target(self._step(Action.CLOSE_APP, {"app": "steam"}), destructive=True)
        self.assertIsNone(target)
        self.assertIn("refusing to guess", err)

    def test_close_never_focuses_and_targets_id(self):
        fake = FakeDesktop([WindowInfo(id=7, app_id="steam")],
                           focused=FocusedWindow(app_id="kitty", window_id=99, workspace_id=1))
        for name in ("focused_window", "list_windows", "find_windows", "backend"):
            p = mock.patch.object(desktop, name, getattr(fake, name))
            p.start()
            self.addCleanup(p.stop)
        res = self.ex.execute_step(self._step(Action.CLOSE_APP, {"app": "steam"}))
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(fake.backend_obj.closed, [7])
        self.assertEqual([c for c in fake.calls if c[0] == "focus"], [])


class MediaSelectionTest(unittest.TestCase):
    def test_two_players_named_pick(self):
        names = ["org.mpris.MediaPlayer2.vlc",
                 "org.mpris.MediaPlayer2.spotify",
                 "dev.noctalia.Mpris"]
        self.assertEqual(_select_mpris(names, ["spotify"]),
                         "org.mpris.MediaPlayer2.spotify")
        self.assertEqual(_select_mpris(names, ["vlc"]),
                         "org.mpris.MediaPlayer2.vlc")

    def test_no_match_is_none_not_wrong_player(self):
        names = ["org.mpris.MediaPlayer2.vlc"]
        self.assertIsNone(_select_mpris(names, ["spotify"]))

    def test_no_filter_prefers_real_player(self):
        names = ["dev.noctalia.Mpris", "org.mpris.MediaPlayer2.vlc"]
        self.assertEqual(_select_mpris(names), "org.mpris.MediaPlayer2.vlc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
