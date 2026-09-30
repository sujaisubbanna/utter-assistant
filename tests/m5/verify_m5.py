#!/usr/bin/env python3
"""M5 verification: assistant doctor / model store / recommend / install-state.

Usage::

    .venv-agent/bin/python tests/m5/verify_m5.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from range_server import RangeServer  # noqa: E402

ASSISTANT = [sys.executable, "-m", "assistant"]
CONFIG_M3 = REPO / "config.m3.toml"


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
        return {"total": len(self.checks), "passed": len(self.checks) - len(self.failed),
                "failed": len(self.failed), "skipped": len(self.skips),
                "checks": self.checks, "skips": self.skips}


def run(args: list[str], env: dict, timeout: float = 180.0) -> subprocess.CompletedProcess:
    return subprocess.run(ASSISTANT + args, cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="utter M5 verification")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args(argv)

    print("utter M5 verification (assistant CLI)")
    print(f"  repo: {REPO}")

    tmp = Path(tempfile.mkdtemp(prefix="lav-m5-"))
    store = tmp / "models"
    state = tmp / "state"
    env = dict(os.environ)
    env["UTTER_MODELS"] = str(store)
    env["XDG_STATE_HOME"] = str(state)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")

    rep = Report()

    # -- test payload + Range server ------------------------------------- #
    payload = tmp / "test.bin"
    data = os.urandom(4 * 1024 * 1024)
    payload.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    server = RangeServer(str(payload), chunk_size=65536, delay=0.02)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = server.url
    print(f"  server: {url} ({len(data)} bytes, sha256 {expected[:16]}…)")

    try:
        # -- resumable pull: kill mid-download, then resume -------------- #
        print("\n[model store: resumable pull]")
        proc = subprocess.Popen(ASSISTANT + ["models", "pull", url, "--json"],
                                cwd=str(REPO), env=env, start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 8
        while time.time() < deadline:
            if list((store / "blobs").glob("*.partial")):
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        time.sleep(0.3)  # let it download a chunk or two
        # kill the whole process group so the curl child dies too
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait()
        partials = list((store / "blobs").glob("*.partial"))
        rep.check("kill mid-download leaves a .partial", bool(partials),
                  f"partials={[p.name for p in partials]}")

        resumed = run(["models", "pull", url], env)
        rep.check("resume completes", resumed.returncode == 0,
                  (resumed.stderr or resumed.stdout)[-300:])
        blobs = list((store / "blobs").glob("sha256-*"))
        rep.check("blob sha256 matches", any(b.name == f"sha256-{expected}" for b in blobs),
                  f"blobs={[b.name[:24] for b in blobs]}")
        rep.check("resume used a Range request", bool(server.ranges_seen),
                  f"ranges={server.ranges_seen[:2]}")

        # -- list / show ------------------------------------------------- #
        print("\n[model store: list / show]")
        listed = run(["models", "list", "--json"], env)
        ldata = json.loads(listed.stdout)
        rep.check("list shows the model",
                  any(m.get("name") == "test" for m in ldata.get("models", [])),
                  json.dumps(ldata)[:200])
        shown = run(["models", "show", "test", "--json"], env)
        sdata = json.loads(shown.stdout)
        rep.check("show reports files",
                  bool(sdata.get("models")) and bool(sdata["models"][0].get("files")),
                  json.dumps(sdata)[:200])

        # -- rm ---------------------------------------------------------- #
        print("\n[model store: rm]")
        removed = run(["models", "rm", "test", "--json"], env)
        rdata = json.loads(removed.stdout)
        rep.check("rm removed the manifest", bool(rdata.get("removed_manifests")),
                  json.dumps(rdata)[:200])
        rep.check("rm removed the blob", bool(rdata.get("removed_blobs")),
                  json.dumps(rdata)[:200])
        rep.check("blob is gone", not list((store / "blobs").glob("sha256-*")))

        # -- --json NDJSON progress -------------------------------------- #
        print("\n[model store: --json progress]")
        pulled = run(["models", "pull", url, "--json"], env)
        events = [json.loads(line) for line in pulled.stdout.splitlines() if line.strip()]
        rep.check("--json emits progress events",
                  any(e.get("event") == "progress" for e in events),
                  f"events={[e.get('event') for e in events][:6]}")
        rep.check("--json emits a done event",
                  any(e.get("event") == "done" for e in events),
                  f"events={[e.get('event') for e in events][-3:]}")

        # -- prune ------------------------------------------------------- #
        print("\n[model store: prune]")
        pruned = run(["models", "prune", "--json"], env)
        pdata = json.loads(pruned.stdout)
        rep.check("prune reports partials + blobs",
                  "removed_partials" in pdata and "removed_blobs" in pdata,
                  json.dumps(pdata)[:200])

        # -- recommend --------------------------------------------------- #
        print("\n[recommend]")
        rec = run(["recommend", "--json"], env)
        rdata = json.loads(rec.stdout)
        rep.check("recommend detects RAM", rdata["hardware"]["ram_gb"] > 0,
                  f"ram_gb={rdata['hardware']['ram_gb']}")
        rep.check("recommend detects a GPU", len(rdata["hardware"]["gpus"]) >= 1,
                  json.dumps(rdata["hardware"]["gpus"]))
        rep.check("recommend has all profiles",
                  all(k in rdata["suggestions"] for k in
                      ("stt", "decision_llm", "planner_llm", "vision")),
                  json.dumps(rdata["suggestions"])[:200])

        # -- install-state ----------------------------------------------- #
        print("\n[install-state]")
        rec2 = run(["install-state", "record",
                    "--files", "/usr/bin/wtype,/usr/bin/ydotool",
                    "--units", "utter-runner.service",
                    "--packages", "wtype,ydotool",
                    "--version", "0.1.0", "--protocol", "1.0", "--json"], env)
        idata = json.loads(rec2.stdout)
        rep.check("install-state record (CSV) returns data",
                  idata.get("files") == ["/usr/bin/wtype", "/usr/bin/ydotool"]
                  and idata.get("units") == ["utter-runner.service"]
                  and idata.get("packages") == ["wtype", "ydotool"], json.dumps(idata))
        merged = run(["install-state", "record", "--files", "/usr/bin/grim", "--json"], env)
        mdata = json.loads(merged.stdout)
        rep.check("install-state record merges (no clobber)",
                  mdata.get("files") == ["/usr/bin/wtype", "/usr/bin/ydotool", "/usr/bin/grim"]
                  and mdata.get("packages") == ["wtype", "ydotool"], json.dumps(mdata))
        shown = run(["install-state", "show"], env)
        rep.check("install-state show prints the full manifest",
                  "/usr/bin/grim" in shown.stdout and "ydotool" in shown.stdout,
                  shown.stdout[:200])
        install_json = state / "utter" / "install.json"
        rep.check("install.json is valid",
                  install_json.is_file()
                  and json.loads(install_json.read_text()).get("protocol") == "1.0",
                  str(install_json))

        # -- doctor (no runner) ------------------------------------------ #
        print("\n[doctor: runner unavailable]")
        off = run(["doctor", "--json"], dict(env, UTTER_RUNNER_SOCK=str(tmp / "nope.sock")))
        odata = json.loads(off.stdout)
        rep.check("doctor reports unavailable runner",
                  odata.get("connected") is False and odata.get("ok") is False,
                  json.dumps(odata)[:200])
        rep.check("doctor includes deps", "wtype" in odata.get("deps", {}),
                  json.dumps(odata.get("deps")))

        # -- doctor (live runner) ---------------------------------------- #
        print("\n[doctor: live runner]")
        sock = str(tmp / "runner.sock")
        runner_env = dict(env)
        runner_env["UTTER_DRY_RUN"] = "1"
        runner_env["UTTER_RUNNER_SOCK"] = sock
        runner_env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        runner = subprocess.Popen(
            [sys.executable, "-m", "runner", "--config", str(CONFIG_M3), "--socket", sock],
            cwd=str(REPO), env=runner_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ready = False
        for _ in range(int(args.timeout * 10)):
            if os.path.exists(sock):
                ready = True
                break
            if runner.poll() is not None:
                break
            time.sleep(0.1)
        try:
            if not ready:
                rep.skip("doctor against a live runner", "runner did not start")
            else:
                live = run(["doctor", "--json"], dict(env, UTTER_RUNNER_SOCK=sock))
                ldata = json.loads(live.stdout)
                rep.check("doctor connects to the runner", ldata.get("connected") is True,
                          json.dumps(ldata)[:200])
                rep.check("doctor lists the utter plugin",
                          any(p.get("id") == "utter" for p in ldata.get("plugins", [])),
                          json.dumps(ldata.get("plugins"))[:200])
                rep.check("doctor reports per-permission advisory",
                          all("advisory" in p for pl in ldata.get("plugins", [])
                              for p in pl.get("permissions", [])),
                          json.dumps(ldata.get("plugins"))[:200])
        finally:
            runner.terminate()
            try:
                runner.wait(timeout=8)
            except subprocess.TimeoutExpired:
                runner.kill()
    finally:
        server.shutdown()
        server.server_close()

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
    print("M5 VERIFY: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
