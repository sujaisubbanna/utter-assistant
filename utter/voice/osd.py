"""Optional on-screen-display (OSD) emitter for the assistant voice lane.

Publishes a tiny JSON state document for a Noctalia overlay panel so the user can
see "what Whisper is hearing" and whether an utterance activated a command.

Frozen contract (written atomically to ``$XDG_RUNTIME_DIR/utter/osd.json``)::

    {"state":"idle","mode":"assistant","level":0.0,"text":"",
     "activated":null,"ts":1234567890}

* ``state``     : ``idle`` | ``listening`` | ``loading`` | ``final``
* ``level``     : audio level 0.0-1.0 (raw 0-100 input is normalised here)
* ``text``      : best-effort partial transcript while listening / final text;
                  a short status line while ``loading`` (empty is allowed)
* ``activated`` : ``True``/``False`` once a command was decided, else ``null``

``loading`` is **additive** to the original ``idle|listening|final`` set: the
model services are (re)starting and the panel should show a calm indeterminate
pulse. It never interrupts an utterance — :meth:`OsdEmitter.loading` is a no-op
while ``listening``/``final`` is active — and is cleared by
:meth:`OsdEmitter.ready` (or :meth:`OsdEmitter.idle`) back to ``idle``.

Design rules:
    * Disabled (``UTTER_OSD=0`` or ``[osd] enabled=false``) => **no writes**.
    * **Never raises** out of the public API and never blocks the recognition
      thread; windowed transcription runs in a single daemon worker with at most
      one decode in flight, serialized on a shared lock with the listener's own
      transcription. Windowed *partial* transcription is **opt-in**
      (``[osd] stream=true``); the default keeps the waveform + final text and
      runs no model inference while listening.
    * If windowed STT is unavailable/unsafe the emitter falls back to an empty
      ``text`` and relies on the level meter.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["OsdEmitter", "default_path"]

_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}

# The level callback fires per audio chunk (~64 ms @16 kHz) which is already
# ~15 Hz; cap writes at 20 Hz to be safe.
_MAX_LEVEL_HZ = 20.0

_SAMPLE_RATE = 16000
_SAMPLE_BYTES = 2  # int16 mono


def _env_override() -> Optional[bool]:
    """Return True/False when ``UTTER_OSD`` is set, else None."""
    raw = os.environ.get("UTTER_OSD")
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in _FALSE:
        return False
    if val in _TRUE:
        return True
    return None


def default_path() -> Path:
    """Resolve the OSD JSON path from the environment."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "utter" / "osd.json"


def _normalise_level(value) -> float:
    """Coerce a raw level into 0.0-1.0, tolerating 0-100 input."""
    try:
        level = float(value)
    except (TypeError, ValueError):
        return 0.0
    if level > 1.0:  # tolerate sources that report a 0-100 scale
        level = level / 100.0
    return max(0.0, min(1.0, level))


