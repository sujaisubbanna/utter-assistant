#!/usr/bin/env python3
"""Smoke-test for utter.router.decide (Jev-style constrained choice).

Run with the agent venv (requests present)::

    .venv-agent/bin/python scripts/test_decide.py

Prints, per utterance, the candidate set and the model's probability
distribution / choice / latency, then a summary table and one raw request &
response dump as proof of the guided-choice + logprobs form.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utter.types import Context, FocusedWindow, WindowInfo  # noqa: E402
from utter.router import profiles as profiles_mod  # noqa: E402
from utter.router import decide as decide_mod  # noqa: E402

UTTERANCES = [
    "open youtube",
    "pull up youtube",
    "show me a youtube video",
    "open zen",
    "go to github",
    "search for mechanical keyboards",
    "tile right",
    "focus left",
    "maximize column",
    "play",
    "next track",
    "type hello world",
    "run ls -la",
    "click the sign in button",
    "make the text bigger",
    "banana",
]


def build_context() -> Context:
    """A realistic snapshot: Zen on YouTube focused, plus Orca and foot."""
    focused = FocusedWindow(
        app_id="zen",
        title="YouTube \u2014 Zen Browser",
        pid=1234,
        window_id=101,
        workspace_id=1,
    )
    windows = [
        WindowInfo(id=101, app_id="zen", title="YouTube \u2014 Zen Browser",
                   workspace_id=1, pid=1234, is_focused=True),
        WindowInfo(id=102, app_id="orca", title="utter \u2014 Orca",
                   workspace_id=1, pid=2222),
        WindowInfo(id=103, app_id="foot", title="foot", workspace_id=2, pid=3333),
    ]
    return Context(focused=focused, windows=windows, clipboard="")


def _fmt_top3(dist: dict) -> str:
    if not dist:
        return "-"
    items = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return ", ".join(f"{label}={p:.3f}" for label, p in items)


def _proof(ctx: Context, profiles: dict, utterance: str = "open youtube") -> None:
    """One raw call that mirrors decide's request, dumped as proof."""
    try:
        import requests
    except Exception as exc:  # pragma: no cover
        print(f"[proof] requests unavailable: {exc}")
        return
    cands = decide_mod.build_candidates(utterance, ctx, profiles)
    letters, user = decide_mod._build_prompt(utterance, ctx, cands)
    payload = {
        "model": "qwen3-4b",
        "temperature": 0.0,
        "max_tokens": 1,
        "logprobs": True,
        "top_logprobs": len(cands),
        "structured_outputs": {"choice": letters},
        "messages": [
            {"role": "system", "content": decide_mod._SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    print("\n" + "=" * 78)
    print(f"[proof] POST http://127.0.0.1:8001/v1/chat/completions  ({utterance!r})")
    print("REQUEST PAYLOAD (exact):")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    try:
        r = requests.post("http://127.0.0.1:8001/v1/chat/completions", json=payload, timeout=6)
        print(f"RESPONSE status={r.status_code}")
        print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:2400])
    except Exception as exc:
        print(f"RESPONSE error: {exc}")


def main() -> int:
    profiles = profiles_mod.load()
    ctx = build_context()
    focused = ctx.focused
    assert focused is not None, "test context must have a focused window"
    print(f"loaded {len(profiles)} profiles; focused={focused.app_id!r} "
          f"title={focused.title!r}; windows={[w.app_id for w in ctx.windows]}")

    rows = []
    for utt in UTTERANCES:
        print("\n" + "=" * 78)
        print(f'UTTERANCE: "{utt}"')
        cands = decide_mod.build_candidates(utt, ctx, profiles)
        letters = [chr(ord("A") + i) for i in range(len(cands))]
        print(f"candidates ({len(cands)}):")
        for letter, cand in zip(letters, cands):
            print(f"  {letter}. {cand.op} {json.dumps(cand.args, ensure_ascii=False)}"
                  f"  # {cand.label} [{cand.tier}]")

        t0 = time.perf_counter()
        decision = decide_mod.decide_debug(utt, ctx, profiles)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if decision is None:
            print(f"  -> NO DECISION  latency_ms={latency_ms:.1f}")
            rows.append((utt, len(cands), "NO DECISION", 0.0, "-", latency_ms))
            continue

        print(f"  distribution (top-3): {_fmt_top3(decision.distribution)}")
        print(f"  distribution (full):  "
              f"{json.dumps(decision.distribution, ensure_ascii=False)}")
        print(f"  choice: {decision.raw} {decision.candidate.op} "
              f"{json.dumps(decision.candidate.args, ensure_ascii=False)}"
              f"  # {decision.candidate.label}")
        print(f"  confidence={decision.confidence:.4f}  latency_ms={latency_ms:.1f}")
        rows.append((utt, len(cands), decision.candidate.label, decision.confidence,
                     _fmt_top3(decision.distribution), latency_ms))

    _proof(ctx, profiles)

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("-" * 78)
    print(f"{'utterance':<30} {'#cand':>5}  {'choice':<26} {'conf':>6} {'ms':>8}")
    print("-" * 78)
    for utt, n, label, conf, _top3, ms in rows:
        short = label if len(label) <= 26 else label[:23] + "..."
        print(f"{utt:<30} {n:>5}  {short:<26} {conf:>6.3f} {ms:>8.1f}")
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
