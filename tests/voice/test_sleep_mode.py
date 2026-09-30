#!/usr/bin/env python3
"""Sleep mode: the trigger phrase stops the model services and unloads speech;
waking reloads speech first and starts the services without blocking.

Usage::

    .venv-agent/bin/python tests/voice/test_sleep_mode.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.sleep import SleepController  # noqa: E402

ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


with tempfile.TemporaryDirectory() as tmp:
    calls: list = []
    events: list = []
    path = Path(tmp) / "sleep.json"
    sc = SleepController(triggers=["go to sleep", "Nap time!"], services=["utter-vision", "utter-planner"],
                         systemctl=lambda args: calls.append(args), path=path)
    sc.on_unload(lambda: events.append("unload"))
    sc.on_reload(lambda: events.append("reload"))

    check("matches 'Go to sleep.'", sc.matches("Go to sleep."))
    check("matches custom 'nap time'", sc.matches("nap time"))
    check("ignores 'go to sleep now'", not sc.matches("go to sleep now"))
    check("ignores ordinary commands", not sc.matches("open youtube"))

    sc.sleep()
    check("asleep after sleep()", sc.asleep)
    check("stops both services", calls == [["stop", "utter-vision.service"], ["stop", "utter-planner.service"]])
    check("unloads speech", events == ["unload"])
    check("publishes asleep=true", json.loads(path.read_text())["asleep"] is True)

    calls.clear()
    sc.sleep()
    check("sleep() again is a no-op", calls == [])

    sc.wake()
    check("awake after wake()", not sc.asleep)
    check("reloads speech before starting services", events == ["unload", "reload"])
    check("starts services without blocking",
          calls == [["start", "--no-block", "utter-vision.service"], ["start", "--no-block", "utter-planner.service"]])
    check("publishes asleep=false", json.loads(path.read_text())["asleep"] is False)
    check("wake() when awake returns False", sc.wake() is False)

    off = SleepController(enabled=False, systemctl=lambda a: None, path=path)
    check("disabled: trigger ignored", not off.matches("go to sleep"))

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
