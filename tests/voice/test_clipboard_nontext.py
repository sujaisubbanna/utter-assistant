#!/usr/bin/env python3
"""Regression: a non-text clipboard (e.g. a copied screenshot) must not raise.

Before the fix, PNG bytes from `wl-paste` raised UnicodeDecodeError out of
get_clipboard(), which aborted the whole voice command.

Usage::

    .venv-agent/bin/python tests/voice/test_clipboard_nontext.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.context import clipboard  # noqa: E402

PNG = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0x89]) + b'PNG\\r\\n')"]
TEXT = [sys.executable, "-c", "print('hello', end='')"]


def main() -> int:
    ok = True
    clipboard._COMMANDS = (PNG,)
    try:
        value = clipboard.get_clipboard()
        print(f"image clipboard -> {value!r} (no exception)")
    except Exception as exc:  # the bug
        print(f"FAIL: raised {type(exc).__name__}: {exc}")
        ok = False
    clipboard._COMMANDS = (TEXT,)
    value = clipboard.get_clipboard()
    ok = ok and value == "hello"
    print(f"text clipboard -> {value!r}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
