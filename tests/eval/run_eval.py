#!/usr/bin/env python3
"""Router / plan-accuracy evaluation runner.

Scores the deterministic rule engine (``utter.router.rules.plan``) against the
hand-curated corpus in :mod:`tests.eval.corpus` and prints overall + per-category
accuracy. Deterministic and hermetic: fixed profiles, fixed contexts, no desktop,
no network, no user config.

Usage::

    .venv-agent/bin/python tests/eval/run_eval.py
    .venv-agent/bin/python tests/eval/run_eval.py --verbose
    .venv-agent/bin/python tests/eval/run_eval.py --json
    .venv-agent/bin/python tests/eval/run_eval.py --threshold 0.98

Exit code is 0 when overall accuracy is at least ``--threshold`` (default 1.0,
i.e. the corpus must be fully green), else 1. Cases listed in
``corpus.KNOWN_GAPS`` are reported separately and excluded from the threshold;
their expected value records the *intended* behaviour, so a gap that starts
passing is flagged as stale.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import corpus  # noqa: E402  (tests/eval/corpus.py)
from utter.router import rules  # noqa: E402


def evaluate(cases):
    """Return a list of result dicts for ``(name, category, utterance, ctx, expected)``."""
    results = []
    for name, category, utterance, ctx_key, expected in cases:
        ctx = corpus.CONTEXTS[ctx_key]
        got = corpus.snapshot(rules.plan(utterance, ctx, corpus.PROFILES))
        results.append({
            "name": name,
            "category": category,
            "utterance": utterance,
            "context": ctx_key,
            "expected": expected,
            "got": got,
            "ok": got == expected,
        })
    return results


def summarise(results):
    """Aggregate results into overall + per-category counts."""
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    categories: dict[str, dict] = {}
    for r in results:
        cat = categories.setdefault(r["category"], {"passed": 0, "total": 0})
        cat["total"] += 1
        if r["ok"]:
            cat["passed"] += 1
    return {"total": total, "passed": passed,
            "accuracy": (passed / total) if total else 0.0,
            "categories": {k: categories[k] for k in sorted(categories)}}


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score router plans against the eval corpus.")
    parser.add_argument("--json", action="store_true",
                        help="print a machine-readable summary instead of the table")
    parser.add_argument("--verbose", action="store_true",
                        help="list every scored failure with expected vs got")
    parser.add_argument("--threshold", type=float, default=1.0,
                        help="minimum overall accuracy to pass (default: 1.0)")
    args = parser.parse_args(argv)

    gaps = corpus.gap_cases()
    scored = evaluate(corpus.CASES)
    gap_results = evaluate(gaps)

    summary = summarise(scored)
    threshold_ok = summary["total"] > 0 and summary["accuracy"] >= args.threshold

    stale_gaps = [r["name"] for r in gap_results if r["ok"]]
    failures = [r for r in scored if not r["ok"]]

    if args.json:
        payload = {
            "total": summary["total"],
            "passed": summary["passed"],
            "accuracy": round(summary["accuracy"], 6),
            "threshold": args.threshold,
            "passed_threshold": threshold_ok,
            "categories": {
                cat: {**counts, "accuracy": round(counts["passed"] / counts["total"], 6)}
                for cat, counts in summary["categories"].items()
            },
            "failures": [
                {"name": f["name"], "category": f["category"], "utterance": f["utterance"],
                 "expected": f["expected"], "got": f["got"]}
                for f in failures
            ],
            "known_gaps": [
                {"name": g["name"], "utterance": g["utterance"],
                 "expected": g["expected"], "got": g["got"], "ok": g["ok"]}
                for g in gap_results
            ],
            "stale_known_gaps": stale_gaps,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if threshold_ok else 1

    print("Router plan-accuracy eval")
    print(f"  scored cases: {summary['passed']}/{summary['total']}"
          f" ({len(gap_results)} known gap{'s' if len(gap_results) != 1 else ''}, "
          f"excluded)")
    print(f"  accuracy:     {_pct(summary['accuracy'])}  "
          f"(threshold {_pct(args.threshold)})")
    print()
    print(f"  {'category':<22} {'pass/total':>10}   {'%':>6}")
    print(f"  {'-' * 22} {'-' * 10}   {'-' * 6}")
    for cat, counts in summary["categories"].items():
        pct = counts["passed"] / counts["total"] if counts["total"] else 0.0
        print(f"  {cat:<22} {counts['passed']:>4}/{counts['total']:<5}   {_pct(pct):>6}")

    if failures:
        print()
        print("  failures:")
        for f in failures:
            print(f"    [{f['category']}] {f['name']}: {f['utterance']!r}")
            if args.verbose:
                print(f"      expected={f['expected']}")
                print(f"      got     ={f['got']}")

    if gap_results:
        print()
        print("  known gaps (excluded from threshold):")
        for g in gap_results:
            state = "STALE (now passes)" if g["ok"] else "gap"
            print(f"    {g['name']}: {corpus.KNOWN_GAPS.get(g['name'], '')} [{state}]")

    print()
    print(f"  RESULT: {'PASS' if threshold_ok else 'FAIL'}")
    return 0 if threshold_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
