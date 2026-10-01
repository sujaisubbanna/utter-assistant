#!/usr/bin/env python3
"""Idle sleep: the watcher puts Utter to sleep after ``idle_minutes`` without
Utter activity, resets on activity, never fires while busy or disabled, and
goes through the same SleepController as the spoken trigger.

Driven entirely by a fake monotonic clock: nothing here sleeps.

Usage::

    .venv-agent/bin/python tests/voice/test_idle_sleep.py
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.config import load_config  # noqa: E402
from utter.sleep import IdleWatcher, SleepController  # noqa: E402

logging.basicConfig(level=logging.WARNING)
ok = True


def check(name: str, cond: bool) -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def make(tmp: str, **kw):
    calls: list = []
    path = Path(tmp) / "sleep.json"
    sc = SleepController(systemctl=lambda args: calls.append(list(args)), path=path)
    clock = FakeClock()
    w = IdleWatcher(sc, clock=clock, **kw)
    return sc, w, clock, calls, path


with tempfile.TemporaryDirectory() as tmp:
    # -- fires after the timeout ------------------------------------------------
    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=15)
    check("not due right after start", w.poll() is False and not sc.asleep)
    clock.advance(14 * 60 + 59)
    check("not due one second early", w.poll() is False and not sc.asleep)
    check("remaining() counts down", w.remaining() == 1.0)
    clock.advance(1)
    check("fires exactly at idle_minutes", w.poll() is True and sc.asleep)
    check("fired through SleepController (services stopped)",
          calls == [["stop", "utter-vision.service"], ["stop", "utter-planner.service"]])
    check("state file identical to voice sleep (asleep=true, no reason field)",
          json.loads(path.read_text()).get("asleep") is True
          and set(json.loads(path.read_text())) == {"asleep", "services", "ts"})
    clock.advance(60 * 60)
    check("does not fire again while asleep", w.poll() is False and w.fired == 1)
    check("remaining() is None while asleep", w.remaining() is None)

    # -- wake restarts the countdown -----------------------------------------
    calls.clear()
    sc.wake()  # what a PTT key press does
    check("wake() reloads via the existing path",
          calls == [["start", "--no-block", "utter-vision.service"],
                    ["start", "--no-block", "utter-planner.service"]])
    check("wake counts as activity: full timeout again", w.remaining() == 15 * 60)
    clock.advance(10 * 60)
    check("not due 10 min after wake", w.poll() is False and not sc.asleep)
    clock.advance(5 * 60)
    check("fires 15 min after wake", w.poll() is True and sc.asleep and w.fired == 2)

    # -- resets on activity -------------------------------------------------------
    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=15)
    for i in range(6):
        clock.advance(10 * 60)
        w.touch("ptt")
        check(f"activity at {10 * (i + 1)} min keeps it awake", w.poll() is False and not sc.asleep)
    clock.advance(15 * 60 - 1)
    check("still awake just before timeout after last touch", w.poll() is False)
    clock.advance(1)
    check("fires 15 min after the last activity", w.poll() is True and sc.asleep)

    # -- no-op when on_idle is false ----------------------------------------------
    sc, w, clock, calls, path = make(tmp, enabled=False, minutes=15)
    clock.advance(24 * 60 * 60)
    check("disabled: never fires", w.poll() is False and not sc.asleep and calls == [])
    check("disabled: remaining() is None", w.remaining() is None)
    check("disabled: start() does not spawn a thread", w.start() is None)

    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=0)
    clock.advance(24 * 60 * 60)
    check("idle_minutes=0 is treated as disabled", w.poll() is False and not w.enabled)

    # -- does not fire while speak/listen is in progress -------------------------
    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=2)
    w.begin("listen")
    clock.advance(5 * 60)
    check("held 'listen' token blocks the timer past the timeout", w.poll() is False and not sc.asleep)
    check("remaining() is None while busy", w.remaining() is None)
    w.begin("listen")  # the second PTT key, or key auto-repeat
    w.end("listen")
    check("ending the token counts as activity", w.remaining() == 2 * 60)
    clock.advance(2 * 60 - 1)
    check("not due until a full timeout after work ended", w.poll() is False)
    clock.advance(1)
    check("fires a full timeout after the token was released", w.poll() is True)

    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=2)
    with w.busy("speak"):
        clock.advance(5 * 60)
        check("busy('speak') context blocks the timer", w.poll() is False and not sc.asleep)
    check("leaving the context restarts the countdown", w.remaining() == 2 * 60)

    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=2)
    with w.busy("command"):
        with w.busy("listen"):
            clock.advance(5 * 60)
        check("one of two tokens released: still busy", w.poll() is False and w.is_busy())
    check("all tokens released: idle again", not w.is_busy())

    sc, w, clock, calls, path = make(tmp, enabled=True, minutes=2)
    w.begin("listen")
    clock.advance(IdleWatcher.MAX_BUSY_S + 1)
    check("a token leaked for >MAX_BUSY_S no longer blocks (safety net)", w.poll() is True and sc.asleep)

    # -- config keys ---------------------------------------------------------------
    cfg_path = Path(tmp) / "config.toml"
    cfg_path.write_text('[sleep]\ntrigger = ["go to sleep"]\nunload_speech = false\n')
    cfg = load_config(cfg_path)
    check("defaults: on_idle=true, idle_minutes=15", cfg.sleep.on_idle is True and cfg.sleep.idle_minutes == 15)
    check("existing keys unaffected", cfg.sleep.trigger == ["go to sleep"] and cfg.sleep.unload_speech is False)
    cfg_path.write_text('[sleep]\non_idle = false\nidle_minutes = 2.5\n')
    cfg = load_config(cfg_path)
    check("on_idle/idle_minutes read from TOML", cfg.sleep.on_idle is False and cfg.sleep.idle_minutes == 2.5)
    default = load_config(Path(__file__).resolve().parents[2] / "config.default.toml")
    check("config.default.toml carries the new keys", default.sleep.on_idle is True and default.sleep.idle_minutes == 15)

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
