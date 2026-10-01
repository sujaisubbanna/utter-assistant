"""Text-to-speech on macOS.

Backends (``[macos] tts_backend``):
    "say"       the system ``/usr/bin/say`` CLI (default; no extra deps)
    "avspeech"  ``AVSpeechSynthesizer`` via PyObjC (in-process, same voices)
    "none"      spoken replies disabled

``speak()`` never raises and never blocks the caller for ``say`` (it is spawned
detached). No shell is used.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

_speaking: dict = {"proc": None, "synth": None}


def say_argv(text: str, voice: str = "", rate: int = 0) -> list[str]:
    """Build the ``say`` command line (pure; unit-tested)."""
    argv = ["say"]
    if voice:
        argv += ["-v", str(voice)]
    try:
        wpm = int(rate)
    except (TypeError, ValueError):
        wpm = 0
    if wpm > 0:
        argv += ["-r", str(wpm)]
    argv += ["--", str(text)]
    return argv


def stop() -> None:
    """Interrupt whatever is currently being spoken (best-effort)."""
    proc = _speaking.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
    _speaking["proc"] = None
    synth = _speaking.get("synth")
    if synth is not None:
        try:
            synth.stopSpeakingAtBoundary_(0)
        except Exception:  # noqa: BLE001
            pass


def _speak_say(text: str, voice: str, rate: int) -> bool:
    if not shutil.which("say"):
        logger.warning("tts: `say` not found on PATH")
        return False
    stop()
    try:
        _speaking["proc"] = subprocess.Popen(
            say_argv(text, voice, rate),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError as exc:
        logger.warning("tts: say failed: %s", exc)
        return False


def _speak_avspeech(text: str, voice: str, rate: int) -> bool:
    try:
        import AVFoundation  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("tts: pyobjc-framework-AVFoundation missing; falling back to `say`")
        return _speak_say(text, voice, rate)
    try:
        synth = _speaking.get("synth") or AVFoundation.AVSpeechSynthesizer.alloc().init()
        _speaking["synth"] = synth
        utt = AVFoundation.AVSpeechUtterance.speechUtteranceWithString_(text)
        if voice:
            v = AVFoundation.AVSpeechSynthesisVoice.voiceWithIdentifier_(voice) \
                or AVFoundation.AVSpeechSynthesisVoice.voiceWithLanguage_(voice)
            if v is not None:
                utt.setVoice_(v)
        if rate and int(rate) > 0:
            # AVSpeech rate is 0..1 (default 0.5 ~ 175-200 wpm); map wpm loosely.
            utt.setRate_(max(0.1, min(1.0, float(rate) / 400.0)))
        synth.speakUtterance_(utt)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("tts: AVSpeechSynthesizer failed (%s); falling back to `say`", exc)
        return _speak_say(text, voice, rate)


def speak(text: str, *, backend: str = "say", voice: str = "", rate: int = 0) -> bool:
    """Speak ``text``. Returns True when a backend accepted it."""
    text = (text or "").strip()
    if not text:
        return False
    backend = (backend or "say").strip().lower()
    if backend in ("none", "off", "false", "0"):
        return False
    if backend == "avspeech":
        return _speak_avspeech(text, voice, rate)
    return _speak_say(text, voice, rate)


def list_voices() -> list[str]:
    """Names of the installed ``say`` voices (empty if unavailable)."""
    if not shutil.which("say"):
        return []
    try:
        proc = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


__all__ = ["speak", "stop", "say_argv", "list_voices"]
