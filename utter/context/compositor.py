"""Compositor abstraction: detect the running Wayland compositor and pick a backend.

Every window/workspace/screenshot touchpoint in the assistant goes through
:func:`active`, which returns a *backend module*. All backends expose the same
module-level functions (see ``utter/context/backends/__init__.py``):

    focused_window() list_windows() find_windows() list_monitors()
    focus_window(id) focus_window_on_workspace(id) build_context(with_a11y)
    close_window(id) minimize_window(id) maximize_window(id)
    move_window_to_workspace(ws, id) switch_workspace(ws)
    screenshot(path, output) run_action(command, args) plan_action(command, args)
    capabilities() available() plan()

Backends
    niri  -> :mod:`utter.context.backends.niri`  (wraps ``utter.context.niri``;
             behaviour unchanged: the niri module itself is still the provider)
    kwin  -> :mod:`utter.context.backends.kwin`  (KDE Plasma, D-Bus + kdotool)
    unknown -> :mod:`utter.context.backends.fallback` (reports unsupported)

Selection order
    1. ``UTTER_COMPOSITOR`` environment variable (tests / one-off probes)
    2. ``[general] compositor`` in the config file ("auto" | "niri" | "kwin")
    3. detection from the session environment (:func:`detect`)

Detection rules (first match wins, evidence is recorded):
    XDG_CURRENT_DESKTOP contains "niri"            -> niri
    XDG_CURRENT_DESKTOP contains "KDE"             -> kwin
    KDE_FULL_SESSION=true or KDE_SESSION_VERSION   -> kwin
    DESKTOP_SESSION / XDG_SESSION_DESKTOP is a plasma/kde/niri name
    NIRI_SOCKET set                                -> niri
    otherwise                                      -> unknown

Nothing here is executed at import time; every call is cheap (environment
reads) so tests can flip the environment between calls.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

from utter import platform

NIRI = "niri"
KWIN = "kwin"
UNKNOWN = "unknown"
AUTO = "auto"
BACKENDS = (NIRI, KWIN)

ENV_OVERRIDE = "UTTER_COMPOSITOR"

# Capability names every backend reports in ``capabilities()``.
CAP_FOCUSED_WINDOW = "focused_window"
CAP_LIST_WINDOWS = "list_windows"
CAP_ACTIVATE = "activate"
CAP_CLOSE = "close"
CAP_MINIMIZE = "minimize"
CAP_MAXIMIZE = "maximize"
CAP_MOVE_TO_WORKSPACE = "move_to_workspace"
CAP_SWITCH_WORKSPACE = "switch_workspace"
CAP_SCREENSHOT = "screenshot"
CAP_COMPOSITOR_ACTION = "compositor_action"
CAPABILITIES = (
    CAP_FOCUSED_WINDOW, CAP_LIST_WINDOWS, CAP_ACTIVATE, CAP_CLOSE, CAP_MINIMIZE,
    CAP_MAXIMIZE, CAP_MOVE_TO_WORKSPACE, CAP_SWITCH_WORKSPACE, CAP_SCREENSHOT,
    CAP_COMPOSITOR_ACTION,
)

_KDE_SESSION_NAMES = {"plasma", "plasmawayland", "plasmax11", "plasma-wayland", "kde", "kde-plasma"}


class CompositorUnsupported(RuntimeError):
    """Raised by capability entry points that cannot return a structured result.

    Callers that must return a value (``screenshot()``) raise this; everything
    else returns an :class:`Outcome` with ``unsupported=True``.
    """

    def __init__(self, backend: str, capability: str, reason: str = ""):
        self.backend = backend
        self.capability = capability
        self.reason = reason
        super().__init__(f"{capability} is not supported on {backend}" + (f": {reason}" if reason else ""))

    def outcome(self) -> "Outcome":
        return Outcome.unsupported_for(self.backend, self.capability, self.reason)


@dataclass
class Outcome:
    """Structured result of a compositor action.

    ``argv`` lists every command the backend ran (or, in dry-run, would run) so
    probes and tests can show exactly what hits the system. ``unsupported`` is
    the graceful "this backend cannot do that" signal: never an exception.
    """
    ok: bool
    detail: str = ""
    argv: list[list[str]] = field(default_factory=list)
    unsupported: bool = False
    backend: str = ""
    capability: str = ""

    @classmethod
    def unsupported_for(cls, backend: str, capability: str, reason: str = "") -> "Outcome":
        detail = f"unsupported on {backend}: {capability}"
        if reason:
            detail += f" ({reason})"
        return cls(False, detail, [], True, backend, capability)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Detection:
    compositor: str = UNKNOWN          # niri | kwin | unknown
    session_type: str = ""             # wayland | x11 | ""
    desktop: str = ""                  # raw XDG_CURRENT_DESKTOP
    plasma_version: str = ""           # "5" | "6" | "" (from KDE_SESSION_VERSION)
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Resolution:
    requested: str
    detected: Detection
    active: str
    reason: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["detected"] = self.detected.as_dict()
        return d


def _desktop_tokens(value: str) -> list[str]:
    # XDG_CURRENT_DESKTOP is a colon-separated list ("KDE", "niri", "GNOME:ubuntu").
    return [t.strip().lower() for t in (value or "").split(":") if t.strip()]


def detect(env: Optional[Mapping[str, str]] = None) -> Detection:
    """Pure detection from an environment mapping (defaults to ``os.environ``)."""
    e = os.environ if env is None else env
    det = Detection(
        session_type=(e.get("XDG_SESSION_TYPE") or "").strip().lower(),
        desktop=e.get("XDG_CURRENT_DESKTOP") or "",
        plasma_version=(e.get("KDE_SESSION_VERSION") or "").strip(),
    )
    tokens = _desktop_tokens(det.desktop)
    if "niri" in tokens:
        det.compositor = NIRI
        det.evidence.append(f"XDG_CURRENT_DESKTOP={det.desktop}")
        return det
    if "kde" in tokens:
        det.compositor = KWIN
        det.evidence.append(f"XDG_CURRENT_DESKTOP={det.desktop}")
        return det
    full = (e.get("KDE_FULL_SESSION") or "").strip().lower()
    if full in ("true", "1", "yes"):
        det.compositor = KWIN
        det.evidence.append(f"KDE_FULL_SESSION={full}")
        return det
    if det.plasma_version:
        det.compositor = KWIN
        det.evidence.append(f"KDE_SESSION_VERSION={det.plasma_version}")
        return det
    for var in ("XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        raw = (e.get(var) or "").strip()
        low = raw.lower()
        if not low:
            continue
        if "niri" in low:
            det.compositor = NIRI
            det.evidence.append(f"{var}={raw}")
            return det
        if low in _KDE_SESSION_NAMES or low.startswith("plasma"):
            det.compositor = KWIN
            det.evidence.append(f"{var}={raw}")
            return det
    if e.get("NIRI_SOCKET"):
        det.compositor = NIRI
        det.evidence.append("NIRI_SOCKET set")
        return det
    det.evidence.append("no compositor markers in the environment")
    return det


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
_CFG_REQUESTED: Optional[str] = None  # cached [general] compositor value


def reset_cache() -> None:
    """Forget the cached config value (tests)."""
    global _CFG_REQUESTED
    _CFG_REQUESTED = None


def configured(env: Optional[Mapping[str, str]] = None) -> str:
    """The requested backend: ``UTTER_COMPOSITOR`` env, else config, else "auto"."""
    e = os.environ if env is None else env
    forced = (e.get(ENV_OVERRIDE) or "").strip().lower()
    if forced:
        return forced
    global _CFG_REQUESTED
    if _CFG_REQUESTED is None:
        value = AUTO
        try:
            from utter.config import load_config

            value = str(getattr(load_config().general, "compositor", AUTO) or AUTO)
        except Exception:  # noqa: BLE001 - config must never break context
            value = AUTO
        _CFG_REQUESTED = value.strip().lower() or AUTO
    return _CFG_REQUESTED


def normalize_name(value: str) -> str:
    v = (value or "").strip().lower()
    aliases = {"kde": KWIN, "plasma": KWIN, "kwin_wayland": KWIN, "kwin_x11": KWIN}
    return aliases.get(v, v)


def resolve(requested: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> Resolution:
    """Decide which backend is active and why. Pure given ``requested`` + ``env``."""
    req = normalize_name(requested if requested is not None else configured(env))
    det = detect(env)
    if req in BACKENDS:
        return Resolution(req, det, req, f"explicit override ({req})")
    if req and req not in (AUTO, ""):
        return Resolution(req, det, det.compositor if det.compositor in BACKENDS else UNKNOWN,
                          f"unknown compositor name {req!r}; fell back to detection")
    if det.compositor in BACKENDS:
        return Resolution(AUTO, det, det.compositor, "detected: " + "; ".join(det.evidence))
    return Resolution(AUTO, det, UNKNOWN, "no supported compositor detected: " + "; ".join(det.evidence))


def backend_for(name: str):
    """The backend module for ``name`` (``niri`` | ``kwin`` | anything else -> fallback)."""
    name = normalize_name(name)
    if name == NIRI:
        from utter.context.backends import niri as mod
    elif name == KWIN:
        from utter.context.backends import kwin as mod
    else:
        from utter.context.backends import fallback as mod
    return mod


def active(requested: Optional[str] = None, env: Optional[Mapping[str, str]] = None):
    """The active backend module (resolved on every call; cheap)."""
    return backend_for(resolve(requested, env).active)


def active_name(requested: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> str:
    return resolve(requested, env).active


# --------------------------------------------------------------------------- #
# probe / dry-run
# --------------------------------------------------------------------------- #
def probe(requested: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Diagnostics snapshot: detection, selection, tools, capabilities, planned calls.

    Pure with respect to the desktop: it never runs a compositor command, only
    ``shutil.which`` probes and the backends' ``plan()``.
    """
    res = resolve(requested, env)
    mod = backend_for(res.active)
    out: dict[str, Any] = {
        "platform": platform.name(),
        "requested": res.requested,
        "detected": res.detected.as_dict(),
        "active": res.active,
        "reason": res.reason,
        "available": bool(mod.available()),
        "capabilities": dict(mod.capabilities()),
    }
    try:
        out["plan"] = mod.plan()
    except Exception as exc:  # noqa: BLE001 - probes must never crash
        out["plan"] = {"error": str(exc)}
    try:
        out["tools"] = dict(mod.tools())
    except Exception as exc:  # noqa: BLE001
        out["tools"] = {"error": str(exc)}
    return out


