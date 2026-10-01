#!/usr/bin/env python3
"""Regression: CLI-agent names must not be shadowed by generated keyword aliases.

Reproduced bug: ChatGPT's generated profile carries the desktop-entry keyword
alias ``codex`` (``aliases=['chatgpt','chat gpt','gpt','openai','codex']``), so
``resolve("codex")`` returned ChatGPT and ``"codex type ok"`` targeted
``chatgpt`` instead of the ``codex`` CLI agent.

Fix (two layers):
* generated-catalogue keyword aliases may not shadow a CLI-agent name;
  an explicit profile id/name (or a hand-curated alias) still wins;
* ``gen_app_catalog.build_generated`` no longer emits CLI-agent names as
  keyword aliases at all.

Run directly::

    .venv-agent/bin/python tests/router/test_profile_resolution.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utter.router import profiles as profiles_mod  # noqa: E402
from utter.router import rules  # noqa: E402
from utter.router.profiles import AppProfile  # noqa: E402
from utter.types import Context  # noqa: E402

NONE = Context(focused=None)

CHATGPT = AppProfile(
    id="chatgpt", name="ChatGPT",
    aliases=["chatgpt", "chat gpt", "gpt", "openai", "codex"],
    generated=True,
)


class CliAgentResolutionTest(unittest.TestCase):
    def test_generated_alias_does_not_shadow_cli_agent(self):
        profs = {"chatgpt": CHATGPT}
        self.assertIsNone(profiles_mod.resolve("codex", profs))
        # A non-reserved generated alias still resolves.
        self.assertEqual(profiles_mod.resolve("chatgpt", profs).id, "chatgpt")

    def test_curated_alias_still_outranks(self):
        curated = AppProfile(id="mycodex", name="My Codex", aliases=["codex"], generated=False)
        profs = {"mycodex": curated, "chatgpt": CHATGPT}
        resolved = profiles_mod.resolve("codex", profs)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, "mycodex")

    def test_explicit_id_or_name_wins(self):
        codex = AppProfile(id="codex", name="Codex", generated=True)
        profs = {"codex": codex, "chatgpt": CHATGPT}
        self.assertEqual(profiles_mod.resolve("codex", profs).id, "codex")

    def test_load_marks_generated_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            curated = root / "curated"
            curated.mkdir()
            (curated / "_defaults.yaml").write_text("defaults: {}\n")
            gen = root / "generated.yaml"
            gen.write_text(
                "profiles:\n"
                "  chatgpt.desktop:\n"
                "    id: chatgpt.desktop\n"
                "    name: ChatGPT\n"
                "    aliases: [chatgpt, chat gpt, gpt, openai, codex]\n"
                "    launch: [chatgpt]\n"
                "    kind: other\n"
            )
            profs = profiles_mod.load(curated, generated_path=gen)
            self.assertTrue(profs["chatgpt.desktop"].generated)
            self.assertIsNone(profiles_mod.resolve("codex", profs))

    def test_router_maps_codex_to_cli_agent(self):
        profs = {"chatgpt": CHATGPT}
        plan = rules.plan("codex type ok", NONE, profs)
        self.assertIsNotNone(plan, "codex target was not claimed")
        self.assertEqual(plan.steps[0].action.value, "type_text")
        self.assertEqual(plan.steps[0].args, {"text": "ok", "app": "codex"})

    def test_router_still_maps_chatgpt(self):
        profs = {"chatgpt": CHATGPT}
        plan = rules.plan("chatgpt type ok", NONE, profs)
        self.assertEqual(plan.steps[0].args, {"text": "ok", "app": "chatgpt"})

    def test_router_cli_agent_does_not_break_real_profile(self):
        # If a real GUI profile owns the name by id, it still wins.
        codex = AppProfile(id="codex", name="Codex", generated=True)
        profs = {"codex": codex, "chatgpt": CHATGPT}
        plan = rules.plan("codex type ok", NONE, profs)
        self.assertEqual(plan.steps[0].args["app"], "codex")


def _load_generator():
    path = ROOT / "scripts" / "gen_app_catalog.py"
    spec = importlib.util.spec_from_file_location("gen_app_catalog_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GeneratorAliasTest(unittest.TestCase):
    def test_cli_agent_keyword_not_emitted_as_alias(self):
        mod = _load_generator()
        catalog = {
            "chatgpt.desktop": {
                "name": "ChatGPT",
                "keywords": ["codex", "gpt", "openai"],
                "exec": ["chatgpt"],
                "terminal": False,
                "wm_class": "ChatGPT",
                "mime_types": [],
                "kind": "other",
            }
        }
        profiles = mod.build_generated(catalog)["profiles"]
        aliases = profiles["chatgpt.desktop"]["aliases"]
        self.assertNotIn("codex", aliases)
        self.assertIn("gpt", aliases)  # non-reserved keyword is kept


if __name__ == "__main__":
    unittest.main(verbosity=2)
