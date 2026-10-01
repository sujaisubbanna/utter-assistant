"""LLM I/O for the Jev-style constrained decision head.

Builds the lettered prompt, performs the constrained (guided-choice) request and
parses the first-token logprobs into a calibrated :class:`Decision`. All network
use is lazy: importing this module never touches the network.

Public API (re-exported from :mod:`utter.router.decide`)::

    _query(utterance, ctx, candidates, cfg=None) -> Decision | None
"""
from __future__ import annotations

import json
import math
import re
from typing import Optional

from ..types import Context
from .decide_candidates import Candidate, Decision

_DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL = "qwen3-4b"
_TIMEOUT = 6.0

_SYSTEM = (
    "You route spoken desktop commands. Output ONLY one letter. A candidate "
    "is actionable ONLY if the utterance explicitly issues a command. A search "
    "action requires the user to say search, google, or look up. For a lone "
    "noun like \"banana\" or a vague phrase, the answer is none."
)


def _ctx_summary(ctx: Context) -> str:
    lines: list[str] = []
    focused = getattr(ctx, "focused", None) if ctx is not None else None
    if focused is not None:
        lines.append(f"Focused: {focused.app_id} \u2014 {focused.title!r}")
    else:
        lines.append("Focused: (none)")
    wins = getattr(ctx, "windows", None) or []
    if wins:
        lines.append("Windows: " + "; ".join(f"{w.app_id}:{w.title!r}" for w in wins[:8]))
    return "\n".join(lines)


def _build_prompt(utterance: str, ctx: Context, candidates: list[Candidate]) -> tuple[list[str], str]:
    letters = [chr(ord("A") + i) for i in range(len(candidates))]
    rows = [f"{letter}. {c.op} {json.dumps(c.args, ensure_ascii=False)}  # {c.label}"
            for letter, c in zip(letters, candidates)]
    user = (
        f"Utterance: {utterance!r}\n"
        f"{_ctx_summary(ctx)}\n"
        "Candidates:\n"
        + "\n".join(rows)
        + "\nAnswer with the single best letter."
    )
    return letters, user


def _parse_decision(data: dict, candidates: list[Candidate], letters: list[str],
                    strict: bool) -> Optional[Decision]:
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        return None
    content = ((choice.get("message") or {}).get("content") or "").strip()
    logprobs = choice.get("logprobs") or {}
    entries = logprobs.get("content") or []

    dist: dict[str, float] = {}
    token = ""
    if entries:
        first = entries[0] or {}
        token = (first.get("token") or "").strip().upper()
        for entry in first.get("top_logprobs") or []:
            tok = (entry.get("token") or "").strip().upper()
            if tok in letters:
                try:
                    dist[tok] = math.exp(float(entry.get("logprob", -9999.0)))
                except (TypeError, ValueError):
                    pass
        if token in letters and token not in dist:
            try:
                dist[token] = math.exp(float(first.get("logprob", -9999.0)))
            except (TypeError, ValueError):
                pass

    chosen = ""
    if content and content[:1].upper() in letters and len(content.strip()) <= 2:
        chosen = content[:1].upper()
    if chosen not in letters and token in letters:
        chosen = token
    if chosen not in letters:
        if strict:
            return None
        m = re.search(r"[A-N]", content.upper())
        if not m or m.group(0) not in letters:
            return None
        chosen = m.group(0)

    # Plain request with no logprobs: a degenerate but honest distribution.
    if not dist:
        if strict:
            return None
        dist = {chosen: 1.0}

    total = sum(dist.values())
    if total <= 0:
        dist = {chosen: 1.0}
        total = 1.0
    dist = {k: v / total for k, v in dist.items()}
    if chosen not in dist and dist:
        chosen = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[0][0]

    distribution = {
        candidates[letters.index(k)].label: round(v, 6)
        for k, v in sorted(dist.items(), key=lambda kv: kv[1], reverse=True)
        if k in letters
    }
    confidence = float(dist.get(chosen, 0.0))
    return Decision(
        candidate=candidates[letters.index(chosen)],
        confidence=confidence,
        distribution=distribution,
        source="decide",
        raw=chosen,
    )


def _query(utterance: str, ctx: Context, candidates: list[Candidate],
           cfg=None) -> Optional[Decision]:
    from utter import runtime
    resolved_cfg = runtime.resolve_router(cfg)
    base_url = getattr(resolved_cfg, "llm_base_url", None) or _DEFAULT_BASE_URL
    model = getattr(resolved_cfg, "llm_model", None) or _DEFAULT_MODEL
    try:
        import requests  # lazy: module import must work offline
    except Exception:
        return None

    letters, user = _build_prompt(utterance, ctx, candidates)
    if not letters:
        return None

    common = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 1,
        "logprobs": True,
        "top_logprobs": len(candidates),
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    # (extra body, strict parse). vLLM >=0.6 accepts `structured_outputs.choice`;
    # older builds accept the legacy `guided_choice`; last resort is a plain call.
    attempts = [
        ({"structured_outputs": {"choice": letters}}, True),
        ({"guided_choice": letters}, True),
        ({}, False),
    ]
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    for extra, strict in attempts:
        payload = dict(common)
        payload.update(extra)
        try:
            resp = requests.post(endpoint, json=payload, timeout=_TIMEOUT)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        decision = _parse_decision(data, candidates, letters, strict)
        if decision is not None:
            return decision
    return None
