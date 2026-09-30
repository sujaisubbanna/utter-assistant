#!/usr/bin/env python3
"""utter_py — the existing ``utter/`` assistant exposed as a protocol plugin.

No rewrite: this module is a thin adapter. It reuses the real router
(``utter.router.rules`` + the Jev decision head ``utter.router.decide``),
the real executor/actions (``utter.executor``) and the real context
(``utter.context.niri``).

Transport: stdio JSON-RPC 2.0 (Content-Length framed), per PROTOCOL.md.

Dry-run: ``UTTER_DRY_RUN`` controls side effects. It defaults to **on** so
tests never touch the desktop; set ``UTTER_DRY_RUN=0`` (or false/no/off) to
execute for real.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Optional

PROTOCOL = "1.0"
ABI = 1
PLUGIN_NAME = "utter_py"
PLUGIN_VERSION = "0.1.0"
PLUGIN_KIND = "bundle"

PROVIDES = [
    "router.plan@1",
    "action.open_url@1",
    "action.terminal@1",
    "action.niri@1",
    "action.input@1",
    "context.live@1",
    "perception.screenshot@1",
    "perception.a11y@1",
]
REQUIRES = ["fs.tmp@1"]
PERMISSIONS = ["input-injection", "process-spawn", "screenshot", "accessibility"]

# ops the plugin can perform, with side-effect class + confirmation hint
OPS = [
    {"op": "ensure_url", "side_effect": "open_url", "needs_confirm": False},
    {"op": "open_url", "side_effect": "open_url", "needs_confirm": False},
    {"op": "ensure_app", "side_effect": "launch", "needs_confirm": False},
    {"op": "launch_app", "side_effect": "launch", "needs_confirm": False},
    {"op": "focus_app", "side_effect": "compositor", "needs_confirm": False},
    {"op": "search", "side_effect": "open_url", "needs_confirm": False},
    {"op": "niri", "side_effect": "compositor", "needs_confirm": False},
    {"op": "media", "side_effect": "media", "needs_confirm": False},
    {"op": "key", "side_effect": "input", "needs_confirm": False},
    {"op": "type_text", "side_effect": "input", "needs_confirm": False},
    {"op": "scroll", "side_effect": "input", "needs_confirm": False},
    {"op": "click_element", "side_effect": "perception", "needs_confirm": False},
    {"op": "click_point", "side_effect": "input", "needs_confirm": False},
    {"op": "terminal", "side_effect": "shell", "needs_confirm": True},
]

# ops that are consequential regardless of args
_CONSEQUENTIAL = {"terminal", "input"}
_DEFAULT_REQUIRE_CONFIRM = ["send", "submit", "delete", "purchase", "pay", "confirm order"]

_WRITE_LOCK = threading.Lock()

# lazily-initialised real utter objects
_CFG: Any = None
_PROFILES: Any = None
_EXECUTOR: Any = None


# --------------------------------------------------------------------------- #
# framing (stdio)
# --------------------------------------------------------------------------- #
def _read_message(stream: Any) -> Optional[Any]:
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
        if len(header) > 8192:
            raise ValueError("header too large")
    length: Optional[int] = None
    for line in header[:-4].split(b"\r\n"):
        name, sep, value = line.partition(b":")
        if sep and name.strip().lower() == b"content-length":
            length = int(value.strip())
    if length is None:
        raise ValueError("missing Content-Length")
    body = stream.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(stream: Any, obj: Any) -> None:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with _WRITE_LOCK:
        stream.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        stream.flush()


# --------------------------------------------------------------------------- #
# real utter wiring (lazy)
# --------------------------------------------------------------------------- #
def _dry_run() -> bool:
    value = os.environ.get("UTTER_DRY_RUN")
    if value is None:
        return True  # safe default: never touch the desktop unless asked
    return value.strip().lower() not in ("0", "false", "no", "off")


def _ensure() -> None:
    global _CFG, _PROFILES, _EXECUTOR
    if _EXECUTOR is not None:
        return
    from utter.config import load_config
    from utter.context import niri
    from utter.executor import Executor
    from utter.router import profiles as profiles_mod

    _CFG = load_config()
    _PROFILES = profiles_mod.load()

    def ctx_builder(with_a11y: bool = False):
        return niri.build_context(with_a11y=with_a11y)

    _EXECUTOR = Executor(ctx_builder, _CFG)


def _context():
    from utter.context import niri

    return niri.build_context(with_a11y=False)


def _needs_confirm(op: str, args: dict) -> bool:
    if op in _CONSEQUENTIAL:
        return True
    if op == "niri" and str(args.get("command", "")) == "close-window":
        return True
    require = _DEFAULT_REQUIRE_CONFIRM
    if _CFG is not None:
        require = getattr(_CFG.actions, "require_confirm", require) or require
    blob = json.dumps(args, ensure_ascii=False).lower()
    return any(str(k).lower() in blob for k in require)


def _step(op: str, args: dict) -> dict:
    return {
        "op": op,
        "args": dict(args or {}),
        "provenance": "user",
        "confirm": _needs_confirm(op, args),
    }


# --------------------------------------------------------------------------- #
# methods
# --------------------------------------------------------------------------- #
def _hello(params: dict) -> dict:
    return {
        "protocol": PROTOCOL,
        "abi": ABI,
        "plugin": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION, "kind": PLUGIN_KIND},
        "transport": "stdio",
        "provides": list(PROVIDES),
        "requires": list(REQUIRES),
        "permissions": list(PERMISSIONS),
    }


def _describe(params: dict) -> dict:
    return {
        "methods": [
            "protocol.hello", "plugin.describe", "plugin.health",
            "router.plan", "action.capabilities", "action.invoke", "context.snapshot",
        ],
        "streams": [],
    }


def _health(params: dict) -> dict:
    detail = f"utter_py ready (dry_run={_dry_run()})"
    try:
        _ensure()
    except Exception as exc:  # noqa: BLE001 - report degraded, keep the handshake
        return {"status": "degraded", "detail": f"{detail}; import failed: {exc}"}
    return {"status": "ok", "detail": detail}


def _plan(params: dict) -> dict:
    utterance = str(params.get("utterance", "")).strip()
    if not utterance:
        return {"steps": []}
    _ensure()
    from utter.router import decide, rules

    ctx = _context()
    rp = rules.plan(utterance, ctx, _PROFILES)
    if rp is not None and getattr(rp, "steps", None):
        return {"steps": [_step(s.action.value, s.args) for s in rp.steps]}

    # rules could not resolve it cheaply -> constrained decision head (Jev).
    decision = None
    try:
        decision = decide.decide(utterance, ctx, _PROFILES, _CFG.router)
    except Exception:  # noqa: BLE001 - fail open to "no plan"
        decision = None
    if decision is not None:
        cand = getattr(decision, "candidate", None)
        if cand is not None and getattr(cand, "op", "none") != "none":
            return {"steps": [_step(cand.op, cand.args)]}
    return {"steps": []}


def _capabilities(params: dict) -> dict:
    return {"ops": [dict(o) for o in OPS]}


def _invoke(params: dict) -> dict:
    op = str(params.get("op") or "")
    args = params.get("args") or {}
    if not op:
        raise ValueError("action.invoke requires 'op'")
    if _dry_run():
        return {"ok": True, "detail": f"dry-run: {op} {json.dumps(args, ensure_ascii=False)}"}

    _ensure()
    from utter.types import Action, Step, Tier

    try:
        action = Action(op)
    except ValueError:
        return {"ok": False, "detail": f"unknown op: {op}"}
    step = Step(action, dict(args), tier=Tier.APP)
    result = _EXECUTOR.execute_step(step)
    return {"ok": bool(result.ok), "detail": result.detail}


def _snapshot(params: dict) -> dict:
    return _ctx_to_dict(_context())


def _ctx_to_dict(ctx) -> dict:
    def rect(r):
        return None if r is None else {"x": r.x, "y": r.y, "w": r.w, "h": r.h}

    focused = ctx.focused
    return {
        "focused": None if focused is None else {
            "app_id": focused.app_id,
            "title": focused.title,
            "pid": focused.pid,
            "window_id": focused.window_id,
            "workspace_id": focused.workspace_id,
        },
        "monitors": [
            {"id": m.id, "output": m.output, "active_workspace_id": m.active_workspace_id,
             "is_focused": m.is_focused, "geometry": rect(m.geometry)}
            for m in ctx.monitors
        ],
        "windows": [
            {"id": w.id, "app_id": w.app_id, "title": w.title,
             "workspace_id": w.workspace_id, "is_focused": w.is_focused}
            for w in ctx.windows
        ],
        "clipboard": ctx.clipboard,
        "timestamp": ctx.timestamp,
    }


_HANDLERS = {
    "protocol.hello": _hello,
    "plugin.describe": _describe,
    "plugin.health": _health,
    "router.plan": _plan,
    "action.capabilities": _capabilities,
    "action.invoke": _invoke,
    "context.snapshot": _snapshot,
}


def handle(method: str, params: dict) -> Any:
    handler = _HANDLERS.get(method)
    if handler is None:
        raise ValueError(f"method not found: {method}")
    return handler(params)


# --------------------------------------------------------------------------- #
# stdio loop
# --------------------------------------------------------------------------- #
def serve(stdin: Any, stdout: Any) -> int:
    while True:
        msg = _read_message(stdin)
        if msg is None:
            return 0
        if not isinstance(msg, dict):
            continue
        method = str(msg.get("method") or "")
        req_id = msg.get("id")
        raw_params = msg.get("params")
        params: dict = raw_params if isinstance(raw_params, dict) else {}
        if method == "$/cancel":
            continue
        if req_id is None:
            continue
        try:
            result = handle(method, params)
            _write_message(stdout, {"jsonrpc": "2.0", "id": req_id, "result": result})
        except Exception as exc:  # noqa: BLE001
            _write_message(stdout, {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            })


def main(argv: Optional[list[str]] = None) -> int:
    return serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
