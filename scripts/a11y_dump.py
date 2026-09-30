#!/usr/bin/env python3
"""Dump an application's AT-SPI accessibility tree as JSON.

Debug helper for the T1 (accessibility) tier. Run under .venv-agent, which is
the only interpreter with `gi` / `Atspi` available:

    .venv-agent/bin/python \
        scripts/a11y_dump.py [APP_ID] [--max-nodes 400] [--timeout 8]

With no APP_ID the focused window's application is used. A JSON summary is
written to stderr and the (possibly partial) tree to stdout. Exit status is 1
when the app does not expose an AT-SPI tree (e.g. Electron/Chromium without
--force-renderer-accessibility, or a browser with accessibility disabled).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _walk(root):
    if root is None:
        return
    yield from root.walk()


def _stats(root) -> tuple[int, int, dict[str, int]]:
    count = 0
    depth = 0
    roles: dict[str, int] = {}
    stack = [(root, 0)] if root is not None else []
    while stack:
        node, d = stack.pop()
        count += 1
        depth = max(depth, d)
        roles[node.role] = roles.get(node.role, 0) + 1
        for child in node.children:
            stack.append((child, d + 1))
    return count, depth, roles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump an app's AT-SPI tree as JSON.")
    parser.add_argument("app", nargs="?", default=None,
                        help="application id/name; defaults to the focused window's app")
    parser.add_argument("--max-nodes", type=int, default=400)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--sample", type=int, default=15,
                        help="named nodes to include in the stderr summary")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    from utter.context import atspi

    t0 = time.perf_counter()
    root = atspi.dump_tree(args.app, max_nodes=args.max_nodes, timeout_s=args.timeout)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    count, depth, roles = _stats(root)
    sample = [
        {"role": el.role, "name": el.name, "actions": el.actions}
        for el in _walk(root) if el.name
    ][: max(0, args.sample)]

    summary = {
        "app": args.app,
        "found": root is not None,
        "nodes": count,
        "depth": depth,
        "elapsed_ms": round(elapsed_ms, 1),
        "roles": dict(sorted(roles.items(), key=lambda kv: -kv[1])),
        "sample": sample,
    }
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)

    if root is None:
        print(json.dumps({"app": args.app, "found": False, "nodes": 0}))
        return 1

    payload = {
        "app": args.app,
        "found": True,
        "nodes": count,
        "depth": depth,
        "elapsed_ms": round(elapsed_ms, 1),
        "tree": dataclasses.asdict(root),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
