"""Golden-order tests for the deterministic rule engine (``utter.router.rules``).

These pin the *observable* behaviour of ``plan()``: the order in which the
matcher chain claims an utterance and the exact Plan it produces. They are
intentionally behavioural (no references to private matcher functions) so the
same file passes before and after the ordered-chain refactor.

Ordering is what matters here. ``plan()`` walks a fixed chain; the cases below
were chosen so that a reordering changes the result, e.g.::

    custom > niri > media > cli_agent > app_target > terminal > comfy > open
    > site > close > search > shortcut > key > editing > type > scroll > click

Run directly::

    .venv-agent/bin/python tests/router/test_rules_order.py

Note: ``NIRI_MAP`` is extended at import time from ``utter/data/niri_phrases.json``;
the expectations below were captured in that same environment.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from utter.router import rules  # noqa: E402
from utter.router.profiles import AppProfile  # noqa: E402
from utter.types import Context, FocusedWindow  # noqa: E402


FIREFOX = AppProfile(
    id="firefox",
    name="Firefox",
    kind="browser",
    aliases=["browser"],
    shortcuts={"new_tab": "ctrl+t", "close_tab": "ctrl+w", "reload": "F5",
               "address_bar": "ctrl+l"},
    commands={"open youtube": "ctrl+y"},
    search_url="https://duckduckgo.com/?q={q}",
)
FOOT = AppProfile(id="foot", name="Foot", kind="terminal")
CODE = AppProfile(id="code", name="Code", kind="editor", aliases=["vscode"])

PROFILES = {"firefox": FIREFOX, "foot": FOOT, "code": CODE}

_BROWSER = Context(focused=FocusedWindow(app_id="firefox", title="GitHub"))
_TERM = Context(focused=FocusedWindow(app_id="foot", title="~"))
_NONE = Context(focused=None)
_TEXT = Context(focused=FocusedWindow(app_id="code", title="main.py"))


def snapshot(plan):
    """Normalise a Plan to plain data for exact comparison."""
    if plan is None:
        return None
    return {
        "source": plan.source,
        "confidence": plan.confidence,
        "needs_perception": plan.needs_perception,
        "steps": [
            {"action": s.action.value, "args": s.args, "tier": s.tier.value,
             "description": s.description}
            for s in plan.steps
        ],
    }


def step(action, args, tier, description):
    return {"action": action, "args": args, "tier": tier, "description": description}


def plan_of(*steps, source="rules", confidence=1.0, needs=False):
    return {"source": source, "confidence": confidence, "needs_perception": needs,
            "steps": list(steps)}


# (name, utterance, context, expected snapshot)
CASES = [
    # --- custom command beats every built-in matcher (runs first) -----------
    ("custom_beats_open", "Open YouTube!", _BROWSER,
     plan_of(step("key", {"chord": "ctrl+y"}, "keyboard", "custom command: open youtube"))),

    # --- niri beats media / shortcuts --------------------------------------
    ("niri_focus_left", "focus left", _BROWSER,
     plan_of(step("niri", {"command": "focus-column-left", "args": []}, "app", "focus left"))),

    # --- media control ------------------------------------------------------
    ("media_play", "play", _TERM,
     plan_of(step("media", {"command": "play"}, "app", "play"))),

    # --- CLI agent: terminal vs launch -------------------------------------
    ("cli_agent_in_terminal", "open claude code", _TERM,
     plan_of(step("terminal", {"command": "claude"}, "app", "run claude"))),
    ("cli_agent_launch", "open claude code", _NONE,
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "claude"]},
                  "app", "launch claude"))),

    # --- terminal run / clear ----------------------------------------------
    ("terminal_run", "run echo hello", _TERM,
     plan_of(step("terminal", {"command": "echo hello"}, "app", "run echo hello"))),
    ("terminal_run_needs_terminal", "run echo hello", _NONE, None),
    ("terminal_clear", "clear terminal", _TERM,
     plan_of(step("terminal", {"command": "clear"}, "app", "clear"))),
    ("terminal_clear_needs_terminal", "clear terminal", _BROWSER, None),

    # --- ComfyUI ------------------------------------------------------------
    ("comfy_launch", "launch comfyui", _NONE,
     plan_of(step("launch_app",
                  {"app": "foot",
                   "argv": ["foot", "-e",
                            str(pathlib.Path(rules.__file__).resolve().parents[2]
                                / "scripts" / "start-comfyui.sh")]},
                  "app", "start ComfyUI (git pull, deps, start.sh)"))),
    ("comfy_open", "open comfyui", _NONE,
     plan_of(step("ensure_url", {"url": "http://127.0.0.1:8188", "site": "comfyui"},
                  "app", "open ComfyUI"))),

    # --- explicit open: URL / domain / site / app / unknown ----------------
    ("open_url", "open https://example.com/x", _NONE,
     plan_of(step("ensure_url", {"url": "https://example.com/x", "site": "x"},
                  "app", "open https://example.com/x"))),
    ("open_domain", "open example.com/path", _NONE,
     plan_of(step("ensure_url", {"url": "https://example.com/path", "site": "x"},
                  "app", "open example.com/path"))),
    ("open_site", "open youtube", _NONE,
     plan_of(step("ensure_url", {"url": "https://www.youtube.com", "site": "youtube"},
                  "app", "open youtube"))),
    ("open_app", "open firefox", _NONE,
     plan_of(step("ensure_app", {"app": "firefox", "argv": []}, "app", "open Firefox"))),
    # An explicit-but-unknown "open X" claims the utterance and escalates:
    # it must NOT fall through to the scroll matcher.
    ("open_unknown_escalates_without_scroll", "open nonexistentapp", _NONE, None),
    ("open_unknown_scroll_word_still_escalates", "open scroll down", _NONE, None),

    # --- "go to" is claimed by _open, "show" by _site ----------------------
    ("go_to_is_open", "go to github", _NONE,
     plan_of(step("ensure_url", {"url": "https://github.com", "site": "github"},
                  "app", "open github"))),
    ("show_is_site", "show github", _NONE,
     plan_of(step("ensure_url", {"url": "https://github.com", "site": "github"},
                  "app", "switch to github"))),
    ("switch_to_app", "switch to code", _NONE,
     plan_of(step("ensure_app", {"app": "code", "argv": []}, "app", "focus Code"))),

    # --- close app/site: focus then close -----------------------------------
    ("close_site", "close github", _NONE,
     plan_of(step("ensure_url", {"url": "https://github.com", "site": "github"},
                  "app", "focus github"),
             step("niri", {"command": "close-window", "args": []}, "app", "close window"))),

    # --- search: site-specific beats generic -------------------------------
    ("search_site", "search youtube for lofi beats", _NONE,
     plan_of(step("open_url",
                  {"url": "https://www.youtube.com/results?search_query=lofi+beats"},
                  "app", "search youtube for lofi beats"))),
    ("search_browser_template", "search for cats", _BROWSER,
     plan_of(step("open_url", {"url": "https://duckduckgo.com/?q=cats"},
                  "app", "search cats"))),
    ("search_generic", "search for cats", _NONE,
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),

    # --- browser shortcuts (T2) --------------------------------------------
    ("shortcut_new_tab", "new tab", _BROWSER,
     plan_of(step("key", {"chord": "ctrl+t"}, "keyboard", "new_tab in firefox"))),
    ("shortcut_needs_browser", "new tab", _NONE, None),

    # --- generic keys / editing / typing / scroll / click ------------------
    ("key_common", "press enter", _NONE,
     plan_of(step("key", {"chord": "Return"}, "keyboard", "press Return"))),
    ("key_raw", "press f5", _NONE,
     plan_of(step("key", {"chord": "f5"}, "keyboard", "press f5"))),
    ("editing", "copy", _NONE,
     plan_of(step("key", {"chord": "ctrl+c"}, "keyboard", "copy"))),
    ("type_text", "type hello world", _NONE,
     plan_of(step("type_text", {"text": "hello world"}, "app", "type 'hello world'"))),
    ("scroll_down", "scroll down", _NONE,
     plan_of(step("scroll", {"direction": "down", "amount": 5}, "keyboard", "scroll down"))),
    ("scroll_page_up", "page up", _NONE,
     plan_of(step("scroll", {"direction": "up", "amount": 5}, "keyboard", "scroll up"))),
    ("click_needs_perception", "click the submit button", _NONE,
     plan_of(step("click_element", {"description": "the submit button"}, "vision",
                  "click the submit button"), confidence=0.6, needs=True)),

    # --- empty --------------------------------------------------------------
    ("empty", "", _NONE, None),
]


class RulesGoldenOrderTests(unittest.TestCase):
    def test_golden_order(self):
        failures = []
        for name, utterance, ctx, expected in CASES:
            got = snapshot(rules.plan(utterance, ctx, PROFILES))
            if got != expected:
                failures.append(f"{name}: {utterance!r}\n  expected={expected}\n  got={got}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_is_command_like_golden(self):
        for text, expected in [
            ("open youtube", True),
            ("focus left", True),
            ("play", True),
            ("new tab", True),
            ("workspace 3", True),
            ("move window to workspace 2", True),
            ("scroll down", True),
            ("banana", False),
            ("", False),
            ("the quick brown fox", False),
        ]:
            self.assertEqual(rules.is_command_like(text), expected, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
