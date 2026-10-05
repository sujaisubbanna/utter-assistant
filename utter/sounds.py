"""Small synthesized UI sounds played over PipeWire, non-blocking.

Sounds are generated on first use (stdlib only, no assets needed) into
``<repo>/sounds/`` and played with ``pw-play`` (fallback ``paplay``) detached.

Names: "start" (assistant listening), "dictate" (dictation listening),
"typed" (dictation typed), "sleep" / "wake" (sleep mode), "detected" (command understood),
"not_detected" (no command matched).
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import wave
from array import array
from pathlib import Path

_SAMPLE_RATE = 48000
_ROOT = Path(__file__).resolve().parents[1]
_SOUND_DIR = _ROOT / "sounds"

# name -> list of (frequency_hz, duration_s); 0 Hz = silence
_RECIPES: dict[str, list[tuple[float, float]]] = {
    "start": [(660.0, 0.070), (0.0, 0.015), (880.0, 0.085)],
    "detected": [(660.0, 0.055), (990.0, 0.055), (1320.0, 0.085)],
    "not_detected": [(520.0, 0.090), (0.0, 0.015), (392.0, 0.110)],
    # dictation: a soft falling pair (assistant "start" rises), then a tick when typed
    "dictate": [(784.0, 0.060), (0.0, 0.012), (587.0, 0.090)],
    "typed": [(1175.0, 0.040)],
    # sleep mode: a slow falling triad down to sleep, rising back up on wake
    "sleep": [(784.0, 0.080), (0.0, 0.020), (587.0, 0.080), (0.0, 0.020), (392.0, 0.160)],
    "wake": [(392.0, 0.060), (0.0, 0.012), (587.0, 0.060), (0.0, 0.012), (784.0, 0.110)],
}

_GAIN = 0.40
_ATTACK_S = 0.006
_RELEASE_S = 0.055


def _synth(recipe: list[tuple[float, float]], path: Path) -> None:
    samples = array("h")
    phase = 0.0
    for freq, dur in recipe:
        n = int(_SAMPLE_RATE * dur)
        if freq <= 0:
            samples.extend([0] * n)
            continue
        for i in range(n):
            # simple attack/release envelope
            if i < _ATTACK_S * _SAMPLE_RATE:
                env = i / (_ATTACK_S * _SAMPLE_RATE)
            elif i > n - _RELEASE_S * _SAMPLE_RATE:
                env = max(0.0, (n - i) / (_RELEASE_S * _SAMPLE_RATE))
            else:
                env = 1.0
            phase += 2.0 * math.pi * freq / _SAMPLE_RATE
            samples.append(int(max(-1.0, min(1.0, _GAIN * env * math.sin(phase))) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(samples.tobytes())


def _ensure(name: str) -> Path | None:
    if name not in _RECIPES:
        return None
    path = _SOUND_DIR / f"{name}.wav"
    if path.exists() and path.stat().st_size > 44:
        return path
    try:
        _SOUND_DIR.mkdir(parents=True, exist_ok=True)
        _synth(_RECIPES[name], path)
    except Exception:
        return None
    return path if path.exists() else None


def _player(sink: str | None = None) -> list[str] | None:
    """The player command, targeting ``sink`` when one is configured.

    ``sink`` falls back to ``UTTER_SOUND_SINK``. Empty = the system default
    output, exactly as before. ``afplay`` (macOS) ignores the sink.
    """
    if sink is None:
        sink = os.environ.get("UTTER_SOUND_SINK", "")
    if shutil.which("pw-play"):
        base = ["pw-play", "--volume=0.35"]
        return [*base, "--target", sink] if sink else base
    if shutil.which("paplay"):
        base = ["paplay", "--volume=11500"]
        return [*base, "--device", sink] if sink else base
    if shutil.which("afplay"):  # macOS
        return ["afplay", "-v", "0.35"]
    return None


def play(name: str) -> None:
    """Play a UI sound without blocking. No-op if disabled or no player."""
    if os.environ.get("UTTER_SOUNDS", "1") in ("0", "false", "no"):
        return
    path = _ensure(name)
    if path is None:
        return
    player = _player()
    if player is None:
        return
    try:
        subprocess.Popen(
            [*player, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass
