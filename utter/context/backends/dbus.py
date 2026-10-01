"""Session D-Bus helpers for the KWin backend (stdlib only, no ``shell=True``).

Three parts, split for readability:

1. **Outgoing calls through a CLI tool** — :class:`Call` builds the argv for
   ``gdbus`` (preferred), ``qdbus6``/``qdbus`` or ``dbus-send`` and
   :func:`call` runs it and parses the reply. The argv is always a list; the
   parsers understand each tool's text output well enough for the scalar,
   string, variant and ``a(uss)`` replies KWin gives us.

2. **Reply-text parsing** — the GVariant / qdbus / dbus-send parsers live in
   :mod:`utter.context.backends.dbus_text` and are re-exported here.

3. **A tiny inbound receiver** — :class:`LiteBus` lives in
   :mod:`utter.context.backends.dbus_wire` (with :func:`session_bus_address`)
   and is re-exported here.

Nothing in this module talks to KWin itself; see ``kwin.py`` for the calls.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from utter.context.backends.dbus_text import (
    parse_dbus_send,
    parse_gvariant,
    parse_qdbus,
    parse_reply,
    tool_kind,
)
from utter.context.backends.dbus_wire import (
    LiteBus,
    Message,
    build_message,
    marshal_body,
    parse_message,
    session_bus_address,
)

TOOL_ENV = "UTTER_DBUS_TOOL"
TOOLS = ("gdbus", "qdbus6", "qdbus", "dbus-send")
_TIMEOUT = 4.0


def pick_tool(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """First available CLI tool, or the ``UTTER_DBUS_TOOL`` override (tests)."""
    e = os.environ if env is None else env
    forced = (e.get(TOOL_ENV) or "").strip()
    if forced:
        return forced
    for name in TOOLS:
        if shutil.which(name):
            return name
    return None


# --------------------------------------------------------------------------- #
# argument encoding
# --------------------------------------------------------------------------- #
def gvariant_literal(value: Any) -> str:
    """Encode a Python value as a GVariant text literal for ``gdbus call``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, Variant):
        return f"<{gvariant_literal(value.value)}>"
    if isinstance(value, dict):
        items = ", ".join(f"{gvariant_literal(k)}: {gvariant_literal(v)}" for k, v in value.items())
        return "{" + items + "}" if items else "@a{sv} {}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(gvariant_literal(v) for v in value) + "]"
    raise TypeError(f"cannot encode {type(value).__name__} for gdbus")


def dbus_send_arg(value: Any) -> str:
    if isinstance(value, bool):
        return f"boolean:{'true' if value else 'false'}"
    if isinstance(value, int):
        return f"int32:{value}"
    if isinstance(value, float):
        return f"double:{value}"
    if isinstance(value, str):
        return f"string:{value}"
    raise TypeError(f"dbus-send cannot encode {type(value).__name__} (use gdbus)")


@dataclass(frozen=True)
class Variant:
    """Marks a value to be wrapped as ``<...>`` in ``a{sv}`` dictionaries."""
    value: Any


@dataclass(frozen=True)
class Call:
    dest: str
    path: str
    iface: str
    method: str
    args: tuple = ()

    def argv(self, tool: str) -> list[str]:
        kind = tool_kind(tool)
        if kind == "qdbus":
            return [tool, self.dest, self.path, f"{self.iface}.{self.method}",
                    *[_qdbus_arg(a) for a in self.args]]
        if kind == "dbus-send":
            return [tool, "--session", "--print-reply", f"--dest={self.dest}", self.path,
                    f"{self.iface}.{self.method}", *[dbus_send_arg(a) for a in self.args]]
        return [tool, "call", "--session", "--dest", self.dest, "--object-path", self.path,
                "--method", f"{self.iface}.{self.method}", *[gvariant_literal(a) for a in self.args]]

    def describe(self) -> str:
        return f"{self.dest} {self.path} {self.iface}.{self.method}({', '.join(repr(a) for a in self.args)})"


def _qdbus_arg(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple, Variant)):
        raise TypeError("qdbus cannot encode containers (use gdbus)")
    return str(value)


def prop_get(dest: str, path: str, iface: str, name: str) -> Call:
    return Call(dest, path, "org.freedesktop.DBus.Properties", "Get", (iface, name))


@dataclass
class Reply:
    ok: bool
    value: Any = None
    argv: Optional[list[str]] = None
    error: str = ""


def dry_run(env: Optional[Mapping[str, str]] = None) -> bool:
    e = os.environ if env is None else env
    return (e.get("UTTER_DRY_RUN") or "").strip().lower() in ("1", "true", "yes", "on")


def call(c: Call, tool: Optional[str] = None, timeout: float = _TIMEOUT) -> Reply:
    """Run ``c`` through a CLI tool. Never raises; ``UTTER_DRY_RUN=1`` only plans."""
    tool = tool or pick_tool()
    if tool is None:
        return Reply(False, None, None, "no D-Bus CLI tool (install glib2 for gdbus, or qt6-tools for qdbus6)")
    try:
        argv = c.argv(tool)
    except TypeError as exc:
        return Reply(False, None, None, str(exc))
    if dry_run():
        return Reply(True, None, argv, "dry-run")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return Reply(False, None, argv, str(exc))
    if proc.returncode != 0:
        return Reply(False, None, argv, (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}")
    try:
        value = parse_reply(tool, proc.stdout) if proc.stdout.strip() else None
    except ValueError as exc:
        return Reply(True, proc.stdout, argv, f"unparsed reply: {exc}")
    return Reply(True, value, argv, "")


__all__ = [
    "TOOL_ENV", "TOOLS", "pick_tool", "tool_kind", "gvariant_literal", "dbus_send_arg", "Variant", "Call",
    "prop_get", "parse_gvariant", "parse_qdbus", "parse_dbus_send", "parse_reply", "Reply", "call", "dry_run",
    "session_bus_address", "build_message", "marshal_body", "parse_message", "Message", "LiteBus",
]
