#!/usr/bin/env python3
"""Regression: the push-to-talk rescan must not leak input-device descriptors.

Every idle rescan re-opens the matching keyboards. Before the fix the loop
compared the fresh fd against the watched ones (never equal), so each rescan
kept one extra /dev/input/event* open per keyboard until the process hit
EMFILE ("Too many open files") and audio capture died.

Usage::

    .venv-agent/bin/python tests/voice/test_hotkey_rescan.py
"""
from __future__ import annotations

import itertools
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.voice import hotkey  # noqa: E402

_fds = itertools.count(100)
OPEN: set = set()


class FakeDevice:
    def __init__(self, path: str) -> None:
        self.path = path
        self.name = f"fake {path}"
        self.fd = next(_fds)
        OPEN.add(self.fd)

    def fileno(self) -> int:
        return self.fd

    def close(self) -> None:
        OPEN.discard(self.fd)

    def read(self):
        return []


def main() -> int:
    keyboards = ["/dev/input/event3", "/dev/input/event7"]
    stop = threading.Event()
    peak = {"open": 0, "rescans": 0}

    def fake_select(rlist, _w, _x, _timeout):
        peak["open"] = max(peak["open"], len(OPEN))
        peak["rescans"] += 1
        if peak["rescans"] >= 50:
            stop.set()
        return [], [], []

    hotkey.evdev = object()  # "installed"
    hotkey.resolve_keycode = lambda _name: 110
    hotkey.find_ptt_devices = lambda *_a, **_k: [FakeDevice(p) for p in keyboards]
    hotkey.select.select = fake_select

    hotkey.listen(lambda: None, lambda: None, key_name="KEY_INSERT", stop_event=stop, rescan_interval=0)

    ok_peak = peak["open"] <= len(keyboards)
    ok_closed = not OPEN
    print(f"rescans={peak['rescans']} peak_open={peak['open']} left_open={len(OPEN)}")
    print("PASS" if ok_peak and ok_closed else "FAIL: descriptors leak across rescans")
    return 0 if ok_peak and ok_closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
