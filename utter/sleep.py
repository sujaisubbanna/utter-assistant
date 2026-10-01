"""Sleep mode: free the GPU, keep the push-to-talk listener alive.

Saying the trigger phrase (``[sleep] trigger``, default "go to sleep") in
assistant mode puts Utter to sleep:

* the model services in ``[sleep] services`` (vision + planner by default) are
  stopped, which unloads their models from the GPU;
* the speech model inside the listener process is dropped (``unload_speech``);
* only the background listener stays alive, waiting for a push-to-talk key.

Holding a push-to-talk key wakes it: speech is reloaded straight away (it is
small and fast) and the model services are started in the background, so the
key press is never blocked while the bigger models load.

Utter can also fall asleep **on its own** (``[sleep] on_idle``): the
:class:`IdleWatcher` puts it to sleep after ``idle_minutes`` without any Utter
activity. Activity means *using Utter*, not using the computer: a push-to-talk
key (either one), a spoken command (dictation or assistant), or waking from
sleep. Nothing else on the desktop counts, so typing in an editor for an hour
still lets Utter free the GPU. The watcher never fires while Utter is busy
(listening, transcribing, running a command, speaking). Automatic sleep goes
through the very same :meth:`SleepController.sleep`, so once asleep the two
are indistinguishable and the same key press wakes both.

State is published to ``$XDG_RUNTIME_DIR/utter/sleep.json`` for the UI.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional

log = logging.getLogger(__name__)

Hook = Callable[[], None]
StateHook = Callable[[bool], None]
Runner = Callable[[List[str]], object]
Clock = Callable[[], float]


def state_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "utter" / "sleep.json"


def _words(text: str) -> list:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()


def _default_systemctl(args: List[str]) -> object:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)


class SleepController:
    """Owns the asleep/awake state and the unload/reload hooks."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        triggers: Iterable[str] = ("go to sleep",),
        services: Iterable[str] = ("utter-vision", "utter-planner"),
        unload_speech: bool = True,
        systemctl: Optional[Runner] = None,
        path: Optional[Path] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.triggers = [_words(t) for t in triggers if _words(t)]
        self.services = [s for s in services if s]
        self.unload_speech = bool(unload_speech)
        self._systemctl = systemctl or _default_systemctl
        self._path = path or state_path()
        self._lock = threading.RLock()
        self._unload: List[Hook] = []
        self._reload: List[Hook] = []
        self._state_hooks: List[StateHook] = []
        self.asleep = False

    # -- hooks (registered by the listener process) ---------------------------
    def on_unload(self, fn: Hook) -> None:
        self._unload.append(fn)

    def on_reload(self, fn: Hook) -> None:
        self._reload.append(fn)

    def on_state(self, fn: StateHook) -> None:
        """Called with the new ``asleep`` value after every sleep/wake transition."""
        self._state_hooks.append(fn)

    # -- trigger ---------------------------------------------------------------
    def matches(self, utterance: str) -> bool:
        """True when the utterance *is* a trigger phrase (case/punctuation-free)."""
        if not self.enabled:
            return False
        words = _words(utterance)
        return any(words == t for t in self.triggers)

    # -- transitions -----------------------------------------------------------
    def sleep(self) -> bool:
        with self._lock:
            if self.asleep:
                return True
            t0 = time.perf_counter()
            for unit in self.services:
                self._run(["stop", f"{unit}.service"])
            if self.unload_speech:
                self._call(self._unload)
            self.asleep = True
            self._publish()
            log.info("sleep: stopped %s, speech %s (%.0fms)", ", ".join(self.services) or "nothing",
                     "unloaded" if self.unload_speech else "kept", (time.perf_counter() - t0) * 1000)
            self._notify()
            return True

    def wake(self) -> bool:
        with self._lock:
            if not self.asleep:
                return False
            t0 = time.perf_counter()
            if self.unload_speech:
                self._call(self._reload)  # small + fast: needed for this very utterance
            for unit in self.services:
                # --no-block: never hold the key press while big models load
                self._run(["start", "--no-block", f"{unit}.service"])
            self.asleep = False
            self._publish()
            log.info("wake: speech ready, starting %s (%.0fms)", ", ".join(self.services) or "nothing",
                     (time.perf_counter() - t0) * 1000)
            self._notify()
            return True

    # -- internals ---------------------------------------------------------------
    def _run(self, args: List[str]) -> None:
        try:
            self._systemctl(args)
        except Exception:  # noqa: BLE001 - a failed unit must not break sleep/wake
            log.exception("systemctl %s failed", " ".join(args))

    def _call(self, hooks: List[Hook]) -> None:
        for fn in hooks:
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("sleep hook %r failed", fn)

    def _notify(self) -> None:
        for fn in self._state_hooks:
            try:
                fn(self.asleep)
            except Exception:  # noqa: BLE001
                log.exception("sleep state hook %r failed", fn)

    def _publish(self) -> None:
        doc = {"asleep": self.asleep, "services": self.services, "ts": int(time.time() * 1000)}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc))
            tmp.replace(self._path)
        except OSError:
            log.debug("could not write %s", self._path, exc_info=True)


