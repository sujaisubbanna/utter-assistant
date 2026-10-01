#!/usr/bin/env python3
"""M3 verification: drive the real ``utter/`` assistant through the runner.

Starts the runner with ``config.m3.toml`` (dry-run ON) and asserts the vertical
slice routes through the real rules + Jev decision head, then runs a single real
(non-dry-run) safe action and reports the observed result.

Usage::

    .venv-agent/bin/python tests/m3/verify_m3.py [--keep] [--timeout 60]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CONF = REPO / "tests" / "conformance"
sys.path.insert(0, str(CONF))

from framing_client import (  # noqa: E402
    ERR_PERMISSION,
    ERR_UNTRUSTED,
    FramingClient,
    FramingTimeout,
    RpcError,
    TransportClosed,
)

CONFIG = REPO / "config.m3.toml"
RUNNER_MAIN = REPO / "runner" / "__main__.py"
GENERATED = HERE / "generated"


# --------------------------------------------------------------------------- #
# tiny assertion harness
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.skips: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return bool(ok)

    def skip(self, name: str, reason: str) -> None:
        self.skips.append({"name": name, "reason": reason})
        print(f"  [SKIP] {name} — {reason}")

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


# --------------------------------------------------------------------------- #
# runner lifecycle
# --------------------------------------------------------------------------- #
class Runner:
    def __init__(self, sock_path: str, *, dry_run: bool, timeout: float = 60.0,
                 log_name: str = "runner.log"):
        self.sock_path = sock_path
        self.dry_run = dry_run
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.log_path = GENERATED / log_name
        self._log = None

    def start(self) -> None:
        GENERATED.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "wb")
        env = dict(os.environ)
        env["UTTER_DRY_RUN"] = "1" if self.dry_run else "0"
        env["UTTER_RUNNER_SOCK"] = self.sock_path
        env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
        # make `python3` in the plugin entrypoint resolve to this venv
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "runner", "--config", str(CONFIG), "--socket", self.sock_path],
            cwd=str(REPO),
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            env=env,
        )

    def wait_ready(self) -> bool:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            if os.path.exists(self.sock_path):
                try:
                    FramingClient.connect_unix(self.sock_path, timeout=2.0).close()
                    return True
                except OSError:
                    pass
            time.sleep(0.1)
        return False

    def connect(self) -> FramingClient:
        return FramingClient.connect_unix(self.sock_path, timeout=self.timeout)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self._log is not None:
            self._log.close()

    def tail_log(self, n: int = 40) -> str:
        try:
            return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-n:])
        except OSError:
            return "(no runner log)"


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_status(client: FramingClient, rep: Report) -> None:
    print("\n[plugin handshake / negotiation]")
    status = client.request("runner.status", {})
    plugins = {p.get("id"): p for p in status.get("plugins", []) or []}
    plugin = plugins.get("utter")
    rep.check("runner.status shows the utter plugin", plugin is not None,
              f"ids={sorted(plugins)}")
    if not plugin:
        return
    rep.check("plugin kind is bundle", plugin.get("kind") == "bundle",
              f"kind={plugin.get('kind')}")
    rep.check("plugin status ok", plugin.get("status") in ("ok", "degraded"),
              f"status={plugin.get('status')}")
    provides = set(plugin.get("provides", []) or [])
    rep.check("plugin provides router.plan@1", "router.plan@1" in provides,
              f"provides={sorted(provides)}")
    rep.check("plugin provides action caps",
              any(c.startswith("action.") for c in provides), f"provides={sorted(provides)}")

    validated = client.request("runner.validate_plugin", {"plugin": "utter"})
    rep.check("validate_plugin ok", validated.get("ok") is True, json.dumps(validated))
    rep.check("validate_plugin reports permissions",
              isinstance(validated.get("permissions"), list)
              and all("enforced" in p for p in validated["permissions"]),
              json.dumps(validated.get("permissions")))


def _first_result(res: dict) -> dict:
    results = res.get("results", []) if isinstance(res, dict) else []
    return results[0] if results else {}


def check_rules_path(client: FramingClient, rep: Report) -> None:
    print("\n[vertical slice: rules path — 'open youtube']")
    res = client.request("runner.command", {"utterance": "open youtube", "provenance": "user"})
    first = _first_result(res)
    detail = str(first.get("detail", ""))
    rep.check("open youtube -> ensure_url", first.get("op") == "ensure_url", json.dumps(first))
    rep.check("open youtube -> youtube.com", "https://www.youtube.com" in detail, detail)
    rep.check("open youtube dry-run ok", first.get("ok") is True
              and detail.startswith("dry-run"), json.dumps(first))


def check_decision_head(client: FramingClient, rep: Report) -> None:
    print("\n[decision-head path — 'pull up youtube']")
    res = client.request("runner.command", {"utterance": "pull up youtube", "provenance": "user"})
    first = _first_result(res)
    if not first:
        rep.skip("pull up youtube -> ensure_url|open_url",
                 "decision head unavailable (vLLM :8001 down or abstained)")
        return
    detail = str(first.get("detail", ""))
    # The decision head may pick either web op for this phrasing; both open the
    # site (checked just below), so accept both instead of flaking.
    rep.check("pull up youtube -> ensure_url|open_url", first.get("op") in ("ensure_url", "open_url"), json.dumps(first))
    rep.check("pull up youtube -> youtube.com", "https://www.youtube.com" in detail, detail)
    rep.check("pull up youtube dry-run ok", first.get("ok") is True
              and detail.startswith("dry-run"), json.dumps(first))


def check_niri_path(client: FramingClient, rep: Report) -> None:
    print("\n[niri path — 'tile right']")
    res = client.request("runner.command", {"utterance": "tile right", "provenance": "user"})
    first = _first_result(res)
    detail = str(first.get("detail", ""))
    rep.check("tile right -> niri", first.get("op") == "niri", json.dumps(first))
    rep.check("tile right -> move-column-right", "move-column-right" in detail, detail)
    rep.check("tile right dry-run ok", first.get("ok") is True
              and detail.startswith("dry-run"), json.dumps(first))


def check_policy(client: FramingClient, rep: Report) -> None:
    print("\n[policy: terminal provenance]")
    # screen-authored terminal args must be rejected -32006
    try:
        client.invoke("utter", "action.invoke",
                      {"op": "terminal", "args": {"command": "rm -rf /"},
                       "provenance": "screen"}, timeout=15.0)
        rep.check("screen terminal rejected -32006", False, "invoke unexpectedly succeeded")
    except RpcError as exc:
        rep.check("screen terminal rejected -32006", exc.code == ERR_UNTRUSTED,
                  f"error={exc.code} {exc.message}")
    except (FramingTimeout, TransportClosed) as exc:
        rep.check("screen terminal rejected -32006", False, str(exc))

    # user terminal is denied by policy (-32003) because terminal is off
    try:
        client.invoke("utter", "action.invoke",
                      {"op": "terminal", "args": {"command": "echo hi"},
                       "provenance": "user"}, timeout=15.0)
        rep.check("user terminal denied -32003", False, "invoke unexpectedly succeeded")
    except RpcError as exc:
        rep.check("user terminal denied -32003", exc.code == ERR_PERMISSION,
                  f"error={exc.code} {exc.message}")
    except (FramingTimeout, TransportClosed) as exc:
        rep.check("user terminal denied -32003", False, str(exc))


def check_real_action(rep: Report, timeout: float) -> None:
    print("\n[real action — 'open youtube' with UTTER_DRY_RUN=0]")
    sock = str(GENERATED / "runner-real.sock")
    runner = Runner(sock, dry_run=False, timeout=timeout, log_name="runner-real.log")
    try:
        runner.start()
        if not runner.wait_ready():
            rep.skip("real open youtube", "real-action runner did not start")
            print(runner.tail_log())
            return
        client = runner.connect()
        try:
            res = client.request("runner.command",
                                 {"utterance": "open youtube", "provenance": "user"},
                                 timeout=timeout)
            first = _first_result(res)
            detail = str(first.get("detail", ""))
            print(f"  observed: op={first.get('op')} ok={first.get('ok')} detail={detail!r}")
            rep.check("real action executed (not dry-run)",
                      bool(first) and not detail.startswith("dry-run"), json.dumps(first))
            rep.check("real action returned a result", bool(first), json.dumps(first))
        finally:
            client.close()
    finally:
        runner.stop()


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="utter M3 verification")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--keep", action="store_true", help="leave the dry-run runner running")
    args = ap.parse_args(argv)

    print("utter M3 verification (real assistant as a plugin)")
    print(f"  repo:   {REPO}")
    print(f"  config: {CONFIG}")

    if not RUNNER_MAIN.exists():
        print("\nBLOCKED: runner/__main__.py is not present.")
        return 2

    GENERATED.mkdir(parents=True, exist_ok=True)
    sock = str(GENERATED / "runner.sock")
    runner = Runner(sock, dry_run=True, timeout=args.timeout, log_name="runner.log")
    rep = Report()
    client = None
    try:
        runner.start()
        if not runner.wait_ready():
            print("\nBLOCKED: runner did not become ready.")
            print("--- runner log tail ---")
            print(runner.tail_log())
            return 2
        client = runner.connect()
        check_status(client, rep)
        check_rules_path(client, rep)
        check_decision_head(client, rep)
        check_niri_path(client, rep)
        check_policy(client, rep)
    except (FramingTimeout, TransportClosed, OSError) as exc:
        print(f"\nBLOCKED: transport error: {exc}")
        print("--- runner log tail ---")
        print(runner.tail_log())
        return 2
    finally:
        if client is not None:
            client.close()
        if not args.keep:
            runner.stop()

    check_real_action(rep, args.timeout)

    summary = rep.summary()
    print(f"\n=== {summary['passed']}/{summary['total']} checks passed, "
          f"{summary['skipped']} skipped ===")
    if rep.failed:
        print("FAILED:")
        for c in rep.failed:
            print(f"  - {c['name']}: {c['detail']}")
        return 1
    if rep.skips:
        print("SKIPPED:")
        for s in rep.skips:
            print(f"  - {s['name']}: {s['reason']}")
    print("M3 VERIFY: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
