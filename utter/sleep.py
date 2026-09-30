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
from pathlib import Path
from typing import Callable, Iterable, List, Optional

log = logging.getLogger(__name__)

Hook = Callable[[], None]
Runner = Callable[[List[str]], object]


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
        self.asleep = False

    # -- hooks (registered by the listener process) ---------------------------
    def on_unload(self, fn: Hook) -> None:
        self._unload.append(fn)

    def on_reload(self, fn: Hook) -> None:
        self._reload.append(fn)

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

    def _publish(self) -> None:
        doc = {"asleep": self.asleep, "services": self.services, "ts": int(time.time() * 1000)}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc))
            tmp.replace(self._path)
        except OSError:
            log.debug("could not write %s", self._path, exc_info=True)


_controller: Optional[SleepController] = None
_controller_lock = threading.Lock()


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


__all__ = ["SleepController", "get", "state_path"]
