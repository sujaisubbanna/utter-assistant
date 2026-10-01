"""Model-readiness watcher behind the OSD ``loading`` state.

On a cold start, and again after waking from sleep, the vision/planner model
services are started in the background (see ``utter/sleep.py``) and take
seconds to load. This watcher shows the OSD ``loading`` state until they are
actually ready.

**Readiness is a real signal.** Each configured service maps to its
OpenAI-compatible base URL and we poll ``GET {base}/models`` with a short
timeout; a 200 whose JSON body has a ``data`` list means the server has
finished loading. We reuse the same URLs the router and vision client already
call. We deliberately do *not* treat "systemd started the unit" as ready: a
vLLM process only listens after the weights are loaded.

**Fallback.** If a service has no known readiness endpoint, or none answers
within ``timeout_s``, the watcher clears the overlay anyway and logs a
warning. That bounded timeout is a fallback for a missing signal, **not** a
claim that the models are ready.

The watcher never raises. It leaves an in-progress utterance alone: the OSD
emitter refuses ``loading`` while ``listening``/``final`` is active, and the
watcher re-asserts ``loading`` on a later tick once the utterance ends.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Callable, Iterable, List, Optional

log = logging.getLogger(__name__)

#: default bounded fallback when readiness is never signalled (seconds)
DEFAULT_TIMEOUT_S = 30.0
#: how often we re-check readiness / refresh the pulse sample (seconds)
DEFAULT_INTERVAL_S = 0.5
#: per-request timeout for a readiness probe (seconds)
_PROBE_TIMEOUT_S = 1.5

__all__ = [
    "ModelLoadingWatcher",
    "http_probe",
    "probes_for_services",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_INTERVAL_S",
]


def http_probe(
    base_url: str, *, probe_timeout_s: float = _PROBE_TIMEOUT_S
) -> Callable[[], bool]:
    """Readiness probe for an OpenAI-compatible server at ``base_url``.

    Returns a zero-argument callable that is ``True`` once ``GET {base}/models``
    answers 200 with a JSON ``data`` list. Any failure (connection refused,
    timeout, bad JSON) is ``False`` and never raises.
    """
    url = base_url.rstrip("/") + "/models"

    def probe() -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=probe_timeout_s) as resp:
                if getattr(resp, "status", 200) != 200:
                    return False
                raw = resp.read()
            payload = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return False
        return isinstance(payload, dict) and isinstance(payload.get("data"), list)

    return probe


def probes_for_services(services: Iterable[str], cfg) -> List[Callable[[], bool]]:
    """Map configured service units to readiness probes.

    ``utter-vision`` maps to ``[vision] base_url``; ``utter-planner`` (or a
    name mentioning llm/router) maps to ``[router] llm_base_url``. Unknown
    services are skipped, and the caller falls back to the bounded timeout.
    """
    vision = getattr(getattr(cfg, "vision", None), "base_url", None)
    llm = getattr(getattr(cfg, "router", None), "llm_base_url", None)
    probes: List[Callable[[], bool]] = []
    seen = set()
    for name in services or ():
        key = str(name).lower()
        url = None
        if "vision" in key:
            url = vision
        elif "planner" in key or "llm" in key or "router" in key:
            url = llm
        if not url or url in seen:
            continue
        seen.add(url)
        probes.append(http_probe(url))
    return probes


class ModelLoadingWatcher:
    """Drive the OSD ``loading`` state until the model servers are ready."""

    def __init__(
        self,
        osd,
        probes: Iterable[Callable[[], bool]] = (),
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        interval_s: float = DEFAULT_INTERVAL_S,
        text: str = "Starting models…",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._osd = osd
        self._probes = list(probes)
        self._timeout_s = max(0.0, float(timeout_s))
        self._interval_s = max(0.01, float(interval_s))
        self._text = text
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active = False
        self._started = 0.0
        #: True once the bounded timeout (not a readiness signal) cleared it
        self.timed_out = False

    # -- probes ---------------------------------------------------------------
    def _all_ready(self) -> bool:
        if not self._probes:
            return False
        for probe in self._probes:
            try:
                if not probe():
                    return False
            except Exception:
                return False
        return True

    @property
    def active(self) -> bool:
        return self._active

    # -- lifecycle ------------------------------------------------------------
    def begin(self, *, background: bool = True) -> None:
        """Show ``loading`` (unless already ready) and poll until ready/timeout.

        ``background=False`` skips the polling thread so callers/tests can drive
        it deterministically with :meth:`tick`.
        """
        with self._lock:
            if self._active:
                # A fresh wake restarts the deadline without flickering the OSD.
                self._started = self._clock()
                return
            self._started = self._clock()
            self._stop.clear()
        if not self._probes:
            log.warning(
                "model loading: no readiness endpoint for the configured services; "
                "showing 'loading' for at most %.0fs before clearing",
                self._timeout_s,
            )
        if self._all_ready():
            self._finish("ready-before-show")
            return
        try:
            self._osd.loading(self._text)
        except Exception:
            log.debug("model loading: OSD loading() failed", exc_info=True)
        with self._lock:
            self._active = True
        if not background:
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="utter-model-loading"
        )
        self._thread.start()

    def tick(self) -> bool:
        """One readiness check. Returns True when loading is finished."""
        with self._lock:
            if not self._active:
                return True
            started = self._started
        if self._all_ready():
            self._finish("ready")
            return True
        if self._clock() - started >= self._timeout_s:
            self.timed_out = True
            self._finish("timeout")
            return True
        # Refresh the sample (updates ts) so the panel can animate the pulse.
        try:
            self._osd.loading(self._text)
        except Exception:
            log.debug("model loading: OSD refresh failed", exc_info=True)
        return False

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            if self.tick():
                return

    def _finish(self, reason: str) -> None:
        with self._lock:
            self._active = False
        self._stop.set()
        if reason == "timeout":
            log.warning(
                "model loading: not ready within %.0fs; clearing the OSD "
                "(bounded timeout, not a readiness confirmation)",
                self._timeout_s,
            )
        try:
            self._osd.ready()
        except Exception:
            log.debug("model loading: OSD ready() failed", exc_info=True)

    def cancel(self) -> None:
        """Stop without changing the OSD (used on uninstall)."""
        with self._lock:
            self._active = False
        self._stop.set()
