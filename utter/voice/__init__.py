"""Voice lane: push-to-talk hotkey, local STT, and the optional vocalinux bridge.

Modules:
    hotkey              evdev global push-to-talk (no root, no exclusive grab)
    stt                 whisper.cpp / faster-whisper transcription
    vocalinux_bridge    reuse vocalinux's mic+STT, intercept triggered commands
"""
from __future__ import annotations

__all__ = ["hotkey", "stt", "vocalinux_bridge"]
