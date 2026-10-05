"""utter daemon: always-on, context-aware voice -> desktop action.

Modes:
  python -m utter.daemon                  # voice (hotkey PTT) service
  python -m utter.daemon --text "open youtube"   # one-shot, no voice (test)

Routing is tiered: deterministic rules (T0/T2) -> tiny LLM -> perception
(accessibility T1, then vision T3).
"""
from __future__ import annotations

import argparse
import logging
import json
import sys
import threading
import time
from typing import Optional

from .config import Config, load_config
from .executor import Executor
from .types import Action, ActionResult, Context, FocusedWindow, Plan, Step, Tier


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


log = logging.getLogger("utter")


def _play(name: str) -> None:
    try:
        from . import sounds
        sounds.play(name)
    except Exception:
        pass


def _notify(message: str, macos_cfg=None) -> None:
    """macOS notification banner (no-op elsewhere or when disabled)."""
    try:
        from . import platform
        if not platform.is_macos() or not getattr(macos_cfg, "notifications", True):
            return
        from .macos import notify
        notify.notify(message)
    except Exception:
        pass


def _rms(value) -> float:
    """RMS of a captured audio chunk as 0.0-1.0 (never raises)."""
    try:
        import numpy as np
        arr = np.asarray(value, dtype="float32")
        if arr.size == 0:
            return 0.0
        return max(0.0, min(1.0, float(np.sqrt(np.mean(np.square(arr))))))
    except Exception:  # noqa: BLE001 - a bad chunk must not break capture
        return 0.0


