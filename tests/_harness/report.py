#!/usr/bin/env python3
"""Shared assertion harness for the protocol test suites.

Extracted from ``tests/conformance/run.py``, ``tests/m3/verify_m3.py`` and
``tests/m5/verify_m5.py``, which carried byte-identical copies.
"""
from __future__ import annotations


class Report:
    """Collect PASS/FAIL checks and SKIPs and render them.

    ``skip_label`` is printed before the reason so the conformance suite can
    keep its ``NOT-YET-SUPPORTED:`` prefix while M3/M5 use a bare reason.
    """

    def __init__(self, *, skip_label: str = "") -> None:
        self.checks: list[dict] = []
        self.skips: list[dict] = []
        self._skip_label = skip_label

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        return bool(ok)

    def skip(self, name: str, reason: str) -> None:
        self.skips.append({"name": name, "reason": reason})
        print(f"  [SKIP] {name} — {self._skip_label}{reason}")

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]

    def summary(self) -> dict:
        return {
            "total": len(self.checks),
            "passed": len(self.checks) - len(self.failed),
            "failed": len(self.failed),
            "skipped": len(self.skips),
            "checks": self.checks,
            "skips": self.skips,
        }
