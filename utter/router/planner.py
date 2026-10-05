"""Tiny-LLM fallback planner.

Only invoked when the deterministic rules cannot resolve an utterance. Talks to
a local OpenAI-compatible endpoint (vLLM/SGLang/llama.cpp) and asks for a strict
JSON plan over the same action vocabulary. Degrades to None if unavailable.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..types import Action, Context, Plan, Step, Tier

_SYSTEM = """You are a desktop command planner. Convert the user's spoken command into
a minimal JSON plan using ONLY these actions:

- open_url        {"url": str, "new_tab": bool}
- launch_app      {"app": str}
- focus_app       {"app": str}
- key             {"chord": str}            e.g. "ctrl+t", "Return"
- type_text       {"text": str}
- click_element   {"description": str}      find a control by visible text/description
- click_point     {"x": int, "y": int}
- scroll          {"direction": "up"|"down", "amount": int}
- wait            {"ms": int}
- done            {}

Prefer app/context actions over clicking. Only use click_element/click_point when
there is no direct action. Respond with ONLY a JSON object:

{"steps":[{"action":"...","args":{...},"tier":"app|a11y|keyboard|vision"}],"confidence":0.0-1.0}
"""

#: JSON schema for the strict plan. Sent through the OpenAI-compatible nested
#: ``response_format`` wrapper below; the top-level form is silently ignored by
#: llama.cpp's ``llama-server`` (and older vLLM), so it must stay nested.
_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "args": {"type": "object"},
                    "tier": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["action"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["steps"],
}

#: OpenAI nested wrapper. Do NOT flatten this to {type, json_schema, schema}.
_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "desktop_plan", "schema": _PLAN_SCHEMA},
}


def _build_payload(model: str, utterance: str, ctx: Context, profiles: dict) -> dict:
    """The chat-completions body, including the nested ``response_format``.

    Pure so it can be pinned by tests without touching the network.
    """
    return {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"CONTEXT:\n{_ctx_summary(ctx, profiles)}\n\nCOMMAND: {utterance}"},
        ],
        "response_format": _RESPONSE_FORMAT,
    }


def _coerce_args(value) -> dict:
    """Function/tool arguments, which may arrive as a JSON string or a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _steps_from_tool_calls(tool_calls) -> list[dict]:
    """Normalise OpenAI ``tool_calls`` into plan step dicts."""
    steps: list[dict] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        fn_value = call.get("function")
        fn: dict = fn_value if isinstance(fn_value, dict) else {}
        name = fn.get("name") or call.get("name")
        if not name:
            continue
        steps.append({"action": name, "args": _coerce_args(fn.get("arguments"))})
    return steps


def _plan_from_message(message: dict) -> Optional[dict]:
    """Extract a raw plan from an assistant message.

    Prefers OpenAI ``tool_calls``; otherwise parses ``content`` as JSON. The
    ``reasoning_content`` field is deliberately ignored — Qwen3 thinking output
    is not a plan.
    """
    if not isinstance(message, dict):
        return None
    tool_steps = _steps_from_tool_calls(message.get("tool_calls"))
    if tool_steps:
        return {"steps": tool_steps}

    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        return None
    return _parse_json(content)


def _ctx_summary(ctx: Context, profiles: dict) -> str:
    lines = []
    if ctx.focused:
        lines.append(f"focused_app_id: {ctx.focused.app_id}")
        lines.append(f"focused_window_title: {ctx.focused.title!r}")
    else:
        lines.append("focused_app_id: (none)")
    lines.append("installed_apps: " + ", ".join(sorted(profiles.keys())[:120]))
    if ctx.clipboard:
        lines.append(f"clipboard_snippet: {ctx.clipboard[:200]!r}")
    return "\n".join(lines)


def _parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def plan(utterance: str, ctx: Context, profiles: dict, cfg=None) -> Optional[Plan]:
    from utter import runtime
    resolved_cfg = runtime.resolve_router(cfg)
    if resolved_cfg is not None and not getattr(resolved_cfg, "llm_fallback", True):
        return None
    base_url = getattr(resolved_cfg, "llm_base_url", "http://127.0.0.1:8001/v1")
    model = getattr(resolved_cfg, "llm_model", "Qwen3-4B-Instruct")
    try:
        import requests
    except Exception:
        return None

    payload = _build_payload(model, utterance, ctx, profiles)
    try:
        r = requests.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, timeout=8)
        r.raise_for_status()
        message = r.json()["choices"][0]["message"]
    except Exception:
        return None

    data = _plan_from_message(message)
    if not data or not data.get("steps"):
        return None

    steps: list[Step] = []
    for raw in data["steps"]:
        if not isinstance(raw, dict):
            continue
        try:
            action = Action(raw["action"])
        except Exception:
            continue
        tier_raw = raw.get("tier", "app")
        try:
            tier = Tier(tier_raw)
        except Exception:
            tier = Tier.VISION if action in (Action.CLICK_ELEMENT, Action.CLICK_POINT) else Tier.APP
        steps.append(Step(action, _coerce_args(raw.get("args")), tier=tier,
                          description=raw.get("description", ""), confirm=False))
    if not steps:
        return None
    return Plan(utterance=utterance, steps=steps, source="llm",
                confidence=float(data.get("confidence", 0.5)),
                needs_perception=any(s.action in (Action.CLICK_ELEMENT, Action.CLICK_POINT) for s in steps))
