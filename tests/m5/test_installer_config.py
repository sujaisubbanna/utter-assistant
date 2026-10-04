#!/usr/bin/env python3
"""Regression: the installer's config step actually writes config.toml.

Two installer bugs are covered:

* **config not written** — ``run_f``/``run`` shifted their arguments wrongly, so
  ``exec_config`` executed the destination path as a command, never ran
  ``mkdir``/``cp``, yet still printed ``ok Config`` and exited 0.
* **checksum ``./`` prefix** — release balances carry ``./<asset>`` names; the
  ``verify()`` awk must strip the prefix (and binary-mode ``*``) to match.

The test is hermetic: it runs the real ``install.sh`` against a throwaway
``PREFIX``/``XDG_*`` tree and a fake core tree, so it never touches ``~/.config``
or the network. A failed step must exit non-zero and must not report ``ok``;
``--dry-run`` must stay non-mutating and exit 0.

Usage::

    .venv-agent/bin/python tests/m5/test_installer_config.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))  # tests/ for _harness

from _harness.report import Report  # noqa: E402

INSTALL = REPO / "install.sh"
DEFAULT_TOML = REPO / "config.default.toml"


def _pinned_version() -> str:
    """A concrete tag from pyproject.toml.

    ``install.sh`` otherwise calls the GitHub releases API to resolve ``latest``;
    pinning keeps these tests hermetic (no network, no rate-limit flakes).
    """
    import re
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return "v" + (match.group(1) if match else "0.0.0")


def _sandbox_env(tmp: Path) -> dict:
    """A minimal hermetic environment rooted entirely inside ``tmp``."""
    env = dict(os.environ)
    env.update({
        "PREFIX": str(tmp / "prefix"),
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "XDG_DATA_HOME": str(tmp / "data"),
        "XDG_STATE_HOME": str(tmp / "state"),
        "XDG_CACHE_HOME": str(tmp / "cache"),
        "UTTER_UI": "plain",
        "UTTER_VERSION": _pinned_version(),
        "NO_COLOR": "1",
        "COLUMNS": "100",
    })
    return env


def _fake_core(tmp: Path) -> None:
    """$SHARE_DIR/config.default.toml inside a tree with an ``assistant`` dir.

    ``ensure_core_context`` prefers ``$SHARE_DIR`` when ``$SHARE_DIR/assistant``
    exists; providing it keeps the run offline (no core tarball download).
    """
    share = tmp / "prefix" / "share" / "utter"
    (share / "assistant").mkdir(parents=True, exist_ok=True)
    (share / "config.default.toml").write_bytes(DEFAULT_TOML.read_bytes())


def _run_installer(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL), *args],
        cwd=str(REPO), env=_sandbox_env(tmp),
        capture_output=True, text=True, timeout=180,
    )


def _awk_matcher(asset: str, sums: Path) -> str:
    """Run install.sh's ``verify()`` awk against ``sums``.

    The exact program is copied from ``verify()`` — and a guard below asserts
    the script still contains the ``./``/``*`` stripping so this test would
    catch a regression in either the program or the call site.
    """
    prog = (
        '{ n=$2; sub(/^\\*/, "", n); sub(/^\\.\\//, "", n); '
        'if (n == a) { print $1; exit } }'
    )
    r = subprocess.run(
        ["awk", "-v", f"a={asset}", prog, str(sums)],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def main() -> int:
    rep = Report()
    print("installer config-step regression (config.toml + checksum prefix)")

    # 1) a successful config step writes config.toml from the default --------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-config-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        r = _run_installer(tmp, "--only", "config", "--yes")
        config = tmp / "config" / "utter" / "config.toml"
        rep.check("config step exits 0", r.returncode == 0,
                  (r.stderr or r.stdout)[-300:])
        rep.check("config.toml is created", config.is_file(), str(config))
        if config.is_file():
            got = config.read_text(encoding="utf-8")
            want = DEFAULT_TOML.read_text(encoding="utf-8")
            rep.check("config.toml matches the shipped default",
                      got == want, f"{len(got)} vs {len(want)} bytes")
            rep.check("config.toml has content", len(got) > 100, f"{len(got)} bytes")
        rep.check("success is reported (ok Config)",
                  "ok Config" in r.stdout, r.stdout[-200:])
        rep.check("no shell 'No such file or directory' leak",
                  "No such file or directory" not in r.stderr
                  and "No such file or directory" not in r.stdout,
                  (r.stderr + r.stdout)[-200:])

    # 2) a failing step must fail loudly, not print ok ----------------------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-configfail-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        # Make the config dir's parent a *file* so `mkdir -p` cannot succeed.
        blocker = tmp / "blocker"
        blocker.write_text("not a directory\n")
        env = _sandbox_env(tmp)
        env["XDG_CONFIG_HOME"] = str(blocker)
        r = subprocess.run(
            ["bash", str(INSTALL), "--only", "config", "--yes"],
            cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180,
        )
        out = r.stdout + r.stderr
        rep.check("a failed step exits non-zero", r.returncode != 0,
                  f"rc={r.returncode}")
        rep.check("a failed step reports a failure line",
                  "[fail]" in out or "ERROR" in out, out[-300:])
        rep.check("a failed step does NOT report ok",
                  "ok Config" not in r.stdout, r.stdout[-200:])

    # 3) --dry-run stays non-mutating and exits 0 ---------------------------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-dry-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        r = _run_installer(tmp, "--only", "config", "--yes", "--dry-run")
        config = tmp / "config" / "utter" / "config.toml"
        rep.check("dry-run exits 0", r.returncode == 0,
                  (r.stderr or r.stdout)[-300:])
        rep.check("dry-run writes nothing", not config.exists(), str(config))
        rep.check("dry-run prints the planned mkdir",
                  "mkdir -p" in r.stdout, r.stdout[-300:])
        rep.check("dry-run prints the planned cp",
                  "cp " in r.stdout and "config.toml" in r.stdout, r.stdout[-300:])

    # 4) checksum parsing tolerates a './' prefix (Bug A) -------------------- #
    # Guard: the installed script really does strip the prefix.
    script = INSTALL.read_text(encoding="utf-8")
    rep.check("verify() strips the './' prefix",
              'sub(/^\\.\\//, "", n)' in script,
              "verify() no longer strips ./ from checksum names")
    with tempfile.TemporaryDirectory(prefix="lav-inst-sums-") as d:
        sums = Path(d) / "sha256sums.txt"
        digest = "a" * 64
        sums.write_text(
            f"{digest}  ./utter-core-0.4.0.tar.gz\n"
            f"{'b' * 64}  ./utter-gui_0.4.0_amd64.AppImage\n"
            f"{'c' * 64} *./utter-gui-0.4.0-1.x86_64.rpm\n",
            encoding="utf-8",
        )
        rep.check("'./' prefix matches (core tarball)",
                  _awk_matcher("utter-core-0.4.0.tar.gz", sums) == digest)
        rep.check("'./' prefix matches (AppImage)",
                  _awk_matcher("utter-gui_0.4.0_amd64.AppImage", sums) == "b" * 64)
        rep.check("binary-mode '*./' prefix matches (rpm)",
                  _awk_matcher("utter-gui-0.4.0-1.x86_64.rpm", sums) == "c" * 64)
        rep.check("an unlisted asset yields nothing",
                  _awk_matcher("not-in-sums.tar.gz", sums) == "")

    summary = rep.summary()
    print(f"\n=== {summary['passed']}/{summary['total']} checks passed, "
          f"{summary['skipped']} skipped ===")
    if rep.failed:
        print("FAILED:")
        for c in rep.failed:
            print(f"  - {c['name']}: {c['detail']}")
        return 1
    print("M5 INSTALLER CONFIG: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
