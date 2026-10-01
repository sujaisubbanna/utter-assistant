"""Voice lane: push-to-talk hotkey and local STT.

Modules:
    hotkey              evdev global push-to-talk (no root, no exclusive grab)
    stt                 whisper.cpp / faster-whisper transcription
"""
from __future__ import annotations

__all__ = ["hotkey", "stt"]
