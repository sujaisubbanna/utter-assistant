#!/usr/bin/env python3
"""Focused test: ``assistant install-state record/show`` (CSV + merge).

Usage::

    .venv-agent/bin/python tests/m5/test_install_state.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ASSISTANT = [sys.executable, "-m", "assistant"]

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def run(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(ASSISTANT + args, cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=60)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="lav-m5-inst-"))
    env = dict(os.environ)
    env["XDG_STATE_HOME"] = str(tmp)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    install_json = tmp / "utter" / "install.json"

    print("install-state record/show (CSV + merge)")

    # 1) CSV + repeatable flags
    r = run(["install-state", "record",
             "--files", "/a,/b", "--files", "/c",
             "--units", "u1,u2",
             "--packages", "p1", "--packages", "p2,p3",
             "--version", "1.2.3", "--json"], env)
    data = json.loads(r.stdout)
    check("CSV + repeatable --files", data["files"] == ["/a", "/b", "/c"], json.dumps(data["files"]))
    check("CSV + repeatable --units", data["units"] == ["u1", "u2"], json.dumps(data["units"]))
    check("CSV + repeatable --packages", data["packages"] == ["p1", "p2", "p3"],
          json.dumps(data["packages"]))
    check("--version recorded", data["version"] == "1.2.3", str(data.get("version")))

    # 2) a second record merges (does not clobber)
    r = run(["install-state", "record", "--files", "/d", "--units", "u3", "--json"], env)
    data = json.loads(r.stdout)
    check("merge preserves files", data["files"] == ["/a", "/b", "/c", "/d"], json.dumps(data["files"]))
    check("merge preserves units", data["units"] == ["u1", "u2", "u3"], json.dumps(data["units"]))
    check("merge preserves packages", data["packages"] == ["p1", "p2", "p3"],
          json.dumps(data["packages"]))
    check("merge preserves version", data["version"] == "1.2.3", str(data.get("version")))

    # 3) a record with no list args must not wipe the manifest
    r = run(["install-state", "record", "--json"], env)
    data = json.loads(r.stdout)
    check("empty record preserves the manifest",
          data["files"] == ["/a", "/b", "/c", "/d"] and data["units"] == ["u1", "u2", "u3"],
          json.dumps(data))

    # 4) show prints the full manifest
    r = run(["install-state", "show"], env)
    check("show prints the full manifest",
          all(token in r.stdout for token in ("/a", "/d", "u1", "u3", "p1", "p3")),
          r.stdout[:200])
    r = run(["install-state", "show", "--json"], env)
    data = json.loads(r.stdout)
    check("show --json returns the full manifest",
          data["files"] == ["/a", "/b", "/c", "/d"] and data["packages"] == ["p1", "p2", "p3"],
          json.dumps(data))

    # 5) on-disk file matches
    on_disk = json.loads(install_json.read_text())
    check("install.json on disk matches",
          on_disk["files"] == ["/a", "/b", "/c", "/d"] and on_disk["units"] == ["u1", "u2", "u3"],
          json.dumps(on_disk))

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
