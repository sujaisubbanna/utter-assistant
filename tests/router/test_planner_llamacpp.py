#!/usr/bin/env python3
"""``utter.router.planner`` payload + response parsing. Hermetic (no network).

Pins the llama.cpp-compatible contract:

* the ``response_format`` is the **nested** OpenAI wrapper (the top-level form is
  silently ignored by ``llama-server``);
* ``reasoning_content`` is never treated as a plan;
* ``tool_calls`` are parsed robustly (arguments as JSON string or dict).

    .venv-agent/bin/python tests/router/test_planner_llamacpp.py
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from utter.router import planner  # noqa: E402
from utter.types import Context  # noqa: E402


class PayloadTests(unittest.TestCase):
    def test_response_format_is_the_nested_wrapper(self):
        payload = planner._build_payload("qwen3-4b", "open youtube", Context(), {})
        rf = payload["response_format"]
        self.assertEqual(rf["type"], "json_schema")
        self.assertIn("json_schema", rf)
        self.assertIn("schema", rf["json_schema"])
        self.assertEqual(rf["json_schema"]["name"], "desktop_plan")
        # The flat form is the classic bug: {type, json_schema, schema}.
        self.assertNotIn("schema", rf)
        self.assertEqual(payload["messages"][0]["role"], "system")

    def test_payload_is_endpoint_agnostic(self):
        payload = planner._build_payload("qwen3-4b", "play music", Context(), {"firefox": {}})
        self.assertNotIn("tools", payload)  # vLLM and llama.cpp both accept this body
        self.assertEqual(payload["temperature"], 0.0)
        self.assertIn("COMMAND: play music", payload["messages"][1]["content"])


class ToolCallTests(unittest.TestCase):
    def test_tool_calls_with_string_arguments(self):
        message = {"content": None, "tool_calls": [
            {"type": "function", "function": {
                "name": "launch_app", "arguments": '{"app": "firefox"}'}}]}
        plan = planner._plan_from_message(message)
        self.assertIsNotNone(plan)
        assert plan is not None  # for type checkers
        self.assertEqual(plan["steps"][0]["action"], "launch_app")
        self.assertEqual(plan["steps"][0]["args"], {"app": "firefox"})

    def test_tool_calls_with_dict_arguments(self):
        message = {"tool_calls": [
            {"function": {"name": "key", "arguments": {"chord": "ctrl+t"}}}]}
        plan = planner._plan_from_message(message)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["steps"][0], {"action": "key", "args": {"chord": "ctrl+t"}})

    def test_bad_tool_call_is_skipped(self):
        message = {"tool_calls": [{"function": {}}, {"function": {"name": "done"}}]}
        plan = planner._plan_from_message(message)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual([s["action"] for s in plan["steps"]], ["done"])

    def test_empty_tool_calls_fall_through_to_content(self):
        plan = planner._plan_from_message(
            {"tool_calls": [], "content": '{"steps": [{"action": "done"}]}'})
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["steps"][0]["action"], "done")


class ReasoningIgnoredTests(unittest.TestCase):
    def test_reasoning_content_alone_is_not_a_plan(self):
        message = {"reasoning_content": '{"steps": [{"action": "done"}]}', "content": None}
        self.assertIsNone(planner._plan_from_message(message))

    def test_content_wins_over_reasoning_content(self):
        message = {
            "reasoning_content": "thinking out loud…",
            "content": "```json\n{\"steps\": [{\"action\": \"open_url\"}]}\n```",
        }
        plan = planner._plan_from_message(message)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["steps"][0]["action"], "open_url")

    def test_content_parts_are_joined(self):
        message = {"content": [{"type": "text", "text": '{"steps": [{"action": "wait"}]}'}]}
        plan = planner._plan_from_message(message)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["steps"][0]["action"], "wait")

    def test_empty_message_is_none(self):
        self.assertIsNone(planner._plan_from_message({}))
        self.assertIsNone(planner._plan_from_message({"content": "   "}))


if __name__ == "__main__":
    unittest.main()
