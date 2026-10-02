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
from .types import Action, Context, Plan, Step, Tier


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

        self.executor = Executor(ctx_builder, self.cfg, profiles=self.profiles)

    # -- routing -----------------------------------------------------------
    def route(self, utterance: str, ctx: Context) -> Optional[Plan]:
        from .router import decide, planner, rules

        rp = rules.plan(utterance, ctx, self.profiles)

        # Deterministic multi-step plans (e.g. "close youtube" -> focus + close)
        # are kept in rules; they cannot be expressed as a single decision.
        if rp is not None and len(rp.steps) > 1:
            return rp

        # Jev-style constrained decision head: candidate set -> one predicted
        # action with a probability. This is the primary router for single-step
        # commands, replacing brittle string matching.
        dec = None
        try:
            dec = decide.decide(utterance, ctx, self.profiles, self.cfg.router)
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
        p = planner.plan(utterance, ctx, self.profiles, self.cfg.router)
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
        from .voice import hotkey
        from .voice.stt import Transcriber
        import numpy as np
        import sounddevice as sd

        from . import sleep as _sleep

        stt = Transcriber.for_platform(self.cfg)
        rec_lock = threading.Lock()
        chunks: list = []
        sleeper = _sleep.get(self.cfg)
        idle = _sleep.idle(self.cfg)

        # Additive OSD: waveform + listening/final, plus the loading state on
        # cold start and after wake. A disabled emitter writes nothing.
        osd = _Osd(self.cfg, audio_source=_pcm16_source(chunks, rec_lock))
        osd.begin_loading()
        osd.watch_sleep(sleeper)

        def record_start():
            idle.begin("listen")
            if sleeper.asleep:
                sleeper.wake()
                _play("wake")
            with rec_lock:
                chunks.clear()
            log.info("PTT down - listening")
            osd.listening("assistant")

            def cb(indata, frames, t, status):
                with rec_lock:
                    chunks.append(indata.copy())
                osd.level(_rms(indata))
            stream = sd.InputStream(samplerate=self.cfg.audio.sample_rate,
                                    channels=self.cfg.audio.channels, dtype="float32",
                                    device=(self.cfg.audio.device or None), callback=cb)
            stream.start()
            record_start.stream = stream  # type: ignore[attr-defined]

        def record_stop():
            try:
                stream = getattr(record_start, "stream", None)
                if stream is None:
                    return
                stream.stop(); stream.close()
                with rec_lock:
                    data = np.concatenate(chunks) if chunks else np.zeros((0, 1), dtype="float32")
                audio = data.reshape(-1).astype("float32")
                if audio.size < self.cfg.audio.sample_rate * 0.2:
                    log.info("too short, ignoring")
                    osd.idle()
                    return
                try:
                    text = stt.transcribe(audio)
                except Exception:  # noqa: BLE001 - clear the OSD, keep the loop alive
                    osd.idle()
                    raise
                log.info("transcript: %r", text)
                if text:
                    try:
                        ok = self.handle_utterance(text)
                    except Exception:  # noqa: BLE001 - clear the OSD, keep the loop alive
                        osd.idle()
                        raise
                    _play("detected" if ok else "not_detected")
                    # ``final`` schedules its own dismiss after [osd] dismiss_ms.
                    osd.final(text, bool(ok))
                else:
                    osd.idle()
            finally:
                idle.end("listen")

        idle.start()
        hotkey.listen(record_start, record_stop, key_name=self.cfg.hotkey.key)

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
        from .voice.stt import Transcriber

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
        session: dict = {"stream": None, "chunks": [], "mode": None}
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
                session["chunks"].clear()
                session["mode"] = mode

                def cb(indata, frames, t, status):
                    with rec_lock:
                        session["chunks"].append(indata.copy())
                    level = _rms(indata)
                    osd.level(level)
                    native.level(level)
                stream = sd.InputStream(samplerate=self.cfg.audio.sample_rate,
                                        channels=self.cfg.audio.channels, dtype="float32",
                                        device=(self.cfg.audio.device or None), callback=cb)
                stream.start()
                session["stream"] = stream
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
            try:
                audio = data.reshape(-1).astype("float32")
                if audio.size < self.cfg.audio.sample_rate * 0.2:
                    log.info("too short, ignoring")
                    osd.idle()
                    native.idle()
                    return
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
                    from .actions import keyboard
                    try:
                        res = keyboard.type_text(text)
                    except Exception:  # noqa: BLE001 - clear the OSD, keep the loop alive
                        osd.idle()
                        native.idle()
                        raise
                    if res.ok:
                        _play("typed")
                    else:
                        _play("not_detected")
                        log.warning("dictation typing failed: %s", res.detail)
                        _notify(f"Could not type text: {res.detail}", mc)
                    osd.final(text, bool(res.ok))
                    native.final(text, bool(res.ok), dismiss_ms, lane=mode)
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
