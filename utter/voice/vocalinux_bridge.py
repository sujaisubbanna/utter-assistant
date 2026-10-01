"""Two-key push-to-talk bridge that reuses vocalinux's microphone + STT.

vocalinux types every recognised utterance into the focused window. This module
monkeypatches its single text choke point
(``vocalinux.text_injection.text_injector.TextInjector.inject_text``) and drives
vocalinux's own recognition from two dedicated evdev keys:

* **dictation** (``dictation_key``)  -> transcript is typed as normal.
* **assistant** (``assistant_key``)  -> transcript is routed to ``callback``
  (utter) and is **NEVER typed**, for the whole session.

Importing this module never requires vocalinux to be installed.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

__all__ = ["install", "uninstall", "run", "match_trigger", "set_mode",
           "get_mode", "in_assistant_context"]

Callback = Callable[[str], object]

_ORIG_ATTR = "_utter_original_inject_text"
_ASSISTANT_GRACE_S = 20.0

_state: dict = {
    "installed": False,
    "callback": None,
    "triggers": (),
    "predicate": None,
    "mode": None,
    "assistant_until": 0.0,
    "manager": None,
    "init_patched": False,
    "osd": None,
}


def _manager_audio() -> list:
    """Snapshot vocalinux's live PCM buffer (16-bit mono chunks). Additive."""
    m = _state.get("manager")
    buf = getattr(m, "audio_buffer", None) if m is not None else None
    if not buf:
        return []
    lock = getattr(m, "_buffer_lock", None)
    if lock is not None:
        try:
            with lock:
                return list(buf)
        except Exception:
            pass
    try:
        return list(buf)
    except Exception:
        return []


def _osd_emit(method: str, *args) -> None:
    """Best-effort OSD call; a missing/disabled emitter is a no-op."""
    em = _state.get("osd")
    if em is None:
        return
    try:
        getattr(em, method)(*args)
    except Exception:
        logger.exception("utter OSD %s failed", method)


def _osd_listening(mode: str = "assistant") -> None:
    _osd_emit("listening", mode)


def _osd_idle() -> None:
    _osd_emit("idle")


def match_trigger(text: str, trigger_prefixes: Iterable[str]) -> Optional[str]:
    if not text:
        return None
    stripped = text.lstrip()
    lowered = stripped.lower()
    for raw in trigger_prefixes:
        trigger = (raw or "").strip().lower()
        if not trigger or not lowered.startswith(trigger):
            continue
        rest = stripped[len(trigger):]
        if rest and (rest[0].isalnum() or rest[0] == "_"):
            continue
        return rest.lstrip(" \t,;:.-").strip()
    return None


def set_mode(mode: Optional[str]) -> None:
    _state["mode"] = mode


def get_mode() -> Optional[str]:
    return _state.get("mode")


def in_assistant_context() -> bool:
    """True while an assistant utterance is (or may still be) in flight."""
    return (_state.get("mode") == "assistant"
            or time.time() < _state.get("assistant_until", 0.0))


def _play(name: str) -> None:
    try:
        from .. import sounds
        sounds.play(name)
    except Exception:
        pass


def _type_and_report(original, injector, text: str) -> bool:
    """Type a dictation transcript and show the result on the overlay."""
    try:
        from .. import sleep as _sleep
        _sleep.touch("dictation")
    except Exception:
        pass
    ok = bool(original(injector, text))
    if _state.get("mode") == "dictation":
        _osd_emit("final", text, ok)
        _play("typed" if ok else "not_detected")
    return ok


def _idle_begin(token: str) -> None:
    """Hold the idle-sleep timer while `token` (e.g. listening) is in progress."""
    try:
        from .. import sleep as _sleep
        _sleep.idle().begin(token)
    except Exception:
        logger.debug("idle begin(%s) failed", token, exc_info=True)


def _idle_end(token: str) -> None:
    try:
        from .. import sleep as _sleep
        _sleep.idle().end(token)
    except Exception:
        logger.debug("idle end(%s) failed", token, exc_info=True)


def _run_callback(cb: Callback, text: str) -> bool:
    try:
        return bool(cb(text))
    except Exception:
        logger.exception("utter bridge callback raised")
        return True


def _start_ptt_hotkey(key_name: str, mode: str) -> None:
    """Hold -> start vocalinux recognition in `mode`. Ignores key auto-repeat."""
    from . import hotkey as _hotkey

    held = {"v": False}

    def on_press() -> None:
        if held["v"]:
            return  # auto-repeat: ignore until release
        held["v"] = True
        # A key press is Utter activity: hold the idle-sleep timer until
        # recognition has gone back to IDLE (or failed to start).
        _idle_begin("listen")
        # Asleep? Any push-to-talk key wakes Utter, then listens as usual.
        try:
            from .. import sleep as _sleep
            sleeper = _sleep.get()
            if sleeper.asleep:
                sleeper.wake()
                _play("wake")
        except Exception:
            logger.exception("wake on %s key failed", mode)
        _state["mode"] = mode
        if mode == "assistant":
            _state["assistant_until"] = 0.0  # window begins on release
        else:
            _state["assistant_until"] = 0.0  # dictation cancels any assistant window
        # Distinct cues so you can hear which mode you're in.
        _play("start" if mode == "assistant" else "dictate")
        m = _state.get("manager")
        if m is None:
            logger.warning("%s key pressed but recognition manager not ready", mode)
            _osd_idle()
            _idle_end("listen")
            return
        # Show the overlay for the duration of the hold, styled per mode.
        _osd_listening(mode)
        try:
            started = m.start_recognition(mode="push_to_talk")
            logger.info("%s PTT started=%s", mode, started)
            if not started:
                _osd_idle()
                _idle_end("listen")
        except Exception:
            logger.exception("%s start_recognition failed", mode)
            _osd_idle()
            _idle_end("listen")

    def on_release() -> None:
        if not held["v"]:
            return
        held["v"] = False
        if mode == "assistant":
            _state["assistant_until"] = time.time() + _ASSISTANT_GRACE_S
        m = _state.get("manager")
        if m is None:
            _idle_end("listen")
            return
        try:
            m.stop_recognition()
        except Exception:
            logger.exception("%s stop_recognition failed", mode)
            # Failure path: don't leave the overlay stuck on "listening".
            _osd_idle()
            _idle_end("listen")

    threading.Thread(target=_hotkey.listen, args=(on_press, on_release, key_name),
                     daemon=True, name=f"utter-ptt-{mode}").start()
    logger.info("%s PTT key: %s", mode, key_name)



def _unload_speech() -> None:
    """Sleep hook: drop the speech model(s) held by this process."""
    import gc
    m = _state.get("manager")
    if m is not None:
        m.model = None
        if hasattr(m, "_model_initialized"):
            m._model_initialized = False
    em = _state.get("osd")
    if em is not None and hasattr(em, "_transcriber"):
        em._transcriber = None  # re-created on demand
    gc.collect()
    logger.info("speech model unloaded (sleep)")


def _reload_speech() -> None:
    """Wake hook: load the configured speech engine again."""
    m = _state.get("manager")
    if m is not None and getattr(m, "model", None) is None:
        m._init_selected_engine()
        logger.info("speech model reloaded (wake)")


def _register_sleep_hooks() -> None:
    try:
        from .. import sleep as _sleep
        sleeper = _sleep.get()
        if not _state.get("sleep_hooks"):
            sleeper.on_unload(_unload_speech)
            sleeper.on_reload(_reload_speech)
            _state["sleep_hooks"] = True
    except Exception:
        logger.exception("could not register sleep hooks")

