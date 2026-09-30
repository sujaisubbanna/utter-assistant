#!/usr/bin/env python3
"""zen_bidi - minimal CLI over the Firefox/Zen WebDriver BiDi Remote Agent.

Zen (a Firefox fork) exposes a WebDriver BiDi endpoint at
``ws://127.0.0.1:<port>/session`` ONLY when it is started with
``--remote-debugging-port=<port>`` (default 9222).

Commands
--------
    ping                 -> "ok" (exit 0) if the agent answers, else exit 2
    list                 -> JSON array of top-level tabs
    find <substr>        -> JSON of first tab whose url/title matches, else null
    activate <context>   -> activate (focus window + select tab)

Output on stdout is strictly JSON for ``list``/``find``; diagnostics go to
stderr. Only the stdlib + ``websockets`` are required.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

from websockets.sync.client import connect as ws_connect

DEFAULT_PORT = 9222
TIMEOUT = 5.0  # hard timeout for connect and for each command


def _log(msg: str) -> None:
    print(f"zen_bidi: {msg}", file=sys.stderr)


def _port() -> int:
    raw = os.environ.get("ZEN_BIDI_PORT", str(DEFAULT_PORT)).strip()
    try:
        return int(raw)
    except ValueError:
        _log(f"invalid ZEN_BIDI_PORT={raw!r}, using {DEFAULT_PORT}")
        return DEFAULT_PORT


def _ws_url(port: int) -> str:
    return f"ws://127.0.0.1:{port}/session"


class Agent:
    """One short-lived BiDi session. Use as a context manager."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.ws = None
        self._id = 0
        self.session_open = False

    # -- lifecycle ------------------------------------------------------
    def __enter__(self) -> "Agent":
        # proxy=None: never route loopback through an HTTP(S) proxy.
        self.ws = ws_connect(
            _ws_url(self.port),
            open_timeout=TIMEOUT,
            close_timeout=TIMEOUT,
            proxy=None,
            max_size=None,
        )
        self._call("session.new", {"capabilities": {}})
        self.session_open = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.session_open:
            try:
                self._call("session.end", {})
            except Exception as e:  # best effort
                _log(f"session.end failed: {e}")
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass

    # -- rpc ------------------------------------------------------------
    def _call(self, method: str, params: dict) -> dict:
        self._id += 1
        msg_id = self._id
        assert self.ws is not None
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        deadline = time.monotonic() + TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{method} timed out after {TIMEOUT}s")
            raw = self.ws.recv(timeout=remaining)
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(msg, dict) or msg.get("id") != msg_id:
                continue  # event or unrelated reply
            if "error" in msg:
                err = msg["error"]
                if isinstance(err, dict):
                    raise RuntimeError(
                        f"{method} error: {err.get('error', 'unknown')}: "
                        f"{err.get('message', '')}".strip()
                    )
                raise RuntimeError(f"{method} error: {err}")
            return msg.get("result", {}) or {}

    # -- commands -------------------------------------------------------
    def get_tree(self) -> list[dict]:
        result = self._call("browsingContext.getTree", {})
        contexts = result.get("contexts", []) or []
        return _flatten_top_level(contexts)

    def activate(self, context: str) -> None:
        self._call("browsingContext.activate", {"context": context})


def _flatten_top_level(contexts: list[dict]) -> list[dict]:
    """Recurse ``children``; keep only top-level tabs (parent is null/absent)."""
    out: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("parent") is None:
                out.append(
                    {
                        "context": node.get("context"),
                        "url": node.get("url", ""),
                        "title": node.get("title", "") or "",
                        "window": node.get("clientWindow"),
                    }
                )
            children = node.get("children")
            if isinstance(children, list):
                walk(children)

    walk(contexts)
    return out


def _find(tabs: list[dict], substr: str) -> Optional[dict]:
    """Best matching tab: prefer keyword in the hostname, deprioritise
    login/consent/accounts subdomains, prefer a bare root path."""
    from urllib.parse import urlparse

    needle = substr.casefold()
    best: Optional[dict] = None
    best_score = None
    for tab in tabs:
        url = (tab.get("url") or "")
        title = (tab.get("title") or "")
        hay = f"{url}\n{title}".casefold()
        if needle not in hay:
            continue
        host = (urlparse(url).hostname or "").casefold()
        path = urlparse(url).path or "/"
        score = 0
        if needle in host:
            score += 3
        if host.startswith("www."):
            score += 1
        if any(p in host for p in ("accounts.", "login.", "consent.", "secure.")):
            score -= 4
        if path in ("", "/"):
            score += 1
        if best_score is None or score > best_score:
            best, best_score = tab, score
    return best


def cmd_ping(port: int) -> int:
    try:
        with Agent(port):
            pass
    except Exception as e:
        _log(f"ping failed: {e}")
        return 2
    print("ok")
    return 0


def cmd_list(port: int) -> int:
    try:
        with Agent(port) as agent:
            tabs = agent.get_tree()
    except Exception as e:
        _log(f"list failed: {e}")
        print("[]")
        return 1
    print(json.dumps(tabs))
    return 0


def cmd_find(port: int, substr: str) -> int:
    try:
        with Agent(port) as agent:
            tab = _find(agent.get_tree(), substr)
    except Exception as e:
        _log(f"find failed: {e}")
        print("null")
        return 0  # spec: find always exits 0
    print(json.dumps(tab) if tab is not None else "null")
    return 0


def cmd_activate(port: int, context: str) -> int:
    try:
        with Agent(port) as agent:
            agent.activate(context)
    except Exception as e:
        print(f"error: {e}")
        return 1
    print("ok")
    return 0


def cmd_activate_match(port: int, substr: str) -> int:
    """Find and activate in ONE session (context ids are not stable across sessions)."""
    tab = None
    try:
        with Agent(port) as agent:
            tab = _find(agent.get_tree(), substr)
            if tab is not None:
                agent.activate(tab["context"])
    except Exception as e:
        print(f"error: {e}")
        return 1
    print(json.dumps(tab) if tab is not None else "null")
    return 0


def usage() -> int:
    print(
        "usage: zen_bidi.py {ping|list|find <substr>|activate <context>|activate-match <substr>}",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return usage()
    cmd = argv[1]
    port = _port()
    if cmd == "ping":
        return cmd_ping(port)
    if cmd == "list":
        return cmd_list(port)
    if cmd == "find":
        if len(argv) < 3:
            return usage()
        return cmd_find(port, argv[2])
    if cmd == "activate":
        if len(argv) < 3:
            return usage()
        return cmd_activate(port, argv[2])
    if cmd == "activate-match":
        if len(argv) < 3:
            return usage()
        return cmd_activate_match(port, argv[2])
    return usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
