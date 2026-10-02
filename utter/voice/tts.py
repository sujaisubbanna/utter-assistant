"""Spoken replies (text-to-speech) facade.

Backend selection (:func:`backend_for`, pure and unit-tested):

* **macOS** — :mod:`utter.macos.tts` (``say`` / ``AVSpeechSynthesizer``)
  according to ``[macos]``, exactly as before.
* **Linux** — local engines, probed with ``shutil.which`` in this order:
  **piper** (when a voice model resolves), **espeak-ng**, **espeak**,
  **spd-say**. ``[tts] engine`` may force one or ``none``; ``[tts] language``
  follows the STT rules (``auto`` = system locale) and derives a default
  voice when ``[tts] voice`` is empty.
* Anything else — no backend.

Everything shells out with argv lists (never ``shell=True``), spawns instead
of waiting on the audio, and never raises: if no engine is installed,
:func:`speak` logs and returns ``False``. Adding a new engine means adding one
entry to :data:`LINUX_ENGINES`, an argv builder and a ``_speak_*`` function.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from utter import locale, platform

logger = logging.getLogger(__name__)

#: Linux engine preference order used by ``engine = "auto"``.
LINUX_ENGINES = ("piper", "espeak-ng", "espeak", "spd-say")

#: Raw players piper can stream into, best first (PipeWire, then PulseAudio, then ALSA).
_PIPER_PLAYERS = ("pw-play", "paplay", "aplay")

#: Where piper voice models are looked up. ``$UTTER_PIPER_VOICES`` is a
#: path-separator list; the rest are common install locations.
_PIPER_VOICE_DIRS = (
    Path.home() / ".local" / "share" / "piper" / "voices",
    Path.home() / ".local" / "share" / "piper",
    Path(__file__).resolve().parents[2] / "models" / "piper",
)

#: Processes the latest utterance spawned, so ``poll()`` reaps them promptly.
_speaking: list = []


# --------------------------------------------------------------------------- #
# backend selection (pure; unit-tested)
# --------------------------------------------------------------------------- #
def select_engine(engine: str = "auto", *, which=None, piper_model: Optional[str] = None) -> str:
    """Pick a Linux TTS engine.

    ``engine`` may be ``"auto"``/empty, ``"none"`` (or off/false/0) or an
    explicit engine name. An explicit engine that is not installed falls
    through to the auto order (degrade, don't break). Piper is only selected
    when it is installed *and* a voice model was resolved.
    """
    probe = shutil.which if which is None else which
    want = (engine or "auto").strip().lower()
    if want in ("none", "off", "false", "0"):
        return "none"
    if want != "auto" and want in LINUX_ENGINES and probe(want):
        return want
    if probe("piper") and piper_model:
        return "piper"
    for name in ("espeak-ng", "espeak", "spd-say"):
        if probe(name):
            return name
    return "none"


def backend_for(platform_name: str, macos_cfg=None, *, tts_cfg=None, which=None) -> str:
    """Name of the TTS backend used on ``platform_name`` (pure; unit-tested).

    macOS keeps its historical shape (``[macos] tts_backend``); Linux probes
    the local engines, preferring piper when a voice model resolves.
    """
    if platform_name == platform.MACOS:
        return (getattr(macos_cfg, "tts_backend", "say") or "say").strip().lower()
    if platform_name != platform.LINUX:
        return "none"
    engine = getattr(tts_cfg, "engine", "auto") if tts_cfg is not None else "auto"
    piper_model = None
    if engine in ("", "auto", "piper"):
        piper_model = resolve_piper_model(
            getattr(tts_cfg, "voice", "") if tts_cfg is not None else "",
            getattr(tts_cfg, "language", locale.AUTO) if tts_cfg is not None else locale.AUTO,
        )
    return select_engine(engine, which=which, piper_model=piper_model)


# --------------------------------------------------------------------------- #
# argv builders / voice mapping (pure; unit-tested)
# --------------------------------------------------------------------------- #
def espeak_voice_for(language_code: Optional[str]) -> str:
    """Map a resolved BCP-47 code to an espeak-ng voice name.

    ``en-GB``/``en-US`` keep the region (espeak has ``en-gb``/``en-us``);
    other languages use the base code (``de-DE`` → ``de``, ``pt-BR`` → ``pt``).
    Unknown/auto yields ``""`` so espeak uses its own default.
    """
    code = locale.normalize_locale(language_code)
    if not code:
        return ""
    base = locale.base_language(code) or ""
    if base == "en" and "-" in code:
        return code.lower()
    return base


def espeak_argv(engine: str, text: str, voice: str = "") -> list[str]:
    """``espeak-ng``/``espeak`` command line (argv only, no shell)."""
    argv = [engine]
    if voice:
        argv += ["-v", str(voice)]
    argv += ["--", str(text)]
    return argv


def spd_say_argv(text: str, language_code: Optional[str] = None, voice: str = "") -> list[str]:
    """``spd-say`` command line (speech-dispatcher)."""
    argv = ["spd-say"]
    base = locale.base_language(language_code)
    if base:
        argv += ["-l", base]
    if voice:
        argv += ["-y", str(voice)]
    argv += ["--", str(text)]
    return argv


def piper_argv(model_path: str) -> list[str]:
    """``piper`` command line: raw 16-bit PCM on stdout for a player to read."""
    return ["piper", "--model", str(model_path), "--output-raw"]


def player_argv(player: str, sample_rate: int) -> list[str]:
    """argv for the raw-audio player that consumes piper's stdout."""
    rate = str(int(sample_rate))
    if player == "pw-play":
        return ["pw-play", "--format=s16", f"--rate={rate}", "--channels=1", "-"]
    if player == "paplay":
        return ["paplay", "--raw", "--format=s16le", f"--rate={rate}", "--channels=1"]
    if player == "aplay":
        return ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", rate, "-"]
    return [player]


def piper_sample_rate(model_path: str, default: int = 22050) -> int:
    """Sample rate from the ``<model>.onnx.json`` companion, else ``default``."""
    try:
        doc = json.loads(Path(f"{model_path}.json").read_text(encoding="utf-8"))
        rate = int(doc.get("audio", {}).get("sample_rate") or doc.get("sample_rate") or 0)
        return rate if rate > 0 else default
    except (OSError, ValueError, TypeError):
        return default


def resolve_piper_model(voice: str = "", language_code: Optional[str] = None,
                        *, dirs=None, is_file=None) -> Optional[str]:
    """Resolve a Piper ``.onnx`` model from ``[tts] voice`` or the language.

    ``voice`` may be a path/name; otherwise the first model matching the
    language (``de_DE-*`` then ``de_*``) in the piper voice directories wins.
    Returns ``None`` when nothing is found (callers fall back to espeak).
    """
    check = (lambda p: Path(p).is_file()) if is_file is None else is_file
    text = (voice or "").strip()
    if text:
        path = Path(text).expanduser()
        if str(path).lower().endswith(".onnx") and check(path):
            return str(path)
        stems = [text, text.replace("-", "_"), text.replace("_", "-")]
        for directory in _search_dirs(dirs):
            for stem in stems:
                exact = directory / f"{stem}.onnx"
                if check(exact):
                    return str(exact)
            for stem in stems:
                matches = sorted(directory.glob(f"*{stem}*.onnx"))
                if matches:
                    return str(matches[0])
        return None
    code = locale.normalize_locale(language_code)
    if not code:
        return None
    base = locale.base_language(code) or ""
    region = code.split("-")[1] if "-" in code else ""
    patterns = []
    if region:
        patterns += [f"{base}_{region.upper()}-*.onnx", f"{base}_{region.lower()}-*.onnx"]
    patterns += [f"{base}_*.onnx", f"{base}-*.onnx"]
    for directory in _search_dirs(dirs):
        for pattern in patterns:
            matches = sorted(directory.glob(pattern))
            if matches:
                return str(matches[0])
    return None


def _search_dirs(dirs=None) -> list:
    if dirs is not None:
        return [Path(d) for d in dirs]
    out: list = []
    env = os.environ.get("UTTER_PIPER_VOICES")
    if env:
        out += [Path(p).expanduser() for p in env.split(os.pathsep) if p]
    out += list(_PIPER_VOICE_DIRS)
    return out


# --------------------------------------------------------------------------- #
# spawning
# --------------------------------------------------------------------------- #
def _reap() -> None:
    """Drop finished children (``poll()`` also reaps them)."""
    _speaking[:] = [proc for proc in _speaking if proc.poll() is None]


def _spawn(argv: list, **kwargs) -> bool:
    """Spawn ``argv`` detached. Returns False (and logs) instead of raising."""
    try:
        _speaking.append(subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, **kwargs,
        ))
        return True
    except (OSError, ValueError) as exc:
        logger.warning("tts: could not run %s: %s", argv[0], exc)
        return False


