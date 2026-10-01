#!/usr/bin/env python3
"""App-targeted action op registry + provenance table (``runner/policy``).

Regression guard for the bug where the plugin advertised 13 ops but the runner
registered only 6, so ``runner.command`` rejected ``key`` / ``type_text`` /
``media`` / ``focus_app`` / ``ensure_app`` / ``search`` / ``scroll`` with
``-32601 unknown action op``.

Also pins the trust rule: untrusted (``screen``) content may select, never
author concrete args (``-32006``); ``close_app`` is confirmation-required;
``terminal``/``input`` stay off by default.

Run directly::

    .venv-agent/bin/python tests/test_app_target_policy.py
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from runner.policy import ConfirmationRequired, Policy, PolicyError, Provenance  # noqa: E402
from runner.rpc import PERMISSION_DENIED, UNTRUSTED_ARG  # noqa: E402

# ops that were previously rejected with -32601 (plus the new close_app)
ALLOWED_USER = [
    ("key", {}),
    ("key", {"chord": "Return"}),
    ("type_text", {"text": "hello"}),
    ("media", {"command": "pause"}),
    ("focus_app", {"app": "steam"}),
    ("ensure_app", {"app": "steam"}),
    ("search", {"query": "cats"}),
    ("scroll", {"direction": "down"}),
    ("click_element", {"description": "submit"}),
    ("click_point", {"x": 1, "y": 2}),
]

# concrete-arg calls that a screen-derived step must never be able to author
SCREEN_CONCRETE = [
    ("key", {"chord": "Return"}),
    ("type_text", {"text": "hello"}),
    ("media", {"command": "pause"}),
    ("focus_app", {"app": "steam"}),
    ("ensure_app", {"app": "steam"}),
    ("search", {"query": "cats"}),
    ("scroll", {"direction": "down"}),
    ("click_element", {"description": "submit"}),
    ("click_point", {"x": 1, "y": 2}),
    ("close_app", {"app": "steam"}),
    ("ensure_url", {"url": "https://example.com"}),
    ("open_url", {"url": "https://example.com"}),
    ("niri", {"command": "move-column-right"}),
    ("launch_app", {"app_id": "firefox"}),
    ("terminal", {"command": "ls"}),
]


class PolicyRegistryTest(unittest.TestCase):
    def setUp(self):
        self.pol = Policy()

    def test_reported_repro_key_is_allowed(self):
        # Before the fix this raised -32601 unknown action op.
        self.pol.validate("key", {}, Provenance.USER)  # must not raise

    def test_advertised_ops_are_registered_and_enabled(self):
        for op, args in ALLOWED_USER:
            with self.subTest(op=op):
                try:
                    self.pol.validate(op, args, Provenance.USER)
                except PolicyError as exc:
                    self.fail(f"{op} rejected for user: {exc.code} {exc.message}")
                except ConfirmationRequired as exc:
                    self.fail(f"{op} unexpectedly needs confirmation: {exc.summary}")

    def test_close_app_needs_confirm(self):
        with self.assertRaises(ConfirmationRequired) as ctx:
            self.pol.validate("close_app", {"app": "steam"}, Provenance.USER)
        self.assertEqual(ctx.exception.op, "close_app")
        # Confirmed calls pass.
        self.pol.validate("close_app", {"app": "steam"}, Provenance.USER, confirmed=True)

    def test_terminal_and_input_stay_off(self):
        for op, args in [("terminal", {"command": "ls"}), ("input", {"text": "hi"})]:
            with self.subTest(op=op):
                # Disabled ops are still untrusted-rejected first when screen.
                with self.assertRaises(PolicyError) as ctx:
                    self.pol.validate(op, args, Provenance.USER)
                self.assertEqual(ctx.exception.code, PERMISSION_DENIED)

    def test_screen_cannot_author_args(self):
        for op, args in SCREEN_CONCRETE:
            with self.subTest(op=op):
                with self.assertRaises(PolicyError) as ctx:
                    self.pol.validate(op, args, Provenance.SCREEN)
                self.assertEqual(ctx.exception.code, UNTRUSTED_ARG,
                                 f"{op} screen arg not rejected -32006")

    def test_screen_selection_only_op_allowed(self):
        # Empty args on an enabled op is a *selection*, not authoring.
        self.pol.validate("key", {}, Provenance.SCREEN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
