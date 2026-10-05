"""Speech-to-text for utter.

Backends (selected by ``config.STTConfig.backend``):
    "whisper_cpp"    pywhispercpp (no GPU required; model stays resident)
    "faster_whisper" optional, only if the package is importable
    "none"           transcription disabled
    "apple_speech"   macOS only: Speech.framework via PyObjC (utter.macos.speech)
    "vocamac"        macOS only: an installed VocaMac.app's file-transcription CLI

On macOS the ``[macos]`` section picks an ordered chain (primary + fallback),
see :func:`select_backends`; a backend that fails to load hands over to the
next one. On Linux the chain is exactly ``[stt.backend]`` as before.

Public API:
    transcribe(pcm: numpy.ndarray) -> str
    Transcriber(...).transcribe(pcm) -> str

``pcm`` is float32 mono PCM at 16 kHz in [-1, 1]. The model is loaded lazily on
the first call and kept resident; ``transcribe()`` never reloads it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from utter import locale as language
try:
    from utter.config import STTConfig, load_config
except Exception:  # pragma: no cover - config package should always import
    STTConfig = None  # type: ignore
    load_config = None  # type: ignore

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Whisper ".en" checkpoints (distil-small.en, ggml-base.en-q5_1, ...) are
# English-only; a non-English `[stt] language` with one of these is a
# configuration mistake we warn about loudly instead of silently mis-hearing.
_ENGLISH_ONLY_RE = re.compile(r"(?:^|[.-])en(?:[.-]|$)")

#: Multilingual models the UI offers (name, approximate download size). Kept
#: here so Python and the settings UI describe the same choices. Nothing is
#: downloaded automatically; the user picks one explicitly.
MULTILINGUAL_MODELS = (("small", "~480 MB"), ("large-v3-turbo", "~1.6 GB"))


def is_english_only_model(model: str) -> bool:
    """True for Whisper ``.en`` variants (English-only checkpoints)."""
    name = Path(str(model or "")).name.lower()
    if name.endswith(".bin"):
        name = name[:-4]
    return bool(_ENGLISH_ONLY_RE.search(name))

# Where to look for a whisper.cpp ggml model, in order. Override with
# $UTTER_WHISPER_MODEL (a full path) or $UTTER_MODELS_DIR.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL_DIRS = [
    _REPO_ROOT / "models" / "whisper",
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


def _store_root() -> Optional[Path]:
    """Where the ``assistant`` model store lives (``manifests/`` + ``blobs/``).

    Prefers ``assistant.util.models_root`` (which honours ``$UTTER_MODELS`` and
    performs the one-time legacy migration); falls back to the same XDG path when
    the ``assistant`` core is not importable (the legacy daemon ships ``utter``
    alone).
    """
    try:
        from assistant.util import models_root  # imported lazily: optional core
        return Path(models_root())
    except Exception:  # noqa: BLE001 - assistant core is optional for the daemon
        override = os.environ.get("UTTER_MODELS")
        if override:
            return Path(override).expanduser()
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        return base / "utter-models"


def _iter_store_manifests(root: Path):
    """Yield ``(manifest_path, data)`` for every store manifest under ``root``."""
    base = root / "manifests"
    if not base.is_dir():
        return
    for path in sorted(base.glob("*/*/*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            yield path, data


def _store_model_candidates(model: str) -> list:
    """ggml paths for ``model`` inside the store, resolved through manifests.

    A store pull keeps the bytes content-addressed as ``blobs/sha256-<hex>`` and
    records the original filename in the manifest, so a blob is found by matching
    the manifest rather than by scanning for ``*.bin``. Any ``*.bin`` a user
    dropped into the store is offered too.
    """
    root = _store_root()
    if root is None:
        return []
    name = Path(model).name if model else _DEFAULT_WHISPERCPP_NAME
    wanted = {name, f"ggml-{name}.bin", Path(name).stem}
    out: list = []

    blobs = root / "blobs"
    if blobs.is_dir():
        out.extend(sorted(blobs.glob("*.bin")))

    for _path, data in _iter_store_manifests(root):
        mname = str(data.get("name") or "")
        for entry in data.get("files", []) or []:
            fname = Path(str(entry.get("name") or "")).name
            matches = (
                fname in wanted
                or Path(fname).stem in wanted
                or mname in wanted
                or bool(model and model in fname)
            )
            blob = entry.get("path")
            if matches and blob:
                out.append(Path(blob))
    return out


def _candidate_model_paths(model: str) -> list:
    """Build the ordered list of ggml model paths to probe for ``model``."""
    candidates: list = []
    name = Path(model).name if model else _DEFAULT_WHISPERCPP_NAME

    if model and Path(model).expanduser().is_file():
        candidates.append(Path(model).expanduser())

    search_dirs = list(_DEFAULT_MODEL_DIRS)
    store = _store_root()
    if store is not None:
        search_dirs.append(store)
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

    # The store's blobs are named sha256-<hex>, so resolve them via manifests.
    candidates.extend(_store_model_candidates(model))

    # De-dup, preserving order.
    seen = set()
    unique = []
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _pywhispercpp_cached_path(name: str) -> Optional[Path]:
    """Return a cached pywhispercpp ggml path for ``name`` if one exists.

    pywhispercpp stores downloaded models as ``ggml-<name>.bin`` in its own
    ``MODELS_DIR`` (e.g. ``ggml-base.en.bin``). Our directory scan does not look
    there, so a cached model was misreported as "will download". The import is
    lazy because the pywhispercpp native extension is heavy and optional.
    """
    if not name:
        return None
    raw = Path(name).expanduser()
    if raw.is_file():
        return raw
    try:
        from pywhispercpp.constants import MODELS_DIR
    except Exception:  # noqa: BLE001 - pywhispercpp is an optional backend
        return None
    for cand in (MODELS_DIR / f"ggml-{name}.bin", MODELS_DIR / f"{name}.bin", MODELS_DIR / name):
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


KNOWN_BACKENDS = ("whisper_cpp", "faster_whisper", "apple_speech", "vocamac", "none")
MACOS_ONLY_BACKENDS = ("apple_speech", "vocamac")

# Where VocaMac installs its binary (Homebrew cask / drag-install).
VOCAMAC_BINARIES = (
    "/Applications/VocaMac.app/Contents/MacOS/VocaMac",
    "~/Applications/VocaMac.app/Contents/MacOS/VocaMac",
)


def _backend_available(name: str, *, has_module, which) -> bool:
    if name == "whisper_cpp":
        return has_module("pywhispercpp")
    if name == "faster_whisper":
        return has_module("faster_whisper")
    if name == "apple_speech":
        return has_module("Speech") and has_module("Foundation")
    if name == "vocamac":
        return any(Path(b).expanduser().is_file() for b in VOCAMAC_BINARIES) or bool(which("VocaMac"))
    return name == "none"


def select_backends(platform_name: str, stt_cfg=None, macos_cfg=None, *,
                    has_module=None, which=None) -> list:
    """Ordered STT backend chain for this platform (pure; unit-tested).

    * Linux (and anything that is not Darwin): ``[stt.backend]`` exactly, so
      behaviour is unchanged.
    * macOS: ``[macos.stt_backend, macos.stt_fallback]`` with duplicates and
      ``none`` removed. Backends whose runtime is missing are moved behind the
      ones that are present; if nothing is importable the configured order is
      returned unchanged so the error message names the configured backend.
    """
    primary = getattr(stt_cfg, "backend", "whisper_cpp") or "whisper_cpp"
    if platform_name != "darwin" or macos_cfg is None:
        return [primary]
    if has_module is None or which is None:
        from utter import platform as _plat
        has_module = has_module or _plat.has_module
        which = which or _plat.which
    chain: list = []
    for name in (getattr(macos_cfg, "stt_backend", "") or primary,
                 getattr(macos_cfg, "stt_fallback", "") or ""):
        name = (name or "").strip()
        if name and name != "none" and name not in chain:
            chain.append(name)
    if not chain:
        return [primary]
    present = [n for n in chain if _backend_available(n, has_module=has_module, which=which)]
    missing = [n for n in chain if n not in present]
    return (present + missing) if present else chain


class Transcriber:
    """Lazily-loaded, resident transcriber with an optional fallback chain.

    Attributes:
        backend: the backend that is active (after load) or configured.
        fallbacks: backends tried in order when ``backend`` fails to load.
        model_path: resolved model path/name for the active backend.
        load_time_s: wall-clock seconds the most recent model load took.
    """

    def __init__(self, cfg=None, *, model_path: Optional[str] = None,
                 backend: Optional[str] = None, fallbacks: Optional[list] = None,
                 macos_cfg=None):
        if cfg is None:
            cfg = load_config().stt if load_config is not None else None
        self.cfg = cfg
        self.macos_cfg = macos_cfg
        self.backend = backend or (getattr(cfg, "backend", "whisper_cpp") if cfg else "whisper_cpp")
        self.fallbacks: list = list(fallbacks or [])
        self._explicit_model_path = model_path
        self.model_path: Optional[str] = model_path
        self.load_time_s: Optional[float] = None
        # Language reported by the most recent transcription (detected when the
        # backend provides it, otherwise the requested code; None for auto).
        self.last_language: Optional[str] = None
        self._model = None
        self._lock = threading.Lock()

    @property
    def language(self) -> Optional[str]:
        """Resolved BCP-47 spoken language, or ``None`` for auto/unknown.

        Reads ``[stt] language`` on every call (so tests and live config
        edits see the current value) and delegates ``"auto"`` to the system
        locale. Never guesses English.
        """
        value = language.AUTO
        if self.cfg is not None:
            value = getattr(self.cfg, "language", language.AUTO) or language.AUTO
        return language.resolve(value)

    def _warn_english_only(self, model_ref: str) -> None:
        """Warn when a non-English language is paired with an ``.en`` model.

        The model is never swapped and nothing is downloaded automatically: an
        English-only checkpoint would simply mis-transcribe. The warning names
        the setting and the multilingual options the Voice page offers.
        """
        resolved = self.language
        if not resolved or language.is_english(resolved):
            return
        if not is_english_only_model(model_ref):
            return
        choices = ", ".join(name for name, _size in MULTILINGUAL_MODELS)
        logger.warning(
            "STT language is %s but model %r is English-only (.en). Set "
            "[stt] model to a multilingual model (%s) — no model is downloaded "
            "automatically. Until then, non-English speech will be mis-transcribed.",
            resolved, model_ref, choices,
        )

    @classmethod
    def for_platform(cls, cfg=None, *, model_path: Optional[str] = None,
                     platform_name: Optional[str] = None):
        """Build a transcriber whose backend chain matches the host platform.

        ``cfg`` may be a full :class:`utter.config.Config` or just its ``stt``
        section. On Linux this is identical to ``Transcriber(cfg.stt)``.
        """
        from utter import platform as _plat

        full = cfg if cfg is not None else (load_config() if load_config is not None else None)
        stt_cfg = getattr(full, "stt", full)
        macos_cfg = getattr(full, "macos", None)
        chain = select_backends(platform_name or _plat.name(), stt_cfg, macos_cfg)
        return cls(stt_cfg, model_path=model_path, backend=chain[0], fallbacks=chain[1:],
                   macos_cfg=macos_cfg)

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
            # pywhispercpp may already hold the model in its own cache even
            # though our scan missed it; only warn when it is truly absent.
            cached = _pywhispercpp_cached_path(name)
            if cached is not None:
                logger.debug("whisper.cpp model %r already cached at %s", name, cached)
                return str(cached)
            logger.warning("no local model file for %r; pywhispercpp will download it", name)
            return name
        fallback = os.environ.get("UTTER_WHISPER_MODEL", "base.en")
        cached = _pywhispercpp_cached_path(fallback)
        if cached is not None:
            logger.debug("whisper.cpp fallback model %r already cached at %s", fallback, cached)
            return str(cached)
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
        self._warn_english_only(model_ref)
        # Leave one core for the UI/audio threads. Using every core makes ggml's
        # OpenMP barrier spin against the rest of the daemon and, with a second
        # model in the OSD, could deadlock. One model + one spare core is plenty.
        n_threads = max(1, (os.cpu_count() or 2) - 1)
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
        self._warn_english_only(model_ref)
        from utter import platform
        if platform.is_macos() and device == "cuda":
            device = "cpu"
            compute_type = "int8"
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

    def _load_apple_speech(self):
        from utter.macos.speech import AppleSpeechRecognizer

        mc = self.macos_cfg
        # Spoken language first: a resolved `[stt] language` (e.g. de-DE) beats
        # the macOS `speech_locale`; unknown falls back to it, then en-US.
        fallback = (getattr(mc, "speech_locale", "") if mc is not None else "") or "en-US"
        locale_code = self.language or fallback
        rec = AppleSpeechRecognizer(
            locale=locale_code,
            on_device=bool(getattr(mc, "on_device_only", True)),
        )
        rec.load()
        self.last_language = rec.locale
        self.model_path = f"Speech.framework/{rec.locale}" + ("/on-device" if rec.on_device else "")
        return rec

    def _load_vocamac(self):
        import shutil

        for cand in VOCAMAC_BINARIES:
            path = Path(cand).expanduser()
            if path.is_file():
                self.model_path = str(path)
                return str(path)
        found = shutil.which("VocaMac")
        if found:
            self.model_path = found
            return found
        raise RuntimeError("STT backend 'vocamac' needs VocaMac.app (brew install --cask vocamac)")

    def _load_one(self, backend: str):
        if backend in (None, "", "none"):
            raise RuntimeError("STT backend is 'none'; no transcriber configured")
        if backend == "whisper_cpp":
            return self._load_whisper_cpp()
        if backend == "faster_whisper":
            return self._load_faster_whisper()
        if backend == "apple_speech":
            return self._load_apple_speech()
        if backend == "vocamac":
            return self._load_vocamac()
        raise ValueError(f"unknown STT backend: {backend!r}")

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            start = time.perf_counter()
            errors: list = []
            for backend in [self.backend, *self.fallbacks]:
                try:
                    self._model = self._load_one(backend)
                except Exception as exc:  # noqa: BLE001 - try the next backend
                    if not self.fallbacks:
                        raise
                    errors.append(f"{backend}: {exc}")
                    logger.warning("STT backend %s unavailable (%s); trying next", backend, exc)
                    continue
                if backend != self.backend:
                    logger.info("STT fell back from %s to %s", self.backend, backend)
                self.backend = backend
                break
            if self._model is None:
                raise RuntimeError("no STT backend could be loaded: " + "; ".join(errors))
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
        if self.backend == "apple_speech":
            try:
                return _clean_text(self._model.transcribe(audio, SAMPLE_RATE))
            except Exception as exc:
                if self.fallbacks:
                    logger.warning("apple_speech failed at runtime (%s); trying fallback %s",
                                   exc, self.fallbacks[0])
                    for fallback in list(self.fallbacks):
                        try:
                            self._model = self._load_one(fallback)
                            self.backend = fallback
                            self.fallbacks.remove(fallback)
                            return self.transcribe(audio)
                        except Exception as fb_exc:
                            logger.warning("fallback %s failed: %s", fallback, fb_exc)
                            continue
                raise
        if self.backend == "vocamac":
            return self._transcribe_vocamac(audio)
        raise ValueError(f"unknown STT backend: {self.backend!r}")

    def _transcribe_vocamac(self, audio: np.ndarray) -> str:
        """Shell out to VocaMac's headless ``--transcribe-file`` mode (no IPC exists)."""
        import json
        import subprocess
        import tempfile

        from utter.macos.speech import write_wav

        fd, tmp = tempfile.mkstemp(prefix="utter-vocamac-", suffix=".wav")
        os.close(fd)
        try:
            write_wav(audio, tmp, SAMPLE_RATE)
            proc = subprocess.run([self._model, "--transcribe-file", tmp, "--json"],
                                  capture_output=True, text=True, timeout=120)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if proc.returncode != 0:
            raise RuntimeError(f"VocaMac failed: {(proc.stderr or proc.stdout).strip()}")
        out = proc.stdout.strip()
        try:
            doc = json.loads(out)
            if isinstance(doc, dict):
                out = str(doc.get("text") or doc.get("transcript") or doc.get("transcription") or "")
        except json.JSONDecodeError:
            pass
        return _clean_text(out)

    def _transcribe_whisper_cpp(self, audio: np.ndarray) -> str:
        # `None` tells whisper.cpp to auto-detect (pywhispercpp accepts None,
        # "" or "auto"); never fall back to the old hardcoded "en".
        lang = language.base_language(self.language)
        kwargs = {
            "language": lang,
            "print_realtime": False,
            "print_progress": False,
            "print_timestamps": False,
        }
        try:
            segments = self._model.transcribe(audio, **kwargs)
        except (TypeError, ValueError):
            # Older/leaner pywhispercpp builds may not accept the print_* params.
            segments = self._model.transcribe(audio, language=lang)
        self.last_language = lang
        logger.debug("whisper_cpp transcription language: %s", lang or "auto")
        return _clean_text(" ".join(getattr(s, "text", "") for s in segments))

    def _transcribe_faster_whisper(self, audio: np.ndarray) -> str:
        lang = language.base_language(self.language)
        kwargs = {"vad_filter": False}
        if lang is not None:
            kwargs["language"] = lang
        segments, info = self._model.transcribe(audio, **kwargs)
        # faster-whisper reports the language it actually detected in `info`.
        detected = getattr(info, "language", None) if info is not None else None
        self.last_language = detected or lang
        if detected and lang and detected != lang:
            logger.warning("faster-whisper transcribed as %s (configured %s)", detected, lang)
        logger.debug("faster-whisper transcription language: %s", self.last_language or "auto")
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
                _default = Transcriber.for_platform()
    return _default


def transcribe(pcm: np.ndarray) -> str:
    """Transcribe float32 mono 16 kHz PCM using the resident default model."""
    return get_default_transcriber().transcribe(pcm)


def reset_default() -> None:
    """Drop the default transcriber (test helper)."""
    global _default
    with _default_lock:
        _default = None
