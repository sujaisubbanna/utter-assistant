"""Text-to-speech on Windows.

Backends (selected by ``[tts] engine``; see
:func:`utter.voice.tts.backend_for`):

    "sapi"      the built-in SAPI 5 ``SpVoice`` via ``comtypes`` (default)
    "pyttsx3"   the ``pyttsx3`` package (also SAPI on Windows)
    "none"      spoken replies disabled

The interface mirrors :mod:`utter.macos.tts`: ``speak(text, *, backend="sapi",
voice="", rate=0)`` and ``stop()``. ``speak()`` never raises and does not block
the caller (SAPI is asked to speak asynchronously; pyttsx3 runs on a daemon
thread). Every Windows-only import (``comtypes``, ``pyttsx3``) is lazy, so this
module imports on Linux/macOS too.
"""
from __future__ import annotations

import logging
import math
import threading
from typing import Optional

logger = logging.getLogger(__name__)

#: Windows engines accepted by :func:`speak`.
WINDOWS_ENGINES = ("sapi", "pyttsx3")

#: SPF_ASYNC | SPF_PURGEBEFORESPEAK for ``ISpVoice::Speak``.
_SPF_ASYNC = 1
_SPF_PURGE = 2
_SPF_ASYNC_PURGE = _SPF_ASYNC | _SPF_PURGE

# Reused COM/engine objects so ``stop()`` can interrupt the current utterance.
_sapi: dict = {"voice": None}
_pyttsx3: dict = {"engine": None}


def _rate_to_sapi(rate) -> int:
    """Map words-per-minute (0 = engine default) to SAPI's -10..10 scale."""
    try:
        wpm = int(rate)
    except (TypeError, ValueError):
        return 0
    if wpm <= 0:
        return 0
    # SAPI's default is roughly 200 wpm at Rate=0; each step is ~2x per 10.
    steps = int(round(10.0 * math.log2(wpm / 200.0)))
    return max(-10, min(10, steps))


def _select_sapi_voice(voice_obj, name: str) -> None:
    """Best-effort SAPI voice selection by loose name match."""
    if not name:
        return
    try:
        voices = voice_obj.GetVoices()
        for i in range(voices.Count):
            cand = voices.Item(i)
            if name.lower() in str(cand.GetDescription()).lower():
                voice_obj.Voice = cand
                return
        logger.warning("tts: no SAPI voice matching %r", name)
    except Exception as exc:  # noqa: BLE001 - voice selection is best-effort
        logger.debug("tts: SAPI voice selection failed: %s", exc)


def _speak_sapi(text: str, voice: str, rate) -> bool:
    try:
        import comtypes  # type: ignore[import-not-found]
        import comtypes.client  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("tts: comtypes missing; falling back to pyttsx3")
        return _speak_pyttsx3(text, voice, rate)
    try:
        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001 - already initialised on this thread
        pass
    try:
        stop()
        voice_obj = _sapi.get("voice")
        if voice_obj is None:
            voice_obj = comtypes.client.CreateObject("SAPI.SpVoice")
            _sapi["voice"] = voice_obj
        _select_sapi_voice(voice_obj, voice)
        voice_obj.Rate = _rate_to_sapi(rate)
        # SPF_ASYNC returns immediately and speaks on SAPI's own thread.
        voice_obj.Speak(str(text), _SPF_ASYNC)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: SAPI failed (%s); falling back to pyttsx3", exc)
        return _speak_pyttsx3(text, voice, rate)


def _speak_pyttsx3(text: str, voice: str, rate) -> bool:
    try:
        import pyttsx3  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("tts: neither comtypes nor pyttsx3 is installed")
        return False
    try:
        engine = _pyttsx3.get("engine")
        if engine is None:
            engine = pyttsx3.init()
            _pyttsx3["engine"] = engine
        if voice:
            for cand in engine.getProperty("voices") or []:
                ident = str(getattr(cand, "id", ""))
                label = str(getattr(cand, "name", ""))
                if voice == ident or voice.lower() in label.lower():
                    engine.setProperty("voice", ident)
                    break
        try:
            wpm = int(rate)
        except (TypeError, ValueError):
            wpm = 0
        if wpm > 0:
            engine.setProperty("rate", wpm)
        engine.say(str(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: pyttsx3 failed: %s", exc)
        return False

    def _run() -> None:
        try:
            engine.runAndWait()
        except Exception as exc:  # noqa: BLE001
            logger.warning("tts: pyttsx3 failed: %s", exc)

    threading.Thread(target=_run, name="utter-tts-win", daemon=True).start()
    return True


def stop() -> None:
    """Interrupt whatever is currently being spoken (best-effort)."""
    voice_obj = _sapi.get("voice")
    if voice_obj is not None:
        try:
            voice_obj.Speak("", _SPF_ASYNC_PURGE)
        except Exception:  # noqa: BLE001
            pass
    engine = _pyttsx3.get("engine")
    if engine is not None:
        try:
            engine.stop()
        except Exception:  # noqa: BLE001
            pass


def speak(text: str, *, backend: str = "sapi", voice: str = "", rate: int = 0) -> bool:
    """Speak ``text``. Returns True when a backend accepted it. Never raises."""
    text = (text or "").strip()
    if not text:
        return False
    backend = (backend or "sapi").strip().lower()
    if backend in ("none", "off", "false", "0"):
        return False
    if backend == "pyttsx3":
        return _speak_pyttsx3(text, voice, rate)
    return _speak_sapi(text, voice, rate)


def list_voices() -> list[str]:
    """Names of the installed SAPI voices (empty if unavailable)."""
    try:
        import comtypes.client  # type: ignore[import-not-found]
    except ImportError:
        return []
    try:
        voice_obj = _sapi.get("voice") or comtypes.client.CreateObject("SAPI.SpVoice")
        _sapi["voice"] = voice_obj
        voices = voice_obj.GetVoices()
        return [str(voices.Item(i).GetDescription()) for i in range(voices.Count)]
    except Exception:  # noqa: BLE001
        return []


__all__ = ["speak", "stop", "list_voices", "WINDOWS_ENGINES"]
