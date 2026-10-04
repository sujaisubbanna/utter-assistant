#!/usr/bin/env python3
"""M3 verification: drive the real ``utter/`` assistant through the runner.

Starts the runner with ``config.m3.toml`` (dry-run ON) and asserts the vertical
slice routes through the real rules + Jev decision head.

The real-action check — which opens YouTube in the live desktop browser — is OFF
by default, because the test suite must not touch the user's desktop. Enable it
explicitly with ``--real-action`` or ``UTTER_M3_REAL_ACTION=1``.

Usage::

    .venv-agent/bin/python tests/m3/verify_m3.py [--keep] [--timeout 60] [--real-action]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CONF = REPO / "tests" / "conformance"
sys.path.insert(0, str(CONF))
sys.path.insert(0, str(REPO / "tests"))

from framing_client import (  # noqa: E402
    ERR_PERMISSION,
    ERR_UNTRUSTED,
    FramingClient,
    FramingTimeout,
    RpcError,
    TransportClosed,
)
from _harness.report import Report  # noqa: E402
from _harness.runner_proc import Runner  # noqa: E402

CONFIG = REPO / "config.m3.toml"
RUNNER_MAIN = REPO / "runner" / "__main__.py"
GENERATED = HERE / "generated"


# --------------------------------------------------------------------------- #
# runner lifecycle
# --------------------------------------------------------------------------- #
def _make_runner(sock_path: str, *, dry_run: bool, timeout: float,
                 log_name: str) -> Runner:
    """Shared runner helper plus M3's dry-run/PYTHONPATH/PATH environment."""
    env = {
        "UTTER_DRY_RUN": "1" if dry_run else "0",
        "UTTER_RUNNER_SOCK": sock_path,
        "PYTHONPATH": str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        # make `python3` in the plugin entrypoint resolve to this venv
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    return Runner(config=CONFIG, sock_path=sock_path, log_dir=GENERATED,
                  timeout=timeout, log_name=log_name, env=env, stop_timeout=8.0)


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_status(client: FramingClient, rep: Report) -> dict | None:
    print("\n[plugin handshake / negotiation]")
    status = client.request("runner.status", {})
    plugins = {p.get("id"): p for p in status.get("plugins", []) or []}
    plugin = plugins.get("utter")
    rep.check("runner.status shows the utter plugin", plugin is not None,
              f"ids={sorted(plugins)}")
    if not plugin:
        return None
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
    return plugin


def _plugin_healthy(plugin: dict | None) -> bool:
    if not plugin:
        return False
    provides = set(plugin.get("provides", []) or [])
    return plugin.get("status") in ("ok", "degraded") and "router.plan@1" in provides


def _decision_head_url() -> str:
    """The configured decision-head base URL (vLLM default when unreadable)."""
    try:
        from utter.config import load_config
        return load_config(CONFIG).router.llm_base_url
    except Exception:  # noqa: BLE001 - the probe must never crash the suite
        return "http://127.0.0.1:8001/v1"


def _decision_head_state(url: str, timeout: float = 1.5) -> str:
    """Classify the configured decision head for a *hermetic* skip decision.

    A bare reachability probe is not enough: an unrelated process can own the
    port (the installed ``utter-runner.service`` answers 404 on :8001), so we
    must tell a usable head from a foreign/misconfigured one. Returns:

      "ready"   - HTTP 200 with a non-empty OpenAI-style ``models`` list: a head
                  this test can genuinely exercise, so an empty plan is a real
                  routing failure.
      "foreign" - something answers but is not a usable models endpoint
                  (4xx/5xx, non-JSON, or an empty list): the head cannot be
                  exercised, so the plan check is skipped.
      "offline" - connection refused/timeout: no head at all.
    """
    probe = url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(probe, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read()
    except urllib.error.HTTPError:
        return "foreign"  # answered, but not a models endpoint (e.g. 404)
    except (urllib.error.URLError, OSError, ValueError):
        return "offline"
    if status != 200:
        return "foreign"
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return "foreign"
    models = data.get("data") if isinstance(data, dict) else None
    return "ready" if isinstance(models, list) and models else "foreign"


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


def check_decision_head(client: FramingClient, rep: Report, *, plugin_healthy: bool) -> None:
    print("\n[decision-head path — 'pull up youtube']")
    res = client.request("runner.command", {"utterance": "pull up youtube", "provenance": "user"})
    first = _first_result(res)
    if not first:
        # Only an unhealthy plugin or an explicitly offline head excuses an
        # empty plan; anything else is a real routing failure.
        if not plugin_healthy:
            rep.check("decision head resolved a plan", False,
                      "utter plugin is unhealthy; empty plan can not be attributed "
                      "to an offline head")
            return
        state = _decision_head_state(_decision_head_url())
        if state != "ready":
            # Only a usable head ("ready") makes an empty plan attributable to
            # routing. A foreign service on the port or a missing head means we
            # cannot verify a plan here: skip rather than fail (or blanket-pass).
            rep.skip("pull up youtube -> ensure_url|open_url",
                     f"decision head not available ({state}); cannot verify a plan")
            return
        rep.check("decision head resolved a plan", False,
                  "plugin healthy and decision head reachable, but no plan was produced")
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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def check_real_action(rep: Report, timeout: float, enabled: bool) -> None:
    if not enabled:
        rep.skip(
            "real open youtube",
            "real desktop action disabled by default "
            "(pass --real-action or set UTTER_M3_REAL_ACTION=1 to enable)",
        )
        return
    print("\n[real action — 'open youtube' with UTTER_DRY_RUN=0]")
    sock = str(GENERATED / "runner-real.sock")
    runner = _make_runner(sock, dry_run=False, timeout=timeout, log_name="runner-real.log")
    try:
        runner.start()
        if not runner.wait_ready():
            # Real action was explicitly requested: not starting is a failure,
            # not something to skip (the operator asked for the live path).
            rep.check("real-action runner started", False,
                      "real-action runner did not start")
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
    ap.add_argument(
        "--real-action",
        action="store_true",
        help="run the real (non-dry-run) 'open youtube' action against the live "
        "desktop (also enabled by UTTER_M3_REAL_ACTION=1)",
    )
    args = ap.parse_args(argv)

    print("utter M3 verification (real assistant as a plugin)")
    print(f"  repo:   {REPO}")
    print(f"  config: {CONFIG}")

    if not RUNNER_MAIN.exists():
        print("\nBLOCKED: runner/__main__.py is not present.")
        return 2

    GENERATED.mkdir(parents=True, exist_ok=True)
    sock = str(GENERATED / "runner.sock")
    runner = _make_runner(sock, dry_run=True, timeout=args.timeout, log_name="runner.log")
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
        plugin = check_status(client, rep)
        check_rules_path(client, rep)
        check_decision_head(client, rep, plugin_healthy=_plugin_healthy(plugin))
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

    real_action = args.real_action or _truthy(os.environ.get("UTTER_M3_REAL_ACTION"))
    check_real_action(rep, args.timeout, real_action)

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
