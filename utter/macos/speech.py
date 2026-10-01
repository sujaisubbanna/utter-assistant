"""Apple ``Speech.framework`` speech-to-text (macOS only).

Wraps ``SFSpeechRecognizer`` through PyObjC. Audio is handed over as a WAV
file via ``SFSpeechURLRecognitionRequest`` (the simplest, most robust bridge
from numpy PCM to the framework; no AVAudioEngine involvement). Recognition can
be pinned on-device with ``requiresOnDeviceRecognition`` so nothing leaves the
machine.

Public API (mirrors the whisper backends in :mod:`utter.voice.stt`):

    AppleSpeechRecognizer(locale="en-US", on_device=True)
        .available() -> bool            # PyObjC + framework + permission
        .load()                         # create the recognizer, ask permission
        .transcribe(pcm_float32_16k) -> str

Everything PyObjC is imported lazily; importing this module on Linux is fine.

Known limits (documented in docs/MACOS.md):
    * one-shot requests are capped by Apple at ~1 minute of audio;
    * on-device recognition needs a locale with a downloaded model, otherwise
      the request fails and the caller falls back to whisper.cpp;
    * the first call prompts for the Speech Recognition permission.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# SFSpeechRecognizerAuthorizationStatus
AUTH_NOT_DETERMINED = 0
AUTH_DENIED = 1
AUTH_RESTRICTED = 2
AUTH_AUTHORIZED = 3

_DEFAULT_TIMEOUT_S = 30.0


def framework_importable() -> bool:
    """True when the PyObjC ``Speech`` and ``Foundation`` bindings exist."""
    from utter.platform import has_module

    return has_module("Speech") and has_module("Foundation")


def write_wav(pcm, path: str, sample_rate: int = SAMPLE_RATE) -> str:
    """Write float32 mono PCM in [-1, 1] (or int16) to a 16-bit WAV file."""
    import numpy as np

    arr = np.asarray(pcm)
    if arr.ndim > 1:
        arr = arr.mean(axis=tuple(range(1, arr.ndim)))
    if np.issubdtype(arr.dtype, np.integer):
        data = arr.astype("<i2")
    else:
        data = np.clip(arr.astype("float32"), -1.0, 1.0)
        data = (data * 32767.0).astype("<i2")
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(int(sample_rate))
        fh.writeframes(data.tobytes())
    return path


class AppleSpeechRecognizer:
    """One-shot recogniser over Apple's Speech framework."""

    backend = "apple_speech"

    def __init__(self, locale: str = "en-US", on_device: bool = True,
                 timeout_s: float = _DEFAULT_TIMEOUT_S):
        self.locale = locale or "en-US"
        self.on_device = bool(on_device)
        self.timeout_s = float(timeout_s)
        self._recognizer = None
        self._lock = threading.Lock()
        self.auth_status: Optional[int] = None

    # -- availability --------------------------------------------------------
    @staticmethod
    def available() -> bool:
        from utter.platform import is_macos

        return is_macos() and framework_importable()

    def _request_authorization(self) -> int:
        """Ask for Speech Recognition permission; returns the final status."""
        import Speech  # type: ignore[import-not-found]

        status = int(Speech.SFSpeechRecognizer.authorizationStatus())
        if status != AUTH_NOT_DETERMINED:
            return status
        done = threading.Event()
        result = {"status": status}

        def _cb(new_status):
            result["status"] = int(new_status)
            done.set()

        Speech.SFSpeechRecognizer.requestAuthorization_(_cb)
        done.wait(self.timeout_s)
        return int(result["status"])

    def load(self) -> None:
        """Create the recognizer (idempotent) and make sure we are authorised."""
        if self._recognizer is not None:
            return
        with self._lock:
            if self._recognizer is not None:
                return
            if not framework_importable():
                raise RuntimeError(
                    "STT backend 'apple_speech' needs PyObjC's Speech framework "
                    "(pip install pyobjc-framework-Speech)"
                )
            import Foundation  # type: ignore[import-not-found]
            import Speech  # type: ignore[import-not-found]

            self.auth_status = self._request_authorization()
            if self.auth_status != AUTH_AUTHORIZED:
                raise RuntimeError(
                    "Speech Recognition permission not granted "
                    f"(status={self.auth_status}); allow it under System Settings "
                    "-> Privacy & Security -> Speech Recognition"
                )
            ns_locale = Foundation.NSLocale.localeWithLocaleIdentifier_(self.locale)
            rec = Speech.SFSpeechRecognizer.alloc().initWithLocale_(ns_locale)
            if rec is None:
                raise RuntimeError(f"SFSpeechRecognizer unavailable for locale {self.locale!r}")
            if not rec.isAvailable():
                raise RuntimeError("SFSpeechRecognizer reports it is not available right now")
            if self.on_device and hasattr(rec, "supportsOnDeviceRecognition") \
                    and not rec.supportsOnDeviceRecognition():
                raise RuntimeError(
                    f"on-device recognition is not supported for {self.locale!r}; "
                    "download the dictation language or set [macos] on_device_only=false"
                )
            self._recognizer = rec

    @property
    def loaded(self) -> bool:
        return self._recognizer is not None

    def unload(self) -> None:
        with self._lock:
            self._recognizer = None

    # -- inference -----------------------------------------------------------
    def transcribe(self, pcm, sample_rate: int = SAMPLE_RATE) -> str:
        """Transcribe float32 mono PCM; returns ``""`` for silence/no result."""
        import numpy as np

        audio = np.asarray(pcm)
        if audio.size == 0:
            return ""
        self.load()
        fd, tmp = tempfile.mkstemp(prefix="utter-speech-", suffix=".wav")
        os.close(fd)
        try:
            write_wav(audio, tmp, sample_rate)
            return self._recognize_file(tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def transcribe_file(self, path: str) -> str:
        self.load()
        return self._recognize_file(str(Path(path).expanduser()))

    def _recognize_file(self, path: str) -> str:
        import Foundation  # type: ignore[import-not-found]
        import Speech  # type: ignore[import-not-found]

        url = Foundation.NSURL.fileURLWithPath_(path)
        request = Speech.SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)
        request.setShouldReportPartialResults_(False)
        if self.on_device and hasattr(request, "setRequiresOnDeviceRecognition_"):
            request.setRequiresOnDeviceRecognition_(True)

        done = threading.Event()
        out = {"text": "", "error": None}

        def _handler(result, error):
            if result is not None:
                try:
                    out["text"] = str(result.bestTranscription().formattedString())
                except Exception as exc:  # noqa: BLE001 - defensive around ObjC
                    out["error"] = str(exc)
                if result.isFinal():
                    done.set()
                    return
            if error is not None:
                out["error"] = str(error.localizedDescription())
                done.set()

        self._recognizer.recognitionTaskWithRequest_resultHandler_(request, _handler)
        if not done.wait(self.timeout_s):
            raise TimeoutError(f"apple_speech recognition timed out after {self.timeout_s:.0f}s")
        if out["error"] and not out["text"]:
            raise RuntimeError(f"apple_speech failed: {out['error']}")
        return (out["text"] or "").strip()


__all__ = ["AppleSpeechRecognizer", "framework_importable", "write_wav",
           "AUTH_AUTHORIZED", "AUTH_DENIED", "AUTH_NOT_DETERMINED", "AUTH_RESTRICTED"]