class OsdEmitter:
    """Publishes assistant OSD state; a no-op when disabled and never raises."""

    def __init__(
        self,
        cfg=None,
        *,
        enabled: Optional[bool] = None,
        path: Optional[os.PathLike] = None,
        audio_source: Optional[Callable[[], List[bytes]]] = None,
        transcriber=None,
        transcriber_factory: Optional[Callable[[], object]] = None,
        transcribe_lock: Optional[threading.Lock] = None,
        config=None,
        on_partial: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ):
        self._lock = threading.RLock()
        self._clock = clock
        self._mono = mono

        env = _env_override()
        if env is False:
            resolved_enabled = False
        elif env is True:
            resolved_enabled = True
        elif enabled is not None:
            resolved_enabled = bool(enabled)
        else:
            resolved_enabled = bool(getattr(cfg, "enabled", True))
        self.enabled = resolved_enabled

        self._path = Path(path) if path is not None else default_path()
        self._dismiss_s = max(0.0, float(getattr(cfg, "dismiss_ms", 1200)) / 1000.0)
        self._stream = bool(getattr(cfg, "stream", True))
        self._interval_s = max(
            0.05, float(getattr(cfg, "stream_interval_ms", 700)) / 1000.0
        )
        self._window_s = max(0.5, float(getattr(cfg, "window_s", 6)))

        self._audio_source = audio_source
        self._transcriber = transcriber
        self._transcriber_factory = transcriber_factory
        # Shared with the listener's final transcribe so a window decode and the
        # utterance decode never run on the same model concurrently. The
        # listener passes its own transcriber here so only ONE model is loaded.
        self._transcribe_lock = transcribe_lock
        # Full configuration (used to build a platform-correct windowed STT
        # transcriber); optional so existing callers keep the default loader.
        self._config = config
        # Best-effort hook for a native overlay to mirror the partial text.
        self._on_partial = on_partial

        # cached document state
        self._state = "idle"
        self._mode = "assistant"  # or "dictation"
        self._level = 0.0
        self._text = ""
        self._activated: Optional[bool] = None

        self._listening = False
        self._stt_failed = False
        self._last_level_mono = 0.0
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._idle_timer: Optional[threading.Timer] = None

    # -- introspection -----------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    # -- public API (safe: never raises) -----------------------------------
    def listening(self, mode: str = "assistant") -> None:
        """PTT pressed: begin listening + level streaming.

        ``mode`` is ``"assistant"`` (the transcript becomes an action) or
        ``"dictation"`` (the transcript is typed); the overlay styles each.
        """
        if not self.enabled:
            return
        try:
            with self._lock:
                self._cancel_idle_locked()
                self._stop_worker_locked()
                self._mode = "dictation" if mode == "dictation" else "assistant"
                self._state = "listening"
                self._listening = True
                self._level = 0.0
                self._text = ""
                self._activated = None
                self._stt_failed = False
                self._last_level_mono = 0.0
                self._write_locked()
                self._start_worker_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd listening() failed", exc_info=True)

    def level(self, value) -> None:
        """Audio level update (0.0-1.0, or 0-100). Throttled to ~20 Hz."""
        if not self.enabled:
            return
        try:
            with self._lock:
                if not self._listening:
                    return
                self._level = _normalise_level(value)
                now = self._mono()
                if now - self._last_level_mono < 1.0 / _MAX_LEVEL_HZ:
                    return
                self._last_level_mono = now
                self._write_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd level() failed", exc_info=True)

    def partial(self, text) -> None:
        """Best-effort partial transcript while listening."""
        if not self.enabled:
            return
        try:
            with self._lock:
                if not self._listening:
                    return
                self._text = text or ""
                self._write_locked()
                partial_text = self._text
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd partial() failed", exc_info=True)
            return
        # Mirror the partial text to an optional native overlay. Best-effort:
        # a broken callback must never escape into the decode worker.
        callback = self._on_partial
        if callback is not None:
            try:
                callback(partial_text)
            except Exception:  # pragma: no cover - defensive
                logger.debug("osd partial callback failed", exc_info=True)

    def final(self, text, activated=None) -> None:
        """Utterance resolved: show final text + whether a command activated."""
        if not self.enabled:
            return
        try:
            with self._lock:
                self._listening = False
                self._stop_worker_locked()
                self._state = "final"
                self._text = text or ""
                self._activated = None if activated is None else bool(activated)
                self._write_locked()
                self._schedule_idle_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd final() failed", exc_info=True)

    def idle(self) -> None:
        """Clear the overlay (also used by stop/failure paths)."""
        if not self.enabled:
            return
        try:
            with self._lock:
                self._listening = False
                self._stop_worker_locked()
                self._cancel_idle_locked()
                self._reset_locked()
                self._write_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd idle() failed", exc_info=True)

    def loading(self, text: str = "") -> None:
        """Model services are (re)starting: show a calm indeterminate state.

        Additive to the frozen ``idle | listening | final`` set. This is a
        *background* state: it never interrupts an utterance, so while
        ``listening`` (or a ``final`` result is being held) it is a no-op and
        the live transcript keeps the overlay. It is safe to call repeatedly
        (the watcher does, to refresh ``ts`` for the pulse animation).
        :meth:`ready` clears it back to ``idle``.
        """
        if not self.enabled:
            return
        try:
            with self._lock:
                if self._listening or self._state in ("listening", "final"):
                    return
                self._cancel_idle_locked()
                self._stop_worker_locked()
                self._state = "loading"
                self._level = 0.0
                self._text = text or ""
                self._activated = None
                self._write_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd loading() failed", exc_info=True)

    def ready(self) -> None:
        """Clear a ``loading`` state once the models report ready.

        Only a ``loading`` state is cleared; ``listening``/``final`` are left
        untouched so a late readiness signal cannot erase an utterance.
        """
        if not self.enabled:
            return
        try:
            with self._lock:
                if self._state != "loading":
                    return
                self._listening = False
                self._cancel_idle_locked()
                self._stop_worker_locked()
                self._reset_locked()
                self._write_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd ready() failed", exc_info=True)

    def on_recognition_idle(self) -> None:
        """Called when the recogniser goes IDLE; clears a stuck 'listening'."""
        if not self.enabled:
            return
        try:
            with self._lock:
                if self._state != "listening":
                    return
                self._listening = False
                self._stop_worker_locked()
                self._reset_locked()
                self._write_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd on_recognition_idle() failed", exc_info=True)

    def close(self) -> None:
        """Stop background threads without writing (used on uninstall)."""
        try:
            with self._lock:
                self._listening = False
                self._stop_worker_locked()
                self._cancel_idle_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd close() failed", exc_info=True)

    # -- internals ---------------------------------------------------------
    def _reset_locked(self) -> None:
        self._state = "idle"
        self._level = 0.0
        self._text = ""
        self._activated = None

    def _cancel_idle_locked(self) -> None:
        timer = self._idle_timer
        self._idle_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _stop_worker_locked(self) -> None:
        self._stop.set()
        worker = self._worker
        self._worker = None
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            # Do not join (worker may be mid-decode); it exits via the event.
            pass

    def _schedule_idle_locked(self) -> None:
        self._cancel_idle_locked()
        if self._dismiss_s <= 0:
            self._reset_locked()
            self._write_locked()
            return
        timer = threading.Timer(self._dismiss_s, self._idle_from_timer)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _idle_from_timer(self) -> None:
        try:
            with self._lock:
                self._idle_timer = None
                if self._state != "final":
                    return
                self._reset_locked()
                self._write_locked()
        except Exception:  # pragma: no cover - defensive
            logger.debug("osd idle timer failed", exc_info=True)

    def _start_worker_locked(self) -> None:
        if not self._stream or self._audio_source is None:
            return
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop,
            args=(self._stop,),
            daemon=True,
            name="utter-osd-stream",
        )
        self._worker.start()

    def _worker_loop(self, stop_event: threading.Event) -> None:
        # A single sequential worker guarantees at most one decode in flight.
        while not stop_event.wait(self._interval_s):
            if stop_event.is_set():
                return
            with self._lock:
                if not self._listening or not self._stream or self._stt_failed:
                    continue
            text = self._decode_window()
            if text is None:
                # Window decode unavailable/unsafe: fall back to the level meter.
                with self._lock:
                    self._stt_failed = True
                continue
            self.partial(text)

    def _decode_window(self) -> Optional[str]:
        """Transcribe the last ``window_s`` of audio; None if unavailable."""
        src = self._audio_source
        if src is None:
            return None
        try:
            chunks = list(src())
        except Exception:
            logger.debug("osd audio source failed", exc_info=True)
            return ""
        if not chunks:
            return ""
        try:
            raw = b"".join(c for c in chunks if c)
        except Exception:
            logger.debug("osd could not join audio chunks", exc_info=True)
            return ""
        if not raw:
            return ""
        max_bytes = int(self._window_s * _SAMPLE_RATE * _SAMPLE_BYTES)
        if len(raw) > max_bytes:
            raw = raw[-max_bytes:]
        if len(raw) % _SAMPLE_BYTES:
            raw = raw[: len(raw) - (len(raw) % _SAMPLE_BYTES)]
        if not raw:
            return ""
        transcriber = self._get_transcriber()
        if transcriber is None:
            return None
        try:
            import numpy as np

            samples = np.frombuffer(raw, dtype=np.int16)
        except Exception:
            logger.debug("osd numpy unavailable", exc_info=True)
            return None
        try:
            lock = self._transcribe_lock
            if lock is None:
                return transcriber.transcribe(samples) or ""
            with lock:
                return transcriber.transcribe(samples) or ""
        except Exception:
            logger.debug("osd window transcribe failed", exc_info=True)
            return None

    def _get_transcriber(self):
        if self._transcriber is not None:
            return self._transcriber
        if self._transcriber_factory is not None:
            try:
                self._transcriber = self._transcriber_factory()
            except Exception:
                logger.debug("osd transcriber factory failed", exc_info=True)
                return None
            return self._transcriber
        try:
            from . import stt as _stt

            # Platform-correct chain: on macOS this picks the native backend
            # (whisper.cpp / Apple Speech) instead of the Linux faster_whisper
            # default, which is not installed in the macOS bundle.
            self._transcriber = _stt.Transcriber.for_platform(self._config)
        except Exception:
            logger.debug("osd: windowed STT unavailable", exc_info=True)
            return None
        return self._transcriber

    def _document_locked(self) -> dict:
        return {
            "state": self._state,
            "mode": self._mode,
            "level": round(float(self._level), 4),
            "text": self._text or "",
            "activated": self._activated,
            "ts": int(self._clock()),
        }

    def _write_locked(self) -> None:
        document = self._document_locked()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(
                f"{self._path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
            )
            tmp.write_text(json.dumps(document))
            os.replace(tmp, self._path)
        except Exception:
            logger.debug("osd: could not write %s", self._path, exc_info=True)
