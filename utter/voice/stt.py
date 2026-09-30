"""Speech-to-text for utter.

Backends (selected by ``config.STTConfig.backend``):
    "whisper_cpp"    pywhispercpp (no GPU required; model stays resident)
    "faster_whisper" optional, only if the package is importable
    "none"           transcription disabled (e.g. vocalinux bridge supplies text)

Public API:
    transcribe(pcm: numpy.ndarray) -> str
    Transcriber(...).transcribe(pcm) -> str

``pcm`` is float32 mono PCM at 16 kHz in [-1, 1]. The model is loaded lazily on
the first call and kept resident; ``transcribe()`` never reloads it.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from utter.config import STTConfig, load_config
except Exception:  # pragma: no cover - config package should always import
    STTConfig = None  # type: ignore
    load_config = None  # type: ignore

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Where to look for a whisper.cpp ggml model, in order. Override with
# $UTTER_WHISPER_MODEL (a full path) or $UTTER_MODELS_DIR.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL_DIRS = [
    _REPO_ROOT / "models" / "whisper",
    Path.home() / ".local" / "share" / "vocalinux" / "models" / "whispercpp",
    Path.home() / ".cache" / "whisper",
]
_DEFAULT_WHISPERCPP_NAME = "ggml-small.en.bin"

# Non-speech artefacts emitted by whisper for silence/noise.
_NON_SPEECH_RE = re.compile(r"^\s*(?:\[[^\]]*\]|\([^)]*\)|[♪♫♬♩♭♮♯\s.,!?;:\-]*)\s*$")


def _as_float32_mono(pcm: np.ndarray) -> np.ndarray:
    """Normalise arbitrary PCM input to contiguous float32 mono in [-1, 1]."""
    arr = np.asarray(pcm)
    if arr.ndim > 1:
        arr = arr.mean(axis=tuple(range(1, arr.ndim)))
    if np.issubdtype(arr.dtype, np.integer):
        info = np.iinfo(arr.dtype)
        scale = max(abs(info.min), info.max)
        arr = arr.astype(np.float32) / float(scale)
    elif arr.dtype != np.float32:
        arr = arr.astype(np.float32)
    return np.ascontiguousarray(arr, dtype=np.float32)


def _clean_text(text: str) -> str:
    """Join/trim whisper output and drop pure non-speech artefacts."""
    text = (text or "").strip()
    if not text:
        return ""
    if _NON_SPEECH_RE.match(text):
        return ""
    return text


def _candidate_model_paths(model: str) -> list:
    """Build the ordered list of ggml model paths to probe for ``model``."""
    candidates: list = []
    name = Path(model).name if model else _DEFAULT_WHISPERCPP_NAME

    if model and Path(model).expanduser().is_file():
        candidates.append(Path(model).expanduser())

    search_dirs = _DEFAULT_MODEL_DIRS
    env_dir = os.environ.get("UTTER_MODELS_DIR")
    if env_dir:
        search_dirs = [Path(env_dir).expanduser()] + search_dirs

    for d in search_dirs:
        if not d.is_dir():
            continue
        if model and not model.endswith(".bin"):
            # "small.en" -> prefer "ggml-small.en.bin", then any "*small.en*.bin"
            exact = d / f"ggml-{model}.bin"
            if exact.is_file():
                candidates.append(exact)
            candidates.extend(sorted(d.glob(f"*{model}*.bin")))
        direct = d / name
        if direct.is_file():
            candidates.append(direct)

    # De-dup, preserving order.
    seen = set()
    unique = []
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


class Transcriber:
    """Lazily-loaded, resident whisper transcriber.

    Attributes:
        backend: resolved backend name (``whisper_cpp`` / ``faster_whisper``).
        model_path: resolved model path/name for the active backend.
        load_time_s: wall-clock seconds the most recent model load took.
    """

    def __init__(self, cfg=None, *, model_path: Optional[str] = None):
        if cfg is None:
            cfg = load_config().stt if load_config is not None else None
        self.cfg = cfg
        self.backend = getattr(cfg, "backend", "whisper_cpp") if cfg else "whisper_cpp"
        self._explicit_model_path = model_path
        self.model_path: Optional[str] = model_path
        self.load_time_s: Optional[float] = None
        self._model = None
        self._lock = threading.Lock()

    # -- loading -----------------------------------------------------------
    def _resolve_whispercpp_model(self) -> str:
        """Return a ggml path if one exists, else a name pywhispercpp can download."""
        env_model = os.environ.get("UTTER_WHISPER_MODEL")
        requested = self._explicit_model_path or env_model or getattr(self.cfg, "model", "")
        for path in _candidate_model_paths(requested):
            if path.is_file():
                logger.info("found whisper.cpp model: %s", path)
                return str(path)
        # No local file: if the configured name is a real whisper.cpp model name
        # let pywhispercpp download it; otherwise fall back to a safe default.
        name = (requested or "").strip()
        valid = {"tiny", "tiny.en", "base", "base.en", "small", "small.en",
                 "medium", "medium.en", "large", "large-v1", "large-v2", "large-v3"}
        if name in valid:
            logger.warning("no local model file for %r; pywhispercpp will download it", name)
            return name
        fallback = os.environ.get("UTTER_WHISPER_MODEL", "base.en")
        logger.warning(
            "no local whisper.cpp model found (looked for %r); pywhispercpp will "
            "download %r", requested, fallback,
        )
        return fallback

    def _load_whisper_cpp(self):
        try:
            from pywhispercpp.model import Model  # imported lazily by design
        except ImportError as exc:
            raise RuntimeError(
                "STT backend 'whisper_cpp' requires pywhispercpp "
                "(pip install pywhispercpp)"
            ) from exc

        model_ref = self._resolve_whispercpp_model()
        self.model_path = model_ref
        n_threads = max(1, (os.cpu_count() or 4))
        logger.info("loading whisper.cpp model %s (n_threads=%d)", model_ref, n_threads)
        return Model(model_ref, n_threads=n_threads)

    def _load_faster_whisper(self):
        try:
            from faster_whisper import WhisperModel  # optional dependency
        except ImportError as exc:
            raise RuntimeError(
                "STT backend 'faster_whisper' requires the faster-whisper package "
                "(pip install faster-whisper); use backend='whisper_cpp' instead"
            ) from exc

        cfg = self.cfg
        model_ref = self._explicit_model_path or getattr(cfg, "model", "base")
        device = getattr(cfg, "device", "cpu") or "cpu"
        compute_type = getattr(cfg, "compute_type", "int8") or "int8"
        self.model_path = model_ref
        logger.info(
            "loading faster-whisper model %s (device=%s compute_type=%s)",
            model_ref, device, compute_type,
        )
        try:
            return WhisperModel(model_ref, device=device, compute_type=compute_type)
        except Exception as exc:
            logger.warning("faster-whisper %s/%s failed (%s); retrying on CPU", device, compute_type, exc)
            return WhisperModel(model_ref, device="cpu", compute_type="int8")

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            if self.backend in (None, "", "none"):
                raise RuntimeError("STT backend is 'none'; no transcriber configured")
            start = time.perf_counter()
            if self.backend == "whisper_cpp":
                self._model = self._load_whisper_cpp()
            elif self.backend == "faster_whisper":
                self._model = self._load_faster_whisper()
            else:
                raise ValueError(f"unknown STT backend: {self.backend!r}")
            self.load_time_s = time.perf_counter() - start
            logger.info("STT model loaded in %.2fs (backend=%s)", self.load_time_s, self.backend)

    def load(self) -> None:
        """Eagerly load the model (optional; transcribe loads lazily)."""
        self._ensure_loaded()

    def unload(self) -> None:
        """Drop the resident model (mainly for tests)."""
        with self._lock:
            self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    # -- inference ---------------------------------------------------------
    def transcribe(self, pcm: np.ndarray) -> str:
        """Transcribe float32 mono 16 kHz PCM into text."""
        audio = _as_float32_mono(pcm)
        if audio.size == 0:
            return ""
        self._ensure_loaded()
        if self.backend == "whisper_cpp":
            return self._transcribe_whisper_cpp(audio)
        if self.backend == "faster_whisper":
            return self._transcribe_faster_whisper(audio)
        raise ValueError(f"unknown STT backend: {self.backend!r}")

    def _transcribe_whisper_cpp(self, audio: np.ndarray) -> str:
        kwargs = {
            "language": "en",
            "print_realtime": False,
            "print_progress": False,
            "print_timestamps": False,
        }
        try:
            segments = self._model.transcribe(audio, **kwargs)
        except (TypeError, ValueError):
            # Older/leaner pywhispercpp builds may not accept the print_* params.
            segments = self._model.transcribe(audio, language="en")
        return _clean_text(" ".join(getattr(s, "text", "") for s in segments))

    def _transcribe_faster_whisper(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(audio, language="en", vad_filter=False)
        return _clean_text(" ".join(s.text for s in segments))


# -- module-level convenience API -----------------------------------------

_default: Optional[Transcriber] = None
_default_lock = threading.Lock()


def get_default_transcriber() -> Transcriber:
    """Return (creating once) the process-wide default Transcriber."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = Transcriber()
    return _default


def transcribe(pcm: np.ndarray) -> str:
    """Transcribe float32 mono 16 kHz PCM using the resident default model."""
    return get_default_transcriber().transcribe(pcm)


def reset_default() -> None:
    """Drop the default transcriber (test helper)."""
    global _default
    with _default_lock:
        _default = None