def install(
    callback: Callback,
    dictation_key: Optional[str] = None,
    assistant_key: Optional[str] = None,
    trigger_prefixes: Optional[Iterable[str]] = None,
    predicate: Optional[Callable[[str], bool]] = None,
) -> None:
    from vocalinux.text_injection.text_injector import TextInjector

    _state["callback"] = callback
    _state["triggers"] = tuple(trigger_prefixes) if trigger_prefixes else ()
    _state["predicate"] = predicate

    # Additive: optional OSD emitter (no-op when disabled). Never fatal.
    if _state.get("osd") is None:
        try:
            from . import osd as _osd

            _state["osd"] = _osd.OsdEmitter(audio_source=_manager_audio)
        except Exception:
            logger.exception("could not initialise utter OSD emitter")
            _state["osd"] = None

    if (dictation_key or assistant_key) and not _state["init_patched"]:
        try:
            from vocalinux.speech_recognition.recognition_manager import (
                SpeechRecognitionManager as _SRM,
            )
            _orig_init = _SRM.__init__

            def _init(self, *a, **k):
                _orig_init(self, *a, **k)
                _state["manager"] = self
                try:
                    def _on_state(state) -> None:
                        if getattr(state, "name", "") == "IDLE":
                            if _state.get("mode") == "assistant":
                                _state["assistant_until"] = max(
                                    _state.get("assistant_until", 0.0), time.time() + 3.0)
                            _state["mode"] = None
                            _osd_emit("on_recognition_idle")
                            # Listening (and transcribing) is over: release
                            # the idle-sleep hold; the countdown restarts now.
                            _idle_end("listen")
                    self.register_state_callback(_on_state)
                except Exception:
                    logger.exception("could not register recognition state callback")
                # Additive: forward live audio level to the OSD emitter.
                try:
                    em = _state.get("osd")
                    if em is not None and hasattr(self, "register_audio_level_callback"):
                        self.register_audio_level_callback(em.level)
                except Exception:
                    logger.exception("could not register OSD audio level callback")

            _SRM.__init__ = _init
            _state["init_patched"] = True
        except Exception:
            logger.exception("could not hook SpeechRecognitionManager")

    if not _state["installed"]:
        original = TextInjector.inject_text

        def patched_inject_text(self, text: str) -> bool:
            # Assistant context: route, NEVER type.
            if in_assistant_context():
                cb = _state["callback"]
                em = _state.get("osd")
                if cb is not None:
                    def _run_and_emit() -> None:
                        activated = _run_callback(cb, text)
                        if em is not None:
                            shown = text
                            try:
                                from .. import sleep as _sleep
                                if _sleep.get().asleep:
                                    shown = "Asleep · hold a key to wake"
                            except Exception:
                                pass
                            _osd_emit("final", shown, activated)
                    threading.Thread(target=_run_and_emit, daemon=True).start()
                elif em is not None:
                    _osd_emit("final", text, False)
                logger.info("utter assistant (never typed): %r", text)
                return True

            triggers = _state["triggers"]
            if triggers:
                cmd = match_trigger(text, triggers)
                if cmd is not None:
                    cb = _state["callback"]
                    if cmd and cb is not None:
                        _run_callback(cb, cmd)
                    return True
                return _type_and_report(original, self, text)

            pred = _state["predicate"]
            if pred is not None and pred(text):
                cb = _state["callback"]
                if cb is not None:
                    threading.Thread(target=_run_callback, args=(cb, text),
                                     daemon=True).start()
                return True
            return _type_and_report(original, self, text)

        setattr(patched_inject_text, _ORIG_ATTR, original)
        setattr(patched_inject_text, "__name__", "utter_patched_inject_text")
        TextInjector.inject_text = patched_inject_text
        _state["installed"] = True

    if dictation_key:
        _start_ptt_hotkey(dictation_key, "dictation")
    if assistant_key:
        _start_ptt_hotkey(assistant_key, "assistant")

    _register_sleep_hooks()
    logger.info("installed utter bridge (dictation_key=%s, assistant_key=%s)",
                dictation_key, assistant_key)


def uninstall() -> None:
    try:
        from vocalinux.text_injection.text_injector import TextInjector
    except Exception:
        return
    current = TextInjector.inject_text
    original = getattr(current, _ORIG_ATTR, None)
    if original is not None:
        TextInjector.inject_text = original
    em = _state.get("osd")
    if em is not None:
        _osd_idle()
        try:
            em.close()
        except Exception:
            logger.exception("could not close utter OSD emitter")
    _state.update(installed=False, callback=None, mode=None, assistant_until=0.0, osd=None)
    logger.info("uninstalled utter vocalinux bridge")


def run() -> None:
    from vocalinux.main import main

    main()


if __name__ == "__main__":  # pragma: no cover
    install(lambda text: print(f"[utter] assistant: {text}") or True)
    run()
