#!/usr/bin/env python3
"""Golden cases for app-targeted commands (``utter.router.rules``).

Pins the plan shape of the target-first matcher that sits between ``_cli_agent``
and ``_terminal``::

    codex type ok   -> type_text {text: ok, app: codex}
    codex press enter -> key {chord: Return, app: codex}
    spotify pause   -> media {command: pause, app: spotify}
    close steam     -> close_app {app: steam}

An ``app`` is set at plan time; ``window_id`` never is (the executor resolves it
from the live compositor list). Generic/ambiguous aliases must not be claimed,
so existing ``type ok`` / ``press enter`` stay focused injection with no app.

Run directly::

    .venv-agent/bin/python tests/router/test_app_target_rules.py
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from utter.router import rules  # noqa: E402
from utter.router.profiles import AppProfile  # noqa: E402
from utter.types import Context, FocusedWindow  # noqa: E402

CODEX = AppProfile(id="codex", name="Codex", aliases=["codex"])
STEAM = AppProfile(id="steam", name="Steam", aliases=["steam"],
                   app_ids=["steam", "Steam"])
SPOTIFY = AppProfile(id="spotify", name="Spotify", aliases=["spotify", "music"],
                     app_ids=["spotify", "Spotify", "com.spotify.Client"])
FIREFOX = AppProfile(id="firefox", name="Firefox", kind="browser", aliases=["browser"])

PROFILES = {"codex": CODEX, "steam": STEAM, "spotify": SPOTIFY, "firefox": FIREFOX}

NONE = Context(focused=None)
TEXT = Context(focused=FocusedWindow(app_id="code", title="main.py"))


def steps(plan):
    if plan is None:
        return None
    return [(s.action.value, s.args) for s in plan.steps]


class AppTargetRulesTest(unittest.TestCase):
    def test_codex_type(self):
        plan = rules.plan("codex type ok", NONE, PROFILES)
        self.assertEqual(steps(plan), [("type_text", {"text": "ok", "app": "codex"})])
        self.assertNotIn("window_id", plan.steps[0].args)

    def test_codex_press(self):
        plan = rules.plan("codex press enter", NONE, PROFILES)
        self.assertEqual(steps(plan), [("key", {"chord": "Return", "app": "codex"})])
        self.assertNotIn("window_id", plan.steps[0].args)

    def test_spotify_pause(self):
        plan = rules.plan("spotify pause", NONE, PROFILES)
        self.assertEqual(steps(plan), [("media", {"command": "pause", "app": "spotify"})])
        self.assertNotIn("window_id", plan.steps[0].args)

    def test_close_steam(self):
        plan = rules.plan("close steam", NONE, PROFILES)
        self.assertEqual(steps(plan), [("close_app", {"app": "steam"})])
        self.assertNotIn("window_id", plan.steps[0].args)

    def test_plain_type_stays_focused(self):
        plan = rules.plan("type ok", TEXT, PROFILES)
        self.assertEqual(steps(plan), [("type_text", {"text": "ok"})])

    def test_plain_press_stays_focused(self):
        plan = rules.plan("press enter", TEXT, PROFILES)
        self.assertEqual(steps(plan), [("key", {"chord": "Return"})])

    def test_write_stays_focused(self):
        plan = rules.plan("write hello world", TEXT, PROFILES)
        self.assertEqual(steps(plan), [("type_text", {"text": "hello world"})])

    def test_unknown_leading_word_not_claimed(self):
        # "please" resolves to no profile -> generic type matcher handles it?
        # (it does not start with type/write, so there is no plan).
        self.assertIsNone(rules.plan("please type hello", NONE, PROFILES))

    def test_generic_alias_not_claimed_for_media(self):
        # "music" is an alias of Spotify but too generic to target.
        self.assertIsNone(rules.plan("music pause", NONE, PROFILES))

    def test_generic_alias_not_claimed_for_close(self):
        self.assertIsNone(rules.plan("close music", NONE, PROFILES))

    def test_close_site_keeps_focus_then_close_pair(self):
        plan = rules.plan("close github", NONE, PROFILES)
        self.assertEqual(steps(plan), [
            ("ensure_url", {"url": "https://github.com", "site": "github"}),
            ("niri", {"command": "close-window", "args": []}),
        ])

    def test_close_window_generic(self):
        plan = rules.plan("close window", NONE, PROFILES)
        self.assertEqual(steps(plan), [("niri", {"command": "close-window", "args": []})])


if __name__ == "__main__":
    unittest.main(verbosity=2)
