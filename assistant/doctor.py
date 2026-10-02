"""``assistant doctor``: deps + plugin negotiation + install drift.

Emits the stable JSON from docs/COMPATIBILITY.md §8 plus a ``deps`` section.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import deps as deps_mod
from . import install_state, util
from .runner_client import RunnerClient, RunnerError

_REPO = Path(__file__).resolve().parent.parent
_CAPS_PATH = _REPO / "protocol" / "capabilities.json"

RUNNER_PROTOCOL = "1.0"
RUNNER_ABI = 1


def _runner_version() -> str:
    try:
        from runner import __version__  # type: ignore

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _capability_registry() -> dict[str, dict]:
    data = util.read_json(_CAPS_PATH, default={})
    return dict((data or {}).get("capabilities") or {})


def _deprecations(plugin: dict) -> list[dict]:
    registry = _capability_registry()
    caps = list(plugin.get("provides", []) or []) + list(plugin.get("requires", []) or [])
    out: list[dict] = []
    for cap in caps:
        entry = registry.get(cap) or {}
        dep = entry.get("deprecated")
        if dep:
            out.append({"capability": cap, **(dep if isinstance(dep, dict) else {})})
    return out


def _drift(runner_info: dict) -> list[dict]:
    recorded = install_state.load()
    drift: list[dict] = []
    rec_protocol = recorded.get("protocol")
    if rec_protocol and rec_protocol != runner_info.get("protocol"):
        drift.append({"kind": "protocol", "recorded": rec_protocol,
                      "actual": runner_info.get("protocol")})
    rec_version = recorded.get("version")
    if rec_version and rec_version != runner_info.get("version"):
        drift.append({"kind": "version", "recorded": rec_version,
                      "actual": runner_info.get("version")})
    return drift


def build_report(sock: Optional[str] = None, timeout: float = 10.0) -> dict:
    from utter import runtime
    runner_info = {"protocol": RUNNER_PROTOCOL, "abi": RUNNER_ABI, "version": _runner_version()}
    report: dict[str, Any] = {
        "ok": True,
        "runner": runner_info,
        "plugins": [],
        "drift": [],
        "deps": deps_mod.probe_deps(),
        "compositor": compositor_section(),
        "runtime": runtime.probe_runtime(),
        "connected": False,
    }

    sock_path = sock or util.runner_sock_path()
    client = RunnerClient(sock_path, timeout=timeout)
    try:
        client.connect()
    except FileNotFoundError:
        report["ok"] = False
        report["error"] = (
            f"the runner isn't running: no socket at {sock_path}. "
            "Start it with: systemctl --user start utter-runner.service"
        )
        report["socket"] = sock_path
        report["drift"] = _drift(runner_info)
        return report
    except OSError as exc:
        report["ok"] = False
        report["error"] = f"couldn't reach the runner at {sock_path}: {exc}"
        report["socket"] = sock_path
        report["drift"] = _drift(runner_info)
        return report

    try:
        status = client.call("runner.status", {})
        report["connected"] = True
        for plugin in status.get("plugins", []) or []:
            pid = plugin.get("id")
            entry: dict[str, Any] = {
                "id": pid,
                "kind": plugin.get("kind"),
                "epoch": plugin.get("epoch"),
                "status": plugin.get("status"),
                "negotiated": {"protocol": RUNNER_PROTOCOL, "abi": RUNNER_ABI},
                "unknown_capabilities": [],
                "missing_requires": [],
                "permissions": [],
                "deprecations": _deprecations(plugin),
            }
            try:
                validated = client.call("runner.validate_plugin", {"plugin": pid})
                entry["negotiated"] = validated.get("negotiated") or entry["negotiated"]
                entry["unknown_capabilities"] = validated.get("unknown_capabilities") or []
                entry["missing_requires"] = validated.get("missing_requires") or []
                entry["permissions"] = [
                    {"name": p.get("name"),
                     "enforced": bool(p.get("enforced")),
                     "advisory": not bool(p.get("enforced"))}
                    for p in (validated.get("permissions") or [])
                ]
                if not validated.get("ok", True):
                    report["ok"] = False
            except (RunnerError, TimeoutError, ConnectionError) as exc:
                entry["error"] = str(exc)
                report["ok"] = False
            report["plugins"].append(entry)
    except (RunnerError, TimeoutError, ConnectionError, OSError) as exc:
        report["ok"] = False
        report["error"] = f"runner call failed: {exc}"
    finally:
        client.close()

    report["drift"] = _drift(runner_info)
    if report["drift"]:
        report["ok"] = False
    return report


def compositor_section() -> dict:
    """Detected compositor + active backend + capabilities (never raises, never acts)."""
    from utter import platform
    if platform.is_macos():
        return {
            "platform": "darwin",
            "requested": "macos",
            "detected": "quartz",
            "session_type": "aqua",
            "desktop": "Aqua/WindowServer",
            "plasma_version": "",
            "evidence": ["platform=darwin (macOS WindowServer)"],
            "active": "quartz",
            "reason": "macOS native WindowServer + Accessibility",
            "available": True,
            "capabilities": {
                "focused_window": True,
                "list_windows": True,
                "activate": True,
                "close": True,
                "minimize": True,
                "maximize": True,
                "move_to_workspace": False,
                "switch_workspace": False,
                "screenshot": bool(util.which("screencapture")),
                "compositor_action": False,
            },
            "tools": {
                "screencapture": util.which("screencapture"),
                "osascript": util.which("osascript"),
                "pbpaste": util.which("pbpaste"),
            },
        }
    try:
        from utter.context import compositor

        p = compositor.probe()
    except Exception as exc:  # noqa: BLE001 - doctor must always produce a report
        return {"detected": "unknown", "active": "unknown", "error": str(exc), "capabilities": {}}
    det = p.get("detected") or {}
    return {
        "platform": p.get("platform"),
        "requested": p.get("requested"),
        "detected": det.get("compositor"),
        "session_type": det.get("session_type"),
        "desktop": det.get("desktop"),
        "plasma_version": det.get("plasma_version"),
        "evidence": det.get("evidence") or [],
        "active": p.get("active"),
        "reason": p.get("reason"),
        "available": p.get("available"),
        "capabilities": p.get("capabilities") or {},
        "tools": {k: v for k, v in (p.get("tools") or {}).items() if not isinstance(v, dict)},
    }


def human(report: dict) -> str:
    lines: list[str] = []
    runner = report.get("runner", {})
    lines.append(f"runner: protocol {runner.get('protocol')} abi {runner.get('abi')} "
                 f"version {runner.get('version')}")
    rt = report.get("runtime", {})
    if rt:
        lines.append(f"runtime: platform {rt.get('platform')} device {rt.get('device')}")
        gpu_info = rt.get("gpu", {})
        if gpu_info:
            lines.append(f"  gpu: {gpu_info.get('name')} ({gpu_info.get('runtime')})")
        llm = rt.get("llm", {})
        if llm:
            lines.append(f"  llm: [{llm.get('status')}] {llm.get('provider')} @ {llm.get('endpoint')} ({llm.get('model')})")
            if llm.get("message"):
                lines.append(f"       {llm.get('message')}")
        vision = rt.get("vision", {})
        if vision:
            lines.append(f"  vision: [{vision.get('status')}] {vision.get('provider')} @ {vision.get('endpoint')} ({vision.get('model')})")
            if vision.get("message"):
                lines.append(f"          {vision.get('message')}")
        stt = rt.get("stt", {})
        if stt:
            lines.append(f"  stt: [{stt.get('status')}] primary={stt.get('primary')} fallback={stt.get('fallback')}")
        tts = rt.get("tts", {})
        if tts:
            lines.append(f"  tts: [{tts.get('status')}] engine={tts.get('engine')}")
    comp = report.get("compositor") or {}
    if comp:
        lines.append(f"compositor: detected {comp.get('detected')} -> backend {comp.get('active')}"
                     + (f" (plasma {comp.get('plasma_version')})" if comp.get("plasma_version") else "")
                     + (f" [{comp.get('session_type')}]" if comp.get("session_type") else ""))
        caps = comp.get("capabilities") or {}
        missing = [k for k, v in caps.items() if not v]
        if missing:
            lines.append(f"  unavailable: {', '.join(missing)}")
    if not report.get("connected"):
        lines.append(f"  NOT CONNECTED: {report.get('error', 'runner socket unavailable')}")
    else:
        lines.append(f"  plugins: {len(report.get('plugins', []))}")
        for p in report.get("plugins", []):
            perms = ", ".join(
                f"{x['name']}={'enforced' if x['enforced'] else 'advisory'}"
                for x in p.get("permissions", [])
            ) or "-"
            lines.append(f"    - {p.get('id')} [{p.get('kind')}] epoch={p.get('epoch')} "
                         f"status={p.get('status')}")
            lines.append(f"        negotiated={p.get('negotiated')} "
                         f"unknown={p.get('unknown_capabilities')} "
                         f"missing={p.get('missing_requires')}")
            lines.append(f"        permissions: {perms}")
            if p.get("deprecations"):
                lines.append(f"        deprecations: {p['deprecations']}")
            if p.get("error"):
                lines.append(f"        error: {p['error']}")

    deps = report.get("deps", {})
    missing = deps_mod.missing_deps(deps)
    lines.append("deps:")
    for name, present in deps.items():
        lines.append(f"    {'ok ' if present else 'MISSING'} {name}")
    if missing:
        lines.append(f"  missing: {', '.join(missing)}")

    drift = report.get("drift", [])
    lines.append(f"drift: {drift if drift else 'none'}")
    lines.append(f"ok: {report.get('ok')}")
    return "\n".join(lines)
