#!/usr/bin/env python3
"""The overlay state records which push-to-talk mode is active, so the panel
can show assistant and dictation differently (dictation used to show nothing).

Usage::

    .venv-agent/bin/python tests/voice/test_osd_modes.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.voice.osd import OsdEmitter  # noqa: E402


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "osd.json"
        cfg = SimpleNamespace(enabled=True, stream=False, dismiss_ms=5000)
        em = OsdEmitter(cfg, enabled=True, path=path)
        for mode in ("dictation", "assistant"):
            em.listening(mode)
            doc = read(path)
            good = doc["state"] == "listening" and doc["mode"] == mode
            print(f"{'ok ' if good else 'BAD'} listening({mode}) -> {doc['state']}/{doc['mode']}")
            ok &= good
            em.final("hello", True)
            doc = read(path)
            good = doc["state"] == "final" and doc["mode"] == mode and doc["activated"] is True
            print(f"{'ok ' if good else 'BAD'} final after {mode} -> {doc['state']}/{doc['mode']}")
            ok &= good
        em.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