class IdleWatcher:
    """Puts the assistant to sleep after ``minutes`` without Utter activity.

    The watcher is a pure state machine driven by an injectable monotonic
    ``clock`` so it can be tested without sleeping; :meth:`start` wraps it in
    one long-lived daemon thread for the real daemon.

    **Activity** (anything that calls :meth:`touch` or :meth:`busy`):

    * a push-to-talk key going down or up (dictation *and* assistant keys);
    * a spoken command being handled (``busy("command")``);
    * waking from sleep (registered via :meth:`SleepController.on_state`).

    Raw desktop input (keyboard, mouse) is deliberately **not** activity:
    counting it would keep the GPU busy while the user types somewhere else,
    which is exactly when Utter should get out of the way.

    **Busy** tokens (``with watcher.busy("listen")``) hold the timer: it never
    fires while a token is held, however long the timeout. Tokens are a set,
    so re-entering the same token is harmless. Leaving the last token counts
    as activity, so the countdown restarts from the end of the work. As a
    safety net a token held for longer than :attr:`MAX_BUSY_S` is treated as
    leaked (a recogniser that never reported IDLE) and stops holding the timer.
    """

    #: how often the thread re-checks even when nothing is due (seconds)
    MAX_WAIT_S = 60.0
    #: a busy token older than this is a leak, not real work (seconds)
    MAX_BUSY_S = 600.0

    def __init__(
        self,
        controller: SleepController,
        *,
        enabled: bool = True,
        minutes: float = 15,
        clock: Clock = time.monotonic,
    ) -> None:
        self.controller = controller
        self.enabled = bool(enabled)
        try:
            self.timeout_s = max(0.0, float(minutes)) * 60.0
        except (TypeError, ValueError):
            log.warning("sleep.idle_minutes=%r is not a number; idle sleep disabled", minutes)
            self.timeout_s = 0.0
        if self.enabled and self.timeout_s <= 0:
            log.warning("sleep.idle_minutes must be > 0; idle sleep disabled")
            self.enabled = False
        self._clock = clock
        self._lock = threading.Lock()
        self._last = clock()
        self._busy: dict = {}  # token -> clock() when it began
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.fired = 0
        controller.on_state(self._on_state)

    # -- activity ------------------------------------------------------------
    def touch(self, reason: str = "") -> None:
        """Record Utter activity: the countdown restarts from now."""
        with self._lock:
            self._last = self._clock()
        if reason:
            log.debug("idle: activity (%s)", reason)
        self._kick()

    def begin(self, token: str) -> None:
        """Mark ``token`` as in progress; the watcher will not fire until :meth:`end`."""
        with self._lock:
            now = self._clock()
            self._busy.setdefault(token, now)
            self._last = now

    def end(self, token: str) -> None:
        with self._lock:
            self._busy.pop(token, None)
            self._last = self._clock()
        self._kick()

    @contextmanager
    def busy(self, token: str) -> Iterator[None]:
        self.begin(token)
        try:
            yield
        finally:
            self.end(token)

    def is_busy(self) -> bool:
        with self._lock:
            return self._busy_locked()

    def _busy_locked(self) -> bool:
        now = self._clock()
        live = [t for t, t0 in self._busy.items() if now - t0 < self.MAX_BUSY_S]
        for token in set(self._busy) - set(live):
            log.warning("idle: busy token %r held for %.0fs; treating it as leaked",
                        token, now - self._busy.pop(token))
        return bool(live)

    def _on_state(self, asleep: bool) -> None:
        if not asleep:
            self.touch("wake")

    # -- timer -----------------------------------------------------------------
    def remaining(self) -> Optional[float]:
        """Seconds until the watcher would fire, or ``None`` when it cannot
        (disabled, asleep already, or busy)."""
        if not self.enabled or self.controller.asleep:
            return None
        with self._lock:
            if self._busy_locked():
                return None
            return max(0.0, self.timeout_s - (self._clock() - self._last))

    def poll(self) -> bool:
        """Fire if due. Returns True when it put the assistant to sleep."""
        left = self.remaining()
        if left is None or left > 0:
            return False
        log.info("idle: no Utter activity for %g min, going to sleep", self.timeout_s / 60.0)
        self.fired += 1
        self.controller.sleep()
        return True

    def start(self) -> Optional[threading.Thread]:
        """Run :meth:`poll` in a daemon thread. Idempotent; no-op when disabled."""
        if not self.enabled:
            log.info("idle sleep: disabled")
            return None
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="utter-idle-sleep", daemon=True)
        self._thread.start()
        log.info("idle sleep: after %.1f min without Utter activity", self.timeout_s / 60.0)
        return self._thread

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._thread = None

    def _kick(self) -> None:
        # Wake the thread so it recomputes its wait after activity (keeps the
        # "MAX_WAIT_S" slices from firing late when the timeout is tiny).
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
                left = self.remaining()
            except Exception:  # noqa: BLE001 - the watcher must survive a bad hook
                log.exception("idle watcher poll failed")
                left = None
            wait = self.MAX_WAIT_S if left is None else max(0.05, min(left, self.MAX_WAIT_S))
            self._wake.wait(wait)
            self._wake.clear()


