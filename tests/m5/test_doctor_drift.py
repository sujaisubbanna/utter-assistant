#!/usr/bin/env python3
"""Focused test: ``doctor`` version drift compares like for like (hermetic).

Covers the regression where ``runner.__version__`` was a hardcoded ``0.1.0``
while the installer recorded the release version (``0.4.1``), so every healthy
install reported version drift.

No socket: ``_drift`` is fed a fake ``runner_info`` and ``install_state.load``
is patched. Also guards that the runner version stays single-sourced from
``pyproject.toml`` instead of a constant.

Usage::

    .venv-agent/bin/python tests/m5/test_doctor_drift.py
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from assistant import __version__ as assistant_version  # noqa: E402
from assistant import doctor, install_state  # noqa: E402
from runner import __version__ as runner_version  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _drift_with(recorded: dict, runner_info: dict) -> list[dict]:
    original = install_state.load
    install_state.load = lambda: dict(install_state.DEFAULT, **recorded)  # type: ignore[assignment]
    try:
        return doctor._drift(runner_info)
    finally:
        install_state.load = original  # type: ignore[assignment]


def main() -> int:
    project_version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    healthy = {"protocol": doctor.RUNNER_PROTOCOL, "abi": doctor.RUNNER_ABI,
               "version": runner_version}

    print("doctor version drift (hermetic)")

    # 1) single source of truth: package, CLI and pyproject agree.
    check("runner version matches assistant version",
          runner_version == assistant_version,
          f"runner={runner_version!r} assistant={assistant_version!r}")
    check("runner version matches pyproject",
          runner_version == project_version,
          f"runner={runner_version!r} pyproject={project_version!r}")
    check("doctor sees the same runner version",
          doctor._runner_version() == runner_version,
          f"doctor={doctor._runner_version()!r} runner={runner_version!r}")

    # 2) healthy install: recorded release == actual runner version -> no drift.
    drift = _drift_with({"version": project_version, "protocol": doctor.RUNNER_PROTOCOL}, healthy)
    check("healthy install reports no drift", drift == [], repr(drift))

    # 3) a genuine version mismatch is still reported.
    drift = _drift_with({"version": "0.3.0", "protocol": doctor.RUNNER_PROTOCOL}, healthy)
    check("version mismatch is reported",
          drift == [{"kind": "version", "recorded": "0.3.0", "actual": runner_version}],
          repr(drift))

    # 4) a protocol mismatch is still reported.
    drift = _drift_with({"version": project_version, "protocol": "0.9"}, healthy)
    check("protocol mismatch is reported",
          drift == [{"kind": "protocol", "recorded": "0.9",
                     "actual": doctor.RUNNER_PROTOCOL}],
          repr(drift))

    # 5) a legacy manifest without a recorded version is not flagged.
    drift = _drift_with({"version": "", "protocol": doctor.RUNNER_PROTOCOL}, healthy)
    check("unset recorded version reports no drift", drift == [], repr(drift))

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())