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

    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"CONTEXT:\n{_ctx_summary(ctx, profiles)}\n\nCOMMAND: {utterance}"},
        ],
    }
    try:
        r = requests.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, timeout=8)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None

    data = _parse_json(content)
    if not data or not data.get("steps"):
        return None

    steps: list[Step] = []
    for raw in data["steps"]:
        try:
            action = Action(raw["action"])
        except Exception:
            continue
        tier_raw = raw.get("tier", "app")
        try:
            tier = Tier(tier_raw)
        except Exception:
            tier = Tier.VISION if action in (Action.CLICK_ELEMENT, Action.CLICK_POINT) else Tier.APP
        needs = action in (Action.CLICK_ELEMENT, Action.CLICK_POINT)
        steps.append(Step(action, dict(raw.get("args", {})), tier=tier,
                          description=raw.get("description", ""), confirm=False))
    if not steps:
        return None
    return Plan(utterance=utterance, steps=steps, source="llm",
                confidence=float(data.get("confidence", 0.5)),
                needs_perception=any(s.action in (Action.CLICK_ELEMENT, Action.CLICK_POINT) for s in steps))
