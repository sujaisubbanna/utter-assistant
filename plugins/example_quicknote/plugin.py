#!/usr/bin/env python3
"""example_quicknote — a local "quick capture" action plugin (stdlib only).

This is a small but real demonstration plugin: one action op that appends a
timestamped line to a dated markdown inbox file on disk. It exists to show how
a plugin extends the *capability* surface of utter without ever touching the
trust boundary:

  * it declares exactly one op, ``action.quicknote.append``;
  * it reads **only** its own ``args.text`` and the ``XDG_DATA_HOME`` env var —
    it does not read the screen, clipboard, filesystem or any other source, so
    it can never author an argument from untrusted content (TRUST.md §1);
  * ``needs_confirm`` is only a hint; the runner owns policy and confirmation.

Wire contract (frozen — do not change the envelope), protocol/PROTOCOL.md:
  Content-Length: <bytes>\\r\\n\\r\\n<utf-8 json>,  JSON-RPC 2.0, one per frame.
Transport: stdio. Terminates on stdin EOF.

Handshake sequence: protocol.hello -> plugin.describe -> plugin.health.
The framing helpers follow the worked example in docs/PLUGINS.md §7; the only
adjustment is parsing the ``Content-Length`` header case-insensitively (the
independent conformance client and the runner both send ``Content-Length``).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any, Optional

# -- protocol constants ------------------------------------------------------ #
PROTOCOL = "1.0"
ABI = 1
PLUGIN_NAME = "example_quicknote"
PLUGIN_VERSION = "0.1.0"
PLUGIN_KIND = "action"

# ``experimental/`` is the collision-free extension namespace and needs no
# registry entry; ``action.quicknote@1`` is also declared in
# protocol/capabilities.json. This plugin needs nothing from the runner.
PROVIDES = [
    "action.quicknote@1",
    "experimental/example_quicknote@1",
]
REQUIRES: list[str] = []
PERMISSIONS = ["filesystem.write"]

OP = "action.quicknote.append"

#: Reject absurdly large captures so a runaway STT never writes a huge line.
MAX_TEXT = 2000

#: The single op this plugin advertises, with a JSON-Schema-ish arg shape.
OPS = [
    {
        "op": OP,
        "side_effect": "local_write",
        "needs_confirm": False,
        "args": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    }
]


class RpcFault(Exception):
    """A JSON-RPC error we want to report with a specific code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# framing (stdio) — see docs/PLUGINS.md §7
# --------------------------------------------------------------------------- #
def read_message(stream: Any) -> Optional[Any]:
    """Read one Content-Length framed JSON message; None on clean EOF."""
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
    # Case-insensitive: peers send "Content-Length".
    length = int(header.lower().split(b"content-length:")[1].split(b"\r\n")[0])
    body = stream.read(length)
    return json.loads(body.decode("utf-8")) if body else None


def write_message(stream: Any, obj: Any) -> None:
    """Write one Content-Length framed JSON message (compact UTF-8)."""
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    stream.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stream.flush()


# --------------------------------------------------------------------------- #
# the inbox
# --------------------------------------------------------------------------- #
def inbox_dir() -> str:
    """Default: ``$XDG_DATA_HOME/utter/quicknote`` (fallback ``~/.local/share``)."""
    base = os.environ.get("XDG_DATA_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "utter", "quicknote")


def append_note(text: str) -> tuple[str, str]:
    """Append ``- [YYYY-MM-DDTHH:MM] <text>`` to ``<inbox>/<YYYY-MM>.md``.

    Returns ``(path, line)``. Creates the directory and file as needed.
    """
    now = datetime.now()
    line = f"- [{now:%Y-%m-%dT%H:%M}] {text}"
    path = os.path.join(inbox_dir(), f"{now:%Y-%m}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Append is atomic enough for a single-user inbox; no shell involved.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path, line


def _validated_text(params: dict) -> str:
    """Pull and validate ``args.text``; raises RpcFault(-32602) on bad input."""
    args = params.get("args")
    if not isinstance(args, dict):
        raise RpcFault(-32602, f"{OP} requires an 'args' object")
    raw = args.get("text")
    if not isinstance(raw, str):
        raise RpcFault(-32602, f"{OP} requires a string 'text'")
    # Collapse embedded newlines so one capture is exactly one markdown bullet.
    text = raw.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        raise RpcFault(-32602, "text must not be empty")
    if len(text) > MAX_TEXT:
        raise RpcFault(-32602, f"text too long ({len(text)} > {MAX_TEXT} chars)")
    return text


# --------------------------------------------------------------------------- #
# methods
# --------------------------------------------------------------------------- #
def handle(method: str, params: dict) -> Any:
    if method == "protocol.hello":
        return {
            "protocol": PROTOCOL,
            "abi": ABI,
            "plugin": {
                "name": PLUGIN_NAME,
                "version": PLUGIN_VERSION,
                "kind": PLUGIN_KIND,
            },
            "transport": "stdio",
            "provides": list(PROVIDES),
            "requires": list(REQUIRES),
            "permissions": list(PERMISSIONS),
        }

    if method == "plugin.describe":
        return {
            "methods": [
                "protocol.hello", "plugin.describe", "plugin.health",
                "action.capabilities", "action.invoke",
            ],
            "streams": [],
        }

    if method == "plugin.health":
        return {"status": "ok", "detail": f"{PLUGIN_NAME} ready ({inbox_dir()})"}

    if method == "action.capabilities":
        return {"ops": [dict(op) for op in OPS]}

    if method == "action.invoke":
        op = str(params.get("op") or "")
        if op != OP:
            raise RpcFault(-32602, f"unknown op: {op!r}")
        text = _validated_text(params)
        path, line = append_note(text)
        return {"ok": True, "op": op, "path": path, "line": line}

    raise RpcFault(-32601, f"method not found: {method}")


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main() -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    while True:
        msg = read_message(stdin)
        if msg is None:
            return 0  # EOF -> terminate (the runner closes stdin to drain)
        if not isinstance(msg, dict) or msg.get("id") is None:
            continue  # notifications / malformed frames get no reply
        try:
            result = handle(str(msg.get("method") or ""), msg.get("params") or {})
            write_message(stdout, {"jsonrpc": "2.0", "id": msg["id"], "result": result})
        except RpcFault as exc:
            write_message(stdout, {
                "jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": exc.code, "message": exc.message},
            })
        except Exception as exc:  # noqa: BLE001 - standard plugin error envelope
            write_message(stdout, {
                "jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": -32000, "message": f"plugin error: {exc}"},
            })


if __name__ == "__main__":
    raise SystemExit(main())