def stop() -> None:
    """Interrupt whatever is currently being spoken (best-effort)."""
    for proc in _speaking:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
    _speaking.clear()


# --------------------------------------------------------------------------- #
# Linux engines
# --------------------------------------------------------------------------- #
def _speak_espeak(engine: str, text: str, voice: str) -> bool:
    return _spawn(espeak_argv(engine, text, voice))


def _speak_spd(text: str, language_code: Optional[str], voice: str) -> bool:
    return _spawn(spd_say_argv(text, language_code, voice))


def _speak_piper(text: str, model_path: str, language_code: Optional[str]) -> bool:
    player = next((name for name in _PIPER_PLAYERS if shutil.which(name)), None)
    if not player:
        logger.warning("tts: piper needs an audio player (pw-play, paplay or aplay)")
        return False
    rate = piper_sample_rate(model_path)
    producer = None
    try:
        producer = subprocess.Popen(
            piper_argv(model_path),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        consumer = subprocess.Popen(
            player_argv(player, rate),
            stdin=producer.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _speaking.extend([producer, consumer])
        if producer.stdout is not None:
            producer.stdout.close()  # the child owns the pipe now
        if producer.stdin is not None:
            try:
                producer.stdin.write(text.encode("utf-8"))
                producer.stdin.close()
            except (BrokenPipeError, OSError):
                logger.warning("tts: piper stopped before receiving the text")
                return False
        return True
    except (OSError, ValueError) as exc:
        logger.warning("tts: piper failed: %s", exc)
        if producer is not None and producer.poll() is None:
            try:
                producer.terminate()
            except OSError:
                pass
        return False


def _speak_linux(text: str, tts_cfg=None) -> bool:
    """Speak on Linux with the configured/preferred local engine. Never raises."""
    if tts_cfg is not None and not bool(getattr(tts_cfg, "enabled", True)):
        logger.debug("tts: spoken replies disabled by [tts] enabled=false")
        return False
    engine = backend_for(platform.LINUX, None, tts_cfg=tts_cfg)
    if engine == "none":
        logger.warning(
            "tts: no local speech engine found (install espeak-ng, espeak or spd-say); "
            "spoken replies are disabled"
        )
        return False
    language_code = locale.resolve(
        getattr(tts_cfg, "language", locale.AUTO) if tts_cfg is not None else locale.AUTO
    )
    voice = (getattr(tts_cfg, "voice", "") if tts_cfg is not None else "") or ""
    voice = str(voice).strip()
    _reap()
    try:
        if engine == "piper":
            model = resolve_piper_model(voice, language_code)
            if model:
                return _speak_piper(text, model, language_code)
            logger.warning("tts: piper has no voice model; falling back to espeak-ng")
            engine = select_engine("auto", piper_model=None)
            if engine == "none":
                return False
        if engine in ("espeak-ng", "espeak"):
            return _speak_espeak(engine, text, voice or espeak_voice_for(language_code))
        if engine == "spd-say":
            return _speak_spd(text, language_code, voice)
        logger.warning("tts: unsupported Linux engine %r", engine)
        return False
    except Exception as exc:  # noqa: BLE001 - TTS must never break voice
        logger.warning("tts: %s failed: %s", engine, exc)
        return False


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def speak(text: str, cfg=None) -> bool:
    """Speak ``text`` if the platform has a backend. Never raises."""
    text = (text or "").strip()
    if not text:
        return False
    if platform.is_macos():
        macos_cfg = getattr(cfg, "macos", cfg)
        backend = backend_for(platform.MACOS, macos_cfg)
        if backend == "none":
            return False
        try:
            from utter.macos import tts as _tts

            return _tts.speak(text, backend=backend,
                              voice=getattr(macos_cfg, "tts_voice", "") or "",
                              rate=int(getattr(macos_cfg, "tts_rate", 0) or 0))
        except Exception as exc:  # noqa: BLE001
            logger.debug("tts failed: %s", exc)
            return False
    if platform.is_linux():
        return _speak_linux(text, getattr(cfg, "tts", None))
    return False


__all__ = [
    "LINUX_ENGINES",
    "backend_for",
    "espeak_argv",
    "espeak_voice_for",
    "piper_argv",
    "piper_sample_rate",
    "player_argv",
    "resolve_piper_model",
    "select_engine",
    "speak",
    "spd_say_argv",
    "stop",
]