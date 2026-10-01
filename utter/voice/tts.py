"""Spoken replies (text-to-speech) facade.

On macOS this routes to :mod:`utter.macos.tts` (``say`` / ``AVSpeechSynthesizer``)
according to ``[macos]``. On Linux the assistant has no built-in TTS engine
here (spoken replies are produced by the plugin lane), so :func:`speak` is a
no-op that returns False, exactly as before this module existed.
"""
from __future__ import annotations

import logging

from utter import platform

logger = logging.getLogger(__name__)


def backend_for(platform_name: str, macos_cfg=None) -> str:
    """Name of the TTS backend used on ``platform_name`` (pure; unit-tested)."""
    if platform_name != platform.MACOS:
        return "none"
    return (getattr(macos_cfg, "tts_backend", "say") or "say").strip().lower()


def speak(text: str, cfg=None) -> bool:
    """Speak ``text`` if the platform has a backend. Never raises."""
    macos_cfg = getattr(cfg, "macos", cfg)
    backend = backend_for(platform.name(), macos_cfg)
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


__all__ = ["speak", "backend_for"]
