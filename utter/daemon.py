"""utter daemon: always-on, context-aware voice -> desktop action.

Modes:
  python -m utter.daemon                  # voice (hotkey PTT) service
  python -m utter.daemon --text "open youtube"   # one-shot, no voice (test)
  python -m utter.daemon --bridge         # reuse vocalinux recognition

Routing is tiered: deterministic rules (T0/T2) -> tiny LLM -> perception
(accessibility T1, then vision T3).
"""
from __future__ import annotations

import argparse
import logging
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


def _assistant_context() -> bool:
    try:
        from .voice import vocalinux_bridge
        return vocalinux_bridge.in_assistant_context()
    except Exception:
        return False


def _play(name: str) -> None:
    try:
        from . import sounds
        sounds.play(name)
    except Exception:
        pass


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

    def setup(self) -> None:
        from .router import profiles as profiles_mod
        self._profiles_mod = profiles_mod
        self.profiles = profiles_mod.load()
        log.info("loaded %d app profiles", len(self.profiles))

        def ctx_builder(with_a11y: bool = False) -> Context:
            from .context import niri
            return niri.build_context(with_a11y=with_a11y)

        self.executor = Executor(ctx_builder, self.cfg)

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
        from . import sleep as _sleep
        # A spoken command is Utter activity, and the idle timer must not put
        # the models to sleep while the command is still being carried out.
        with _sleep.idle(self.cfg).busy("command"):
            return self._handle_utterance(utterance)

    def _handle_utterance(self, utterance: str) -> bool:
        from . import sleep as _sleep
        sleeper = _sleep.get(self.cfg)
        if sleeper.matches(utterance):
            log.info("sleep trigger: %r", utterance)
            if not self.dry_run:
                sleeper.sleep()
                _play("sleep")
            return True
        t0 = time.perf_counter()
        from .context import niri
        ctx = niri.build_context(with_a11y=False)
        log.info("utterance: %r (focused=%s)", utterance, ctx.focused_app or "?")
        plan = self.route(utterance, ctx)
        if plan is None:
            log.warning("no plan for %r", utterance)
            if _assistant_context():
                _play("not_detected")
            return False
        if self.dry_run:
            for s in plan.steps:
                log.info("DRY-RUN %s tier=%s args=%s", s.action.value, s.tier.value, s.args)
            return True
        if _assistant_context():
            _play("detected")
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

        stt = Transcriber(self.cfg.stt)
        rec_lock = threading.Lock()
        chunks: list = []
        sleeper = _sleep.get(self.cfg)
        idle = _sleep.idle(self.cfg)

        def record_start():
            idle.begin("listen")
            if sleeper.asleep:
                sleeper.wake()
                _play("wake")
            with rec_lock:
                chunks.clear()
            log.info("PTT down - listening")

            def cb(indata, frames, t, status):
                with rec_lock:
                    chunks.append(indata.copy())
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
                    return
                text = stt.transcribe(audio)
                log.info("transcript: %r", text)
                if text:
                    self.handle_utterance(text)
            finally:
                idle.end("listen")

        idle.start()
        hotkey.listen(record_start, record_stop, key_name=self.cfg.hotkey.key)

    def run_bridge(self) -> None:
        from .voice import vocalinux_bridge
        # Two dedicated push-to-talk keys, both driven by utter's evdev
        # listener: dictation types text; assistant runs a screen action.
        vocalinux_bridge.install(
            self.handle_utterance,
            dictation_key=self.cfg.ptt.dictation_key,
            assistant_key=self.cfg.ptt.assistant_key,
        )
        log.info("vocalinux bridge installed (dictation=%s, assistant=%s)",
                 self.cfg.ptt.dictation_key, self.cfg.ptt.assistant_key)
        from . import sleep as _sleep
        _sleep.idle(self.cfg).start()
        saved = sys.argv
        sys.argv = [saved[0]]
        try:
            vocalinux_bridge.run()
        finally:
            sys.argv = saved


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="utter")
    ap.add_argument("--text", help="run a single text command and exit (no voice)")
    ap.add_argument("--dry-run", action="store_true", help="route only; do not execute")
    ap.add_argument("--bridge", action="store_true", help="reuse vocalinux recognition")
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("--log-level", default=None)
    args = ap.parse_args(argv)

    app = Utter(load_config(args.config), dry_run=args.dry_run)
    _setup_logging(args.log_level or app.cfg.log_level)
    app.setup()

    if args.text:
        return 0 if app.handle_utterance(args.text) else 1

    if args.bridge or app.cfg.general.trigger == "bridge":
        app.run_bridge()
    else:
        app.run_hotkey()
    return 0


if __name__ == "__main__":
    sys.exit(main())
