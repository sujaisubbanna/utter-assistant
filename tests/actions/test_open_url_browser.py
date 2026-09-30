#!/usr/bin/env python3
"""Regression: open_url sends the URL to the browser that is already open, so
it lands as a tab in the window on screen, instead of always handing it to
xdg-open (which may prompt or pick a different browser). With no browser open
the desktop default (xdg-open) decides.

Usage::

    .venv-agent/bin/python tests/actions/test_open_url_browser.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.actions import launch  # noqa: E402

spawned: list = []
launch._spawn = lambda argv: (spawned.append(argv) or True, " ".join(argv))
launch._browser_argv = lambda app_id: ["/usr/bin/example-browser"] if app_id == "example" else None


def check(app_id, url, expect) -> bool:
    spawned.clear()
    launch.open_url(url, browser_app_id=app_id)
    got = spawned[-1] if spawned else None
    ok = got == expect
    print(f"{'ok ' if ok else 'BAD'} open={app_id or '-':8} {url:26} -> {got}")
    return ok


results = [
    check("example", "https://www.youtube.com", ["/usr/bin/example-browser", "https://www.youtube.com"]),
    check(None, "https://www.youtube.com", ["xdg-open", "https://www.youtube.com"]),
    check("unknown", "https://www.youtube.com", ["xdg-open", "https://www.youtube.com"]),
    check("example", "mailto:a@b.c", ["xdg-open", "mailto:a@b.c"]),
    check("example", "youtube.com", ["/usr/bin/example-browser", "https://youtube.com"]),
]
print("PASS" if all(results) else "FAIL")
raise SystemExit(0 if all(results) else 1)
