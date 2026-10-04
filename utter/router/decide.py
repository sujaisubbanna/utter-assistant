"""Jev-style constrained decision head.

Instead of free-form planner generation, enumerate a small set of *fully
resolved* candidate actions and let the local tiny LLM **choose** one. The
server's first-token logprobs over the lettered choices yield a calibrated
probability distribution.

Local vLLM is expected at ``cfg.llm_base_url`` (default
``http://127.0.0.1:8001/v1``) serving ``cfg.llm_model`` (default ``qwen3-4b``).
All network use is lazy: importing this module never touches the network.

Candidate construction lives in :mod:`utter.router.decide_candidates` and the
constrained LLM call in :mod:`utter.router.decide_llm`; both are re-exported
here so ``utter.router.decide`` stays the single public entry point.

Public API::

    build_candidates(utterance, ctx, profiles) -> list[Candidate]
    decide(utterance, ctx, profiles, cfg=None) -> Decision | None
    decide_debug(utterance, ctx, profiles, cfg=None) -> Decision | None
"""
from __future__ import annotations

from ..types import Context
from .decide_candidates import Candidate, Decision, build_candidates
from .decide_llm import _SYSTEM, _build_prompt, _query  # noqa: F401  (kept for scripts/test_decide.py)


def _should_skip(candidates: list[Candidate]) -> bool:
    return not any(c.op != "none" for c in candidates)


def decide(utterance: str, ctx: Context, profiles: dict, cfg=None):
    """Return the model's chosen action, or None when it fails/abstains.

    Fails open (returns None) on any server/parse error so the caller can fall
    back to rules. If ``cfg.decide_threshold`` is set, a choice below it is
    treated as an abstention *by this function only*; use :func:`decide_debug`
    to always see the raw decision.
    """
    if cfg is not None and not getattr(cfg, "decision_head_enabled", True):
        return None
    candidates = build_candidates(utterance, ctx, profiles)
    if _should_skip(candidates):
        return None
    decision = _query(utterance, ctx, candidates, cfg)
    if decision is None:
        return None
    threshold = getattr(cfg, "decide_threshold", None) if cfg is not None else None
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = None
        if threshold is not None and decision.confidence < threshold:
            return None
    return decision


def decide_debug(utterance: str, ctx: Context, profiles: dict, cfg=None):
    """Like :func:`decide` but never applies ``cfg.decide_threshold``."""
    candidates = build_candidates(utterance, ctx, profiles)
    if _should_skip(candidates):
        return None
    return _query(utterance, ctx, candidates, cfg)


__all__ = [
    "Candidate",
    "Decision",
    "build_candidates",
    "decide",
    "decide_debug",
]