def _pcm16_source(chunks, lock):
    """Snapshot shared float32 chunks as int16 bytes for the OSD streamer."""
    def source() -> list:
        try:
            with lock:
                snap = list(chunks)
            if not snap:
                return []
            import numpy as np
            data = np.concatenate([np.asarray(c).reshape(-1) for c in snap])
            if data.size == 0:
                return []
            return [(np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()]
        except Exception:  # noqa: BLE001 - windowed decode is best-effort
            return []
    return source


def _open_input_stream(sd, cfg, callback) -> tuple[object, int]:
    """Open an input stream at the best sample rate the device supports.

    Prefers ``[audio] sample_rate`` but falls back to the device's own default
    and then common rates. Some USB audio devices (e.g. the NanoKVMPro) accept
    only 48000 Hz, so a fixed 16000 Hz request makes PortAudio raise
    ``PaErrorCode -9997``. Before this helper that error killed the daemon.

    Returns the open (but not started) ``InputStream`` plus the rate it uses.
    """
    device = cfg.audio.device or None
    candidates = [int(cfg.audio.sample_rate)]
    try:
        info = (sd.query_devices(device) if device is not None
                else sd.query_devices(kind="input"))
        default_rate = int(info["default_samplerate"] or 0)
    except Exception:  # noqa: BLE001 - no info just means fewer candidates
        default_rate = 0
    if default_rate:
        candidates.append(default_rate)
    candidates.extend([48000, 44100, 32000, 22050, 16000])

    rates: list[int] = []
    for rate in candidates:
        if rate and rate not in rates:
            rates.append(rate)

    last_error: Optional[Exception] = None
    for rate in rates:
        try:
            stream = sd.InputStream(samplerate=rate, channels=cfg.audio.channels,
                                    dtype="float32", device=device, callback=callback)
            return stream, rate
        except Exception as exc:  # noqa: BLE001 - try the next rate
            last_error = exc
    raise RuntimeError(
        f"could not open input device {device!r} at any of {rates}: {last_error}"
    )


def _resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linearly resample a 1-D float32 signal (numpy only).

    Identity when the rates match or the input is empty. STT expects 16 kHz.
    """
    import numpy as np
    arr = np.asarray(audio, dtype="float32").reshape(-1)
    if arr.size == 0 or src_rate == dst_rate or src_rate <= 0 or dst_rate <= 0:
        return arr
    n_dst = int(round(arr.size * dst_rate / src_rate))
    if n_dst <= 0:
        return np.zeros(0, dtype="float32")
    src_idx = np.linspace(0.0, float(arr.size - 1), arr.size, dtype="float64")
    dst_idx = np.linspace(0.0, float(arr.size - 1), n_dst, dtype="float64")
    return np.interp(dst_idx, src_idx, arr).astype("float32")


def _model_service_reachable(cfg) -> bool:
    """True when the model server for this platform is actually up.

    On macOS the only model service is the local LLM (Ollama), which is
    optional. A short probe lets the OSD skip the cold-start "loading" watcher
    when there is nothing to wait for (no panel, no 30 s timeout warning).
    On other platforms this is always True so behaviour is unchanged.
    """
    try:
        from . import platform
        if not platform.is_macos():
            return True
        from . import runtime as _runtime
        resolved = _runtime.resolve_router(cfg)
        base = (getattr(resolved, "llm_base_url", "") or "").rstrip("/")
        if not base:
            return False
        import urllib.request
        request = urllib.request.Request(base + "/models", method="GET")
        with urllib.request.urlopen(request, timeout=0.6):
            return True
    except Exception:  # noqa: BLE001 - unavailable is a normal, non-fatal state
        return False


# --- dictation target pinning ----------------------------------------------
# Dictation is typed into the window that was focused when the key went *down*,
# not whatever happens to be focused by the time the key is released.
_DICTATION_FALLBACK = "Couldn't find the input — text copied, paste it"
_DICTATION_FALLBACK_NOCLIP = "Couldn't type the text — copy it manually"


def _capture_dictation_target() -> Optional[FocusedWindow]:
    """Snapshot the focused window at key-down (None when unavailable).

    Only the window is captured: neither platform exposes a cheap, generic
    "focused element" probe (macOS AX tree is unwired, AT-SPI has no focused
    node), so element capture is deliberately deferred to a follow-up.
    """
    from .context import desktop
    try:
        return desktop.focused_window()
    except Exception:  # noqa: BLE001 - capture must never break listening
        log.debug("dictation target capture failed", exc_info=True)
        return None


def _still_focused(target) -> bool:
    """Best-effort: is ``target`` the window that is focused right now?"""
    from .context import desktop
    try:
        current = desktop.focused_window()
    except Exception:  # noqa: BLE001
        return False
    if current is None:
        return False
    wid = int(getattr(target, "window_id", 0) or 0)
    cwid = int(getattr(current, "window_id", 0) or 0)
    if wid and cwid:
        return wid == cwid
    pid = int(getattr(target, "pid", 0) or 0)
    cpid = int(getattr(current, "pid", 0) or 0)
    if pid and cpid:
        return pid == cpid
    return (bool(getattr(current, "app_id", ""))
            and current.app_id == getattr(target, "app_id", ""))


def _refocus(target) -> bool:
    """Re-focus the pinned window before typing (Linux best effort)."""
    from .context import desktop
    wid = int(getattr(target, "window_id", 0) or 0)
    if not wid:
        return False
    try:
        return bool(desktop.focus_window_on_workspace(wid))
    except Exception:  # noqa: BLE001
        log.debug("dictation re-focus failed", exc_info=True)
        return False


def _type_dictation(text: str, target) -> ActionResult:
    """Type ``text`` into the key-down target. Never raises.

    macOS posts to the captured pid, so the user's current focus is untouched.
    Linux has no per-window text injection on Wayland: type as-is when the
    target is still focused, otherwise re-focus it first (best effort). Any
    failure is returned as ``ok=False`` for the caller's clipboard fallback.
    """
    from .actions import keyboard
    from . import platform
    try:
        if target is None:
            return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                                "no dictation target")
        if platform.is_macos():
            pid = int(getattr(target, "pid", 0) or 0)
            return keyboard.type_text(text, pid=pid or None)
        if not _still_focused(target):
            _refocus(target)
        return keyboard.type_text(text)
    except Exception as exc:  # noqa: BLE001 - degrade to the clipboard fallback
        return ActionResult(False, Action.TYPE_TEXT, Tier.KEYBOARD,
                            f"type_text failed: {exc}")


def _deliver_dictation(text: str, target, cfg) -> ActionResult:
    """The one dictation seam both platforms call (Linux ``run_hotkey`` and
    macOS ``run_macos``): optionally reformat the transcript, then type it.

    Kept in a single place so the transform is never duplicated per platform,
    and so the assistant lane (which never calls this) stays untouched.
    ``format_transcript`` is offline-safe and returns the raw text on failure.
    """
    from .voice.formatting import format_transcript
    return _type_dictation(format_transcript(text, cfg), target)


def _copy_to_clipboard(text: str) -> bool:
    """Copy ``text`` for the fallback (macOS ``pbcopy`` / Linux ``wl-copy``)."""
    try:
        from . import platform
        if platform.is_macos():
            from .macos import clipboard
        else:
            from .context import clipboard
        return bool(clipboard.set_clipboard(text))
    except Exception:  # noqa: BLE001 - a missing tool must not break the loop
        log.debug("dictation clipboard fallback failed", exc_info=True)
        return False


def _linux_ptt_keys(cfg, start, stop) -> dict:
    """Map configured evdev key names to ``(on_press, on_release)`` lane handlers.

    The dedicated ``[ptt]`` keys drive dictation and assistant; the legacy
    ``[hotkey] key`` still drives the assistant lane (see CUSTOMISING.md §3).
    Empty names are dropped; a repeated key collapses onto one lane, with the
    assistant lane winning a collision (mirrors the macOS two-key map).
    """
    keys: dict = {}
    dict_key = (getattr(cfg.ptt, "dictation_key", "") or "").strip()
    asst_key = (getattr(cfg.ptt, "assistant_key", "") or "").strip()
    legacy_key = (getattr(cfg.hotkey, "key", "") or "").strip()

    if dict_key:
        keys[dict_key] = (lambda: start("dictation"), lambda: stop("dictation"))
    # Assistant sources are assigned last so an equal key resolves to assistant.
    for name in (asst_key, legacy_key):
        if name:
            keys[name] = (lambda: start("assistant"), lambda: stop("assistant"))
    return keys


class _NativeOverlay:
    """System-wide overlay facade (macOS native panel; no-op elsewhere).

    Same rule as the Linux panel: assistant lane only. Every method is safe
    to call from any thread and never raises.
    """

    def __init__(self) -> None:
        self._ov = None
        try:
            from . import platform
            if not platform.is_macos():
                return
            from .macos.overlay import Overlay
            self._ov = Overlay()
        except Exception:
            self._ov = None

    def _call(self, method: str, *args) -> None:
        ov = self._ov
        if ov is None:
            return
        try:
            getattr(ov, method)(*args)
        except Exception:
            pass

    def listening(self, text: str = "", lane: str = "assistant") -> None:
        self._call("listening", text, lane)

    def loading(self, text: str = "") -> None:
        self._call("loading", text)

    def clear_loading(self) -> None:
        self._call("clear_loading")

    def level(self, value: float) -> None:
        self._call("level", value)

    def final(self, text: str, ok: bool, dismiss_ms: int = 1200,
              lane: str = "assistant") -> None:
        self._call("final", text, ok, dismiss_ms, lane)

    def idle(self) -> None:
        self._call("idle")


def _osd_dismiss_ms(cfg) -> int:
    try:
        return int(getattr(getattr(cfg, "osd", None), "dismiss_ms", 1200))
    except (TypeError, ValueError):
        return 1200


class _Osd:
    """Best-effort OSD driver for the native voice lanes.

    Purely additive: a disabled emitter writes nothing, and no call may ever
    raise into the audio/recognition path.
    """

    def __init__(self, cfg, audio_source=None, native=None):
        self.em = None
        self.watcher = None
        self._native = native
        self._lane = "assistant"
        self._sleep_hooked = False
        try:
            from .voice.osd import OsdEmitter
            self.em = OsdEmitter(
                cfg=getattr(cfg, "osd", None),
                audio_source=audio_source,
                config=cfg,
                on_partial=self._on_partial,
            )
        except Exception:
            log.exception("could not initialise OSD emitter")
        self._init_model_loading(cfg)

    # -- safe wrappers -----------------------------------------------------
    def _emit(self, method: str, *args) -> None:
        em = self.em
        if em is None:
            return
        try:
            getattr(em, method)(*args)
        except Exception:  # noqa: BLE001 - the OSD must never break voice
            log.debug("OSD %s failed", method, exc_info=True)

    def listening(self, mode: str = "assistant") -> None:
        self._lane = "dictation" if mode == "dictation" else "assistant"
        self._emit("listening", mode)

    def loading(self, text: str = "") -> None:
        """Show ``loading`` on the emitter *and* the native overlay.

        The model-loading watcher is constructed with ``self`` (the ``_Osd``),
        so its ``loading``/``ready`` calls drive both the JSON document and the
        native macOS panel. Either side may be absent; both are best-effort.
        """
        self._emit("loading", text)
        native = getattr(self, "_native", None)
        if native is not None:
            try:
                native.loading(text)
            except Exception:  # noqa: BLE001 - never break voice
                log.debug("native OSD loading failed", exc_info=True)

    def _on_partial(self, text) -> None:
        """Mirror the live partial transcript onto the native overlay."""
        native = getattr(self, "_native", None)
        if native is None:
            return
        try:
            native.listening(text or "", lane=self._lane)
        except Exception:  # noqa: BLE001 - best-effort only
            log.debug("native OSD partial failed", exc_info=True)

    def level(self, value) -> None:
        self._emit("level", value)

    def final(self, text, activated=None) -> None:
        self._emit("final", text, activated)

    def idle(self) -> None:
        self._emit("idle")

    def ready(self) -> None:
        self._emit("ready")
        native = getattr(self, "_native", None)
        if native is not None:
            try:
                native.clear_loading()
            except Exception:
                pass

    def close(self) -> None:
        self._emit("close")

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.em, "enabled", False))

    # -- model-loading (cold start / wake) ---------------------------------
    def _init_model_loading(self, cfg) -> None:
        sc = getattr(cfg, "sleep", None)
        services = list(getattr(sc, "services", []) or [])
        if not services:
            return
        # On macOS the only model service is the local LLM server (Ollama),
        # which is optional: rules + whisper STT work without it. If nothing is
        # actually listening there is nothing to wait for, so skip the watcher
        # entirely — otherwise every cold start shows a "Models are coming up…"
        # panel and logs a 30 s timeout warning for a server that isn't there.
        if not _model_service_reachable(cfg):
            log.debug("model loading: no reachable model service; skipping watcher")
            return
        try:
            from .voice import model_loading as ml
            # Pass ``self`` (not the emitter) so the watcher's ready()/timeout
            # path runs ``_Osd.ready()`` and clears the native overlay too.
            self.watcher = ml.ModelLoadingWatcher(
                self,
                ml.probes_for_services(services, cfg),
                timeout_s=getattr(sc, "model_ready_timeout_s", ml.DEFAULT_TIMEOUT_S),
            )
        except Exception:
            log.exception("could not initialise model-loading watcher")
            self.watcher = None

    def begin_loading(self) -> None:
        """Show ``loading`` until the model services report ready (cold/wake)."""
        # Only show the loading state when a watcher exists to clear it again;
        # otherwise the panel would be stuck on screen until the next PTT.
        if self.watcher is None:
            return
        native = getattr(self, "_native", None)
        self.loading("Models are coming up…")
        if not self.enabled and native is None:
            # Preserve the previous Linux behaviour: a disabled emitter with no
            # native overlay starts no polling thread.
            return
        try:
            self.watcher.begin()
        except Exception:
            log.debug("could not start model-loading OSD state", exc_info=True)

    def watch_sleep(self, sleeper) -> None:
        """Re-assert ``loading`` when the controller wakes from sleep."""
        if sleeper is None or self.watcher is None or self._sleep_hooked:
            return
        if getattr(sleeper, "_utter_osd_state_hook", False):
            return
        try:
            def _on_state(asleep: bool) -> None:
                if not asleep:
                    self.begin_loading()
            sleeper.on_state(_on_state)
            sleeper._utter_osd_state_hook = True  # type: ignore[attr-defined]
            self._sleep_hooked = True
        except Exception:
            log.debug("could not register OSD sleep hook", exc_info=True)


def _plan_from_decision(dec) -> Optional[Plan]:
    """Convert a decide.Decision into an executable Plan (single step)."""
    c = getattr(dec, "candidate", None)
    if c is None:
        return None
    try:
        action = Action(c.op)
    except ValueError:
        return None
    needs = action in (Action.CLICK_ELEMENT, Action.CLICK_POINT)
    step = Step(action, dict(getattr(c, "args", {}) or {}),
                tier=Tier.VISION if needs else Tier.APP,
                description=getattr(c, "label", "") or action.value)
    return Plan(utterance="", steps=[step], source="decide",
                confidence=float(getattr(dec, "confidence", 0.0)),
                needs_perception=needs)


class Utter:
    def __init__(self, cfg: Optional[Config] = None, dry_run: bool = False):
        self.cfg = cfg or load_config()
        self.dry_run = dry_run
        self.executor: Optional[Executor] = None
        self.profiles: dict = {}
        self._profiles_mod = None
        self.last_plan: Optional[Plan] = None

    def setup(self) -> None:
        from .router import profiles as profiles_mod
        self._profiles_mod = profiles_mod
        self.profiles = profiles_mod.load()
        log.info("loaded %d app profiles", len(self.profiles))

        def ctx_builder(with_a11y: bool = False) -> Context:
            from .context import desktop
            return desktop.build_context(with_a11y=with_a11y)

        self.executor = Executor(ctx_builder, self.cfg, profiles=self.profiles,
                                 reload_profiles=True)

    # -- routing -----------------------------------------------------------
    def route(self, utterance: str, ctx: Context) -> Optional[Plan]:
        from .router import decide, planner, profiles as profiles_mod, rules

        # Refresh (mtime-invalidated) so a GUI/CLI opt-in toggle applies without
        # a restart, then route over the enabled subset only. The executor keeps
        # the *full* dict so it can still tell disabled-known from unknown.
        profiles = profiles_mod.load_cached()
        self.profiles = profiles
        if self.executor is not None:
            self.executor._profiles = profiles
        enabled = profiles_mod.enabled_profiles(profiles)

        rp = rules.plan(utterance, ctx, enabled)

        # Deterministic multi-step plans (e.g. "close youtube" -> focus + close)
        # are kept in rules; they cannot be expressed as a single decision.
        if rp is not None and len(rp.steps) > 1:
            return rp

        # Jev-style constrained decision head: candidate set -> one predicted
        # action with a probability. This is the primary router for single-step
        # commands, replacing brittle string matching.
        dec = None
        try:
            dec = decide.decide(utterance, ctx, enabled, self.cfg.router)
        except Exception as e:  # noqa: BLE001
            log.debug("decide failed: %s", e)

        if dec is not None:
            if dec.candidate.op == "none":
                log.info("decide: no action (conf=%.3f)", dec.confidence)
                return None
            plan = _plan_from_decision(dec)
            if plan is not None:
                log.info("decide -> %s (conf=%.3f)", dec.candidate.label, dec.confidence)
                return plan

        # Decision head unavailable or unmappable: fall back to rules, then to
        # the free-form planner (only when the model server is unreachable).
        if rp is not None:
            return rp
        p = planner.plan(utterance, ctx, enabled, self.cfg.router)
        if p is not None:
            log.info("llm planner produced plan (conf=%.2f)", p.confidence)
        return p

    def handle_utterance(self, utterance: str) -> bool:
        utterance = (utterance or "").strip()
        if not utterance:
            return False
        # A dry-run must never enter the idle/sleep machinery: a one-shot process
        # has no idle timer running, and entering it there blocks.
        if self.dry_run:
            return self._handle_utterance(utterance)
        from . import sleep as _sleep
        # A spoken command is Utter activity, and the idle timer must not put
        # the models to sleep while the command is still being carried out.
        with _sleep.idle(self.cfg).busy("command"):
            return self._handle_utterance(utterance)

    def _handle_utterance(self, utterance: str) -> bool:
        if not self.dry_run:
            from . import sleep as _sleep
            sleeper = _sleep.get(self.cfg)
            if sleeper.matches(utterance):
                log.info("sleep trigger: %r", utterance)
                sleeper.sleep()
                _play("sleep")
                return True
        t0 = time.perf_counter()
        from .context import desktop
        ctx = desktop.build_context(with_a11y=False)
        log.info("utterance: %r (focused=%s)", utterance, ctx.focused_app or "?")
        plan = self.route(utterance, ctx)
        self.last_plan = plan
        if plan is None:
            log.warning("no plan for %r", utterance)
            return False
        if self.dry_run:
            for s in plan.steps:
                log.info("DRY-RUN %s tier=%s args=%s", s.action.value, s.tier.value, s.args)
            return True
        results = self.executor.execute_plan(plan)
        ok = all(r.ok for r in results)
        log.info("handled %r in %.0fms ok=%s", utterance, (time.perf_counter() - t0) * 1000, ok)
        return ok

    # -- voice -------------------------------------------------------------
    def run_hotkey(self) -> None:
        """Linux voice loop: the ``[ptt]`` dictation/assistant keys plus the
        legacy ``[hotkey]`` key.

        * ``[ptt] dictation_key`` -> the transcript is typed into the pinned
          target (``_type_dictation``), with the clipboard fallback.
        * ``[ptt] assistant_key`` / ``[hotkey] key`` -> the transcript is routed
          like any other utterance (rules -> decision head -> actions).
        """
        from .voice import hotkey
        from .voice.stt import Transcriber, SAMPLE_RATE as STT_SAMPLE_RATE
        import numpy as np
        import sounddevice as sd

        from . import sleep as _sleep

        stt = Transcriber.for_platform(self.cfg)
        rec_lock = threading.Lock()
        session: dict = {"stream": None, "chunks": [], "mode": None, "target": None,
                         "rate": 0}
        sleeper = _sleep.get(self.cfg)
        idle = _sleep.idle(self.cfg)

        # Additive OSD: waveform + listening/final, plus the loading state on
        # cold start and after wake. A disabled emitter writes nothing.
        osd = _Osd(self.cfg, audio_source=_pcm16_source(session["chunks"], rec_lock))
        osd.begin_loading()
        osd.watch_sleep(sleeper)

        def start(mode: str) -> None:
            with rec_lock:
                if session["stream"] is not None:
                    return
                # Pin the dictation target at key-down: focus may move mid-speech.
                session["chunks"].clear()
                session["mode"] = mode
                session["target"] = (_capture_dictation_target()
                                     if mode == "dictation" else None)

                def cb(indata, frames, t, status):
                    with rec_lock:
                        session["chunks"].append(indata.copy())
                    osd.level(_rms(indata))
                try:
                    stream, rate = _open_input_stream(sd, self.cfg, cb)
                except Exception as exc:  # noqa: BLE001 - a bad device must not kill the daemon
                    session["stream"] = None
                    session["rate"] = 0
                    log.error("PTT down (%s): cannot open audio input: %s", mode, exc)
                    osd.idle()
                    idle.end("listen")
                    return
                session["stream"] = stream
                session["rate"] = rate
            idle.begin("listen")
            if sleeper.asleep:
                sleeper.wake()
                _play("wake")
            # Same key-down cue on both platforms: the dictation lane gets
            # "dictate", the assistant lane "start" (both after "wake" when the
            # press woke the daemon).
            _play("dictate" if mode == "dictation" else "start")
            # Emit ``listening`` before capture starts so the first audio level
            # lands on a listening panel (the pre-refactor order).
            osd.listening("dictation" if mode == "dictation" else "assistant")
            log.info("PTT down (%s) - listening", mode)
            # Start outside the lock: the first callback may fire synchronously
            # (and the pre-refactor loop never held rec_lock across start()), so
            # holding it here could deadlock capture.
            stream.start()

        def stop(mode: str) -> None:
            with rec_lock:
                stream = session["stream"]
                if stream is None or session["mode"] != mode:
                    return
                session["stream"] = None
                stream.stop(); stream.close()
                data = (np.concatenate(session["chunks"]) if session["chunks"]
                        else np.zeros((0, 1), dtype="float32"))
                rate = int(session.get("rate") or self.cfg.audio.sample_rate)
            try:
                audio = data.reshape(-1).astype("float32")
                if audio.size < rate * 0.2:
                    log.info("too short, ignoring")
                    osd.idle()
                    return
                audio = _resample_linear(audio, rate, STT_SAMPLE_RATE)
                try:
                    text = stt.transcribe(audio)
                except Exception:  # noqa: BLE001 - clear the OSD, keep the loop alive
                    osd.idle()
                    raise
                log.info("transcript (%s): %r", mode, text)
                if not text:
                    osd.idle()
                    return
                if mode == "dictation":
                    res = _deliver_dictation(text, session.get("target"), self.cfg)
                    if res.ok:
                        _play("typed")
                        osd.final(text, True)
                    else:
                        # Never fail silently: park the transcript on the
                        # clipboard and say so (OSD + notification).
                        copied = _copy_to_clipboard(text)
                        _play("not_detected")
                        message = _DICTATION_FALLBACK if copied else _DICTATION_FALLBACK_NOCLIP
                        log.warning("dictation not delivered (%s); clipboard=%s",
                                    res.detail, copied)
                        osd.final(message, False)
                        _notify(message, self.cfg.macos)
                    return
                try:
                    ok = self.handle_utterance(text)
                except Exception:  # noqa: BLE001 - clear the OSD, keep the loop alive
                    osd.idle()
                    raise
                _play("detected" if ok else "not_detected")
                # ``final`` schedules its own dismiss after [osd] dismiss_ms.
                osd.final(text, bool(ok))
            finally:
                idle.end("listen")

        keys = _linux_ptt_keys(self.cfg, start, stop)
        if not keys:
            log.warning("no PTT keys configured ([ptt]/[hotkey]); voice lane idle")
            return
        idle.start()
        try:
            hotkey.listen_many(keys)
        except ValueError as exc:  # bad key name: log, do not kill the daemon
            log.error("invalid PTT key configuration: %s", exc)

    def run_macos(self) -> None:
        """macOS voice loop: two push-to-talk keys and native STT.

        * ``[macos] dictation_key`` -> the transcript is typed into the focused
          field (Quartz/AppleScript injection).
        * ``[macos] assistant_key`` -> the transcript is routed like any other
          utterance (rules -> decision head -> actions).
        """
        import numpy as np
        import sounddevice as sd

        from .macos import hotkey as mac_hotkey
        from .voice.stt import Transcriber, SAMPLE_RATE as STT_SAMPLE_RATE

        from . import sleep as _sleep

        mc = self.cfg.macos

        # Permission state is probed at startup and re-checked lazily on each
        # PTT press, so granting a permission takes effect without a restart.
        # Startup is INFO only (no banner): a notification for permissions the
        # user already knows about was the "random error" popup.
        perm_state: dict = {"missing": set()}

        def _probe_permissions(announce: bool) -> None:
            try:
                from .macos import permissions
                # Probe only: requesting (prompting) from the daemon can SIGABRT
                # under TCC when the responsible process has no usage description
                # in its Info.plist. Prompts belong to the Setup tab / `macos-permissions
                # --request`, which run attributed to utter.app.
                doc = permissions.status_all(request=False)
                missing = {
                    p["label"] for p in doc["permissions"]
                    if p["status"] != permissions.GRANTED
                }
            except Exception as e:  # noqa: BLE001 - never block startup on the probe
                log.debug("permission probe failed: %s", e)
                return
            previous = perm_state["missing"]
            perm_state["missing"] = missing
            if missing and announce:
                log.info("macOS permissions missing: %s (System Settings -> Privacy & Security)",
                         ", ".join(sorted(missing)))
            # Clear the logged missing set once everything is granted.
            if previous and not missing:
                log.info("macOS permissions granted: %s", ", ".join(sorted(previous)))

        _probe_permissions(announce=True)
        stt = Transcriber.for_platform(self.cfg)
        log.info("macOS voice: stt chain=%s dictation=%s assistant=%s hotkeys=%s",
                 [stt.backend, *stt.fallbacks], mc.dictation_key, mc.assistant_key, mc.hotkey_backend)
        rec_lock = threading.Lock()
        session: dict = {"stream": None, "chunks": [], "mode": None, "target": None,
                         "rate": 0}
        sleeper = _sleep.get(self.cfg)
        idle = _sleep.idle(self.cfg)

        # Native system-wide overlay (macOS twin of the Linux Noctalia panel):
        # assistant lane only, driven directly (no file polling).
        native = _NativeOverlay()
        dismiss_ms = _osd_dismiss_ms(self.cfg)
        # Additive OSD for both dictation and assistant keys.
        osd = _Osd(self.cfg, audio_source=_pcm16_source(session["chunks"], rec_lock),
                   native=native)
        osd.begin_loading()
        osd.watch_sleep(sleeper)

        def start(mode: str) -> None:
            # Lazy permission re-check: once the user grants Accessibility /
            # Screen Recording the state refreshes without a daemon restart.
            if perm_state["missing"]:
                _probe_permissions(announce=False)
            with rec_lock:
                if session["stream"] is not None:
                    return
                # Pin the dictation target at key-down: focus may move mid-speech.
                session["chunks"].clear()
                session["mode"] = mode
                session["target"] = (_capture_dictation_target()
                                     if mode == "dictation" else None)

                def cb(indata, frames, t, status):
                    with rec_lock:
                        session["chunks"].append(indata.copy())
                    level = _rms(indata)
                    osd.level(level)
                    native.level(level)
                try:
                    stream, rate = _open_input_stream(sd, self.cfg, cb)
                except Exception as exc:  # noqa: BLE001 - a bad device must not kill the daemon
                    session["stream"] = None
                    session["rate"] = 0
                    log.error("PTT down (%s): cannot open audio input: %s", mode, exc)
                    osd.idle()
                    native.clear_loading()
                    native.idle()
                    idle.end("listen")
                    return
                stream.start()
                session["stream"] = stream
                session["rate"] = rate
            idle.begin("listen")
            if sleeper.asleep:
                sleeper.wake()
                _play("wake")
            _play("dictate" if mode == "dictation" else "start")
            osd.listening("dictation" if mode == "dictation" else "assistant")
            native.listening(lane=mode)
            log.info("PTT down (%s) - listening", mode)

        def stop(mode: str) -> None:
            with rec_lock:
                stream = session["stream"]
                if stream is None or session["mode"] != mode:
                    return
                session["stream"] = None
                stream.stop(); stream.close()
                data = np.concatenate(session["chunks"]) if session["chunks"] else np.zeros((0, 1), dtype="float32")
                rate = int(session.get("rate") or self.cfg.audio.sample_rate)
            try:
                audio = data.reshape(-1).astype("float32")
                if audio.size < rate * 0.2:
                    log.info("too short, ignoring")
                    osd.idle()
                    native.idle()
                    return
                audio = _resample_linear(audio, rate, STT_SAMPLE_RATE)
                try:
                    text = stt.transcribe(audio)
                except Exception as e:  # noqa: BLE001
                    log.error("transcription failed: %s", e)
                    osd.idle()
                    native.clear_loading()
                    native.idle()
                    _notify(f"Transcription failed: {e}", mc)
                    return
                native.clear_loading()
                log.info("transcript (%s): %r", mode, text)
                if not text:
                    osd.idle()
                    native.idle()
                    return
                if mode == "dictation":
                    res = _deliver_dictation(text, session.get("target"), self.cfg)
                    if res.ok:
                        _play("typed")
                        osd.final(text, True)
                        native.final(text, True, dismiss_ms, lane=mode)
                    else:
                        # Never fail silently: park the transcript on the
                        # clipboard and say so (OSD + native notification).
                        copied = _copy_to_clipboard(text)
                        _play("not_detected")
                        message = _DICTATION_FALLBACK if copied else _DICTATION_FALLBACK_NOCLIP
                        log.warning("dictation not delivered (%s); clipboard=%s",
                                    res.detail, copied)
                        osd.final(message, False)
                        native.final(message, False, dismiss_ms, lane=mode)
                        _notify(message, mc)
                    return
                try:
                    ok = self.handle_utterance(text)
                except Exception:  # noqa: BLE001 - clear the OSD, keep the loop alive
                    osd.idle()
                    native.idle()
                    raise
                _play("detected" if ok else "not_detected")
                osd.final(text, bool(ok))
                native.final(text, bool(ok), dismiss_ms, lane=mode)
            finally:
                idle.end("listen")

        keys = {
            mc.dictation_key: (lambda: start("dictation"), lambda: stop("dictation")),
            mc.assistant_key: (lambda: start("assistant"), lambda: stop("assistant")),
        }
        idle.start()
        mac_hotkey.listen_many(keys, backend=mc.hotkey_backend)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="utter")
    ap.add_argument("--text", help="run a single text command and exit (no voice)")
    ap.add_argument("--dry-run", action="store_true", help="route only; do not execute")
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("--log-level", default=None)
    ap.add_argument("--json-plan", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    app = Utter(load_config(args.config), dry_run=args.dry_run)
    _setup_logging(args.log_level or app.cfg.log_level)
    app.setup()

    if args.text:
        if args.dry_run:
            # One-shot previews are route-only. Keep this out of
            # handle_utterance: daemon sleep/idle wrappers may acquire service
            # or busy-state locks that are irrelevant to a preview.
            from .context import niri
            ctx = niri.build_context(with_a11y=False)
            plan = app.route(args.text, ctx)
            app.last_plan = plan
            ok = plan is not None
            if plan is not None:
                for step in plan.steps:
                    log.info("DRY-RUN %s tier=%s args=%s", step.action.value,
                             step.tier.value, step.args)
            else:
                log.warning("no plan for %r", args.text)
        else:
            ok = app.handle_utterance(args.text)
        if args.json_plan:
            plan = app.last_plan
            payload = {"accepted": ok, "plan": None if plan is None else {
                "utterance": plan.utterance,
                "source": plan.source,
                "confidence": plan.confidence,
                "needs_perception": plan.needs_perception,
                "steps": [{"action": step.action.value, "tier": step.tier.value,
                           "args": step.args, "description": step.description}
                          for step in plan.steps],
            }}
            print(json.dumps(payload, ensure_ascii=False))
        return 0 if ok else 1

    from . import platform
    if platform.is_macos():
        app.run_macos()
    else:
        app.run_hotkey()
    return 0


if __name__ == "__main__":
    sys.exit(main())