_controller: Optional[SleepController] = None
_controller_lock = threading.Lock()
_idle: Optional[IdleWatcher] = None


def get(cfg=None) -> SleepController:
    """The process-wide controller, built from ``[sleep]`` in config.toml."""
    global _controller
    with _controller_lock:
        if _controller is None:
            if cfg is None:
                from .config import load_config
                cfg = load_config()
            sc = getattr(cfg, "sleep", None)
            triggers = getattr(sc, "trigger", ["go to sleep"])
            if isinstance(triggers, str):
                triggers = [triggers]
            _controller = SleepController(
                enabled=getattr(sc, "enabled", True),
                triggers=triggers,
                services=getattr(sc, "services", ["utter-vision", "utter-planner"]),
                unload_speech=getattr(sc, "unload_speech", True),
            )
        return _controller


def idle(cfg=None) -> IdleWatcher:
    """The process-wide idle watcher, built from ``[sleep] on_idle`` / ``idle_minutes``.

    Always returns a watcher (a disabled one when ``on_idle`` is false) so
    callers can report activity unconditionally.
    """
    global _idle
    with _controller_lock:
        if _idle is None:
            if cfg is None:
                from .config import load_config
                cfg = load_config()
            sc = getattr(cfg, "sleep", None)
            _idle = IdleWatcher(
                get(cfg),
                enabled=getattr(sc, "on_idle", True),
                minutes=getattr(sc, "idle_minutes", 15),
            )
        return _idle


def touch(reason: str = "") -> None:
    """Report Utter activity to the idle watcher (safe before it is configured)."""
    try:
        idle().touch(reason)
    except Exception:  # noqa: BLE001 - never let bookkeeping break a key press
        log.debug("idle touch failed", exc_info=True)


__all__ = ["IdleWatcher", "SleepController", "get", "idle", "state_path", "touch"]