def format_probe(p: dict[str, Any]) -> str:
    lines = [
        f"platform:   {p.get('platform')}",
        f"requested:  {p.get('requested')}",
        f"detected:   {p['detected'].get('compositor')}"
        + (f" (plasma {p['detected']['plasma_version']})" if p["detected"].get("plasma_version") else "")
        + (f" session={p['detected']['session_type']}" if p["detected"].get("session_type") else ""),
        f"evidence:   {'; '.join(p['detected'].get('evidence') or [])}",
        f"active:     {p.get('active')}  ({p.get('reason')})",
        f"available:  {p.get('available')}",
        "capabilities:",
    ]
    for cap in CAPABILITIES:
        ok = p.get("capabilities", {}).get(cap)
        lines.append(f"  {'yes' if ok else 'no ':<3} {cap}")
    tools = p.get("tools") or {}
    if tools:
        lines.append("tools:")
        for k, v in tools.items():
            lines.append(f"  {k}: {v}")
    plan = p.get("plan") or {}
    if plan:
        lines.append("plan (argv the backend would run):")
        for k, v in plan.items():
            if isinstance(v, list):
                for argv in v:
                    lines.append(f"  {k}: {argv}")
            else:
                lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m utter.context.compositor [--json] [--compositor NAME] [--print-plan]``."""
    import argparse
    import json

    ap = argparse.ArgumentParser(prog="utter.context.compositor",
                                 description="Show the detected compositor, the active backend and "
                                             "the commands it would run (dry-run; touches nothing).")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--compositor", default=None, help="force a backend (auto|niri|kwin)")
    ap.add_argument("--print-plan", action="store_true",
                    help="include the argv / D-Bus calls for every capability (default on)")
    args = ap.parse_args(argv)
    p = probe(args.compositor)
    if args.json:
        print(json.dumps(p, indent=2, sort_keys=True))
    else:
        print(format_probe(p))
    return 0


__all__ = [
    "NIRI", "KWIN", "UNKNOWN", "AUTO", "BACKENDS", "CAPABILITIES", "ENV_OVERRIDE",
    "CAP_FOCUSED_WINDOW", "CAP_LIST_WINDOWS", "CAP_ACTIVATE", "CAP_CLOSE", "CAP_MINIMIZE",
    "CAP_MAXIMIZE", "CAP_MOVE_TO_WORKSPACE", "CAP_SWITCH_WORKSPACE", "CAP_SCREENSHOT",
    "CAP_COMPOSITOR_ACTION", "CompositorUnsupported", "Outcome", "Detection", "Resolution",
    "detect", "configured", "resolve", "backend_for", "active", "active_name", "probe",
    "format_probe", "reset_cache", "normalize_name", "main",
]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
