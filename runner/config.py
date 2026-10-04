"""Runner configuration: loading and validation (TOML -> RunnerConfig).

Extracted from ``runner.host`` (behavior-preserving); ``runner.host`` re-exports
these names for existing importers.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import security
from .plugin import PluginConfig


@dataclass
class RunnerConfig:
    plugins: list[PluginConfig] = field(default_factory=list)
    socket_path: str = ""
    allow_binaries: list[str] = field(default_factory=list)
    socket_allow_same_uid: bool | None = None
    socket_token: str = ""
    socket_section_present: bool = False
    security_enforce: bool = False
    enabled_ops: list[str] = field(default_factory=list)
    disabled_ops: list[str] = field(default_factory=list)
    disabled_plugins: list[str] = field(default_factory=list)
    handle_root: str = ""
    handle_ttl: float = 300.0
    rpc_timeout_ms: int = 10000
    confirm_timeout_ms: int = 30000
    lossy_queue: int = 256
    credit_window: int = 64


def load_config(path: str | Path) -> RunnerConfig:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    cfg = RunnerConfig()
    # `[plugins] disabled` is the settings-app opt-out; it overrides each
    # `[[plugin]] enabled` so the GUI can gate plugins without rewriting the
    # array-of-tables.
    plugins_cfg = data.get("plugins", {}) or {}
    cfg.disabled_plugins = [str(p) for p in plugins_cfg.get("disabled", []) or []]
    for raw in data.get("plugin", []):
        entry = raw.get("entrypoint", raw.get("argv")) or []
        plugin_id = str(raw.get("id", ""))
        cfg.plugins.append(
            PluginConfig(
                id=plugin_id,
                kind=str(raw.get("kind", "action")),
                runtime=str(raw.get("runtime", "subprocess")),
                transport=str(raw.get("transport", "stdio")),
                entrypoint=[str(a) for a in entry],
                permissions=[str(p) for p in raw.get("permissions", []) or []],
                provides=[str(p) for p in raw.get("provides", []) or []],
                requires=[str(p) for p in raw.get("requires", []) or []],
                enabled=bool(raw.get("enabled", True)) and plugin_id not in cfg.disabled_plugins,
                cwd=str(raw.get("cwd", "") or ""),
                env={str(k): str(v) for k, v in (raw.get("env", {}) or {}).items()},
            )
        )
    runner = data.get("runner", {})
    cfg.socket_path = str(runner.get("socket_path", "") or "")
    cfg.rpc_timeout_ms = int(runner.get("rpc_timeout_ms", cfg.rpc_timeout_ms))
    cfg.handle_ttl = float(runner.get("handle_ttl", cfg.handle_ttl))
    cfg.handle_root = str(runner.get("handle_root", "") or "")
    cfg.confirm_timeout_ms = int(runner.get("confirm_timeout_ms", cfg.confirm_timeout_ms))
    cfg.lossy_queue = int(runner.get("lossy_queue", cfg.lossy_queue))
    cfg.credit_window = int(runner.get("credit_window", cfg.credit_window))
    if "socket" in data:
        sock = data.get("socket") or {}
        cfg.socket_section_present = True
        cfg.allow_binaries = [str(b) for b in sock.get("allow_binaries", []) or []]
        if "allow_same_uid" in sock:
            cfg.socket_allow_same_uid = bool(sock.get("allow_same_uid"))
        cfg.socket_token = str(sock.get("token", "") or "")
    sec = data.get("security", {})
    cfg.security_enforce = bool(sec.get("enforce", False))
    pol = data.get("policy", {})
    cfg.enabled_ops = [str(o) for o in pol.get("enabled_ops", []) or []]
    cfg.disabled_ops = [str(o) for o in pol.get("disabled_ops", []) or []]
    return cfg


def check_config(path: str | Path) -> tuple[bool, list[str]]:
    try:
        cfg = load_config(path)
    except Exception as exc:  # noqa: BLE001
        return False, [f"failed to load config: {exc}"]
    msgs: list[str] = []
    if not cfg.plugins:
        msgs.append("warning: no [[plugin]] entries")
    seen: set[str] = set()
    for p in cfg.plugins:
        if not p.id:
            msgs.append("error: plugin without id")
        elif p.id in seen:
            msgs.append(f"error: duplicate plugin id {p.id!r}")
        seen.add(p.id)
        if p.runtime != "subprocess":
            msgs.append(f"warning: plugin {p.id}: runtime {p.runtime!r} unsupported (subprocess only)")
        if p.transport not in ("stdio", "connect", "listen"):
            msgs.append(f"error: plugin {p.id}: unknown transport {p.transport!r}")
        if not p.entrypoint:
            msgs.append(f"error: plugin {p.id}: empty entrypoint")
        if p.cwd and not Path(p.cwd).is_dir():
            msgs.append(f"warning: plugin {p.id}: cwd {p.cwd!r} is not a directory")
    if cfg.socket_section_present and not (
        cfg.allow_binaries or cfg.socket_token or cfg.socket_allow_same_uid
    ):
        msgs.append(
            "warning: [socket] has no allow_binaries/token/allow_same_uid; "
            "default-deny will reject all clients"
        )
    if cfg.security_enforce and not security.detect_wrapper().enforced:
        msgs.append("warning: [security] enforce=true but no systemd-run/bwrap; permissions advisory")
    errors = [m for m in msgs if m.startswith("error")]
    return (not errors), msgs
