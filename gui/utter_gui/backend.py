"""Async backend: subprocesses, the ``assistant`` CLI, systemd and parsing.

Everything here runs off the UI thread. Subprocess I/O is driven by the GLib
main loop (``Gio.Subprocess`` + ``*_async`` calls), so the interface never
blocks. Callers hand in plain callables; they are invoked on the main loop.
"""
from __future__ import annotations

import array
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib  # noqa: E402

from . import config  # noqa: E402

SERVICES = [
    ("utter-runner", "Runner", "Plugin supervisor and trust boundary"),
    ("utter-bridge", "Voice bridge", "Reuses vocalinux recognition"),
    ("utter-vision", "Vision", "Screenshot grounding service"),
    ("utter-planner", "Planner", "Small text-LLM planner"),
    ("utter-audio-defaults", "Audio defaults", "Applies the input/output profile"),
]
SERVICE_UNITS = [unit for unit, _label, _desc in SERVICES]
STT_BACKENDS = [
    ("faster_whisper", "faster-whisper", "CUDA/CPU, CTranslate2"),
    ("whisper_cpp", "whisper.cpp", "portable C++ build"),
    ("vosk", "Vosk", "offline plugin (needs the Vosk plugin)"),
    ("parakeet", "Parakeet", "NVIDIA plugin (needs the Parakeet plugin)"),
    ("remote", "Remote", "external STT over the network"),
    ("none", "None", "the bridge supplies transcripts"),
]
LLM_PROVIDERS = [
    ("vllm", "vLLM", "http://127.0.0.1:8001/v1"),
    ("ollama", "Ollama", "http://127.0.0.1:11434/v1"),
    ("llamacpp", "llama.cpp", "http://127.0.0.1:8080/v1"),
    ("remote", "Remote (OpenAI-compatible)", ""),
]
TTS_ENGINES = [
    ("espeak-ng", "espeak-ng", ["espeak-ng"]),
    ("espeak", "eSpeak", ["espeak"]),
    ("spd-say", "Speech Dispatcher", ["spd-say"]),
    ("piper", "Piper", ["piper"]),
]


# --------------------------------------------------------------------------- #
# environment discovery
# --------------------------------------------------------------------------- #
def find_python(repo: Path) -> str:
    """Pick an interpreter that can run ``python -m assistant`` (and gi)."""
    candidates = []
    env = os.environ.get("UTTER_PYTHON")
    if env:
        candidates.append(env)
    candidates += [
        str(repo / ".venv-agent" / "bin" / "python"),
        str(repo / ".venv" / "bin" / "python"),
        shutil.which("python3") or "python3",
    ]
    for cand in candidates:
        if cand and (cand == "python3" or Path(cand).exists()):
            return cand
    return "python3"


def human_bytes(n: Optional[int | float]) -> str:
    if n is None:
        return "?"
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


# --------------------------------------------------------------------------- #
# async process wrapper
# --------------------------------------------------------------------------- #
class Proc:
    """A running subprocess whose I/O is delivered on the GLib main loop."""

    def __init__(self, argv: list[str], cwd: Optional[str] = None,
                 silence_stderr: bool = False):
        self.argv = [str(a) for a in argv]
        self._cancellable = Gio.Cancellable()
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        if silence_stderr:
            flags |= Gio.SubprocessFlags.STDERR_SILENCE
        launcher = Gio.SubprocessLauncher.new(flags)
        if cwd:
            launcher.set_cwd(str(cwd))
        self.error: Optional[str] = None
        try:
            self.subprocess: Optional[Gio.Subprocess] = launcher.spawnv(self.argv)
        except GLib.Error as exc:  # executable missing, etc.
            self.subprocess = None
            self.error = str(exc)

    # -- one-shot -------------------------------------------------------- #
    def communicate(self, on_done: Callable[[int, str, str], None]) -> None:
        """on_done(rc, stdout, stderr)"""
        if self.subprocess is None:
            GLib.idle_add(on_done, 127, "", self.error or "failed to start")
            return
        self.subprocess.communicate_utf8_async(
            None, self._cancellable, self._communicate_cb, on_done
        )

    def _communicate_cb(self, proc: Gio.Subprocess, res: Gio.AsyncResult, on_done) -> None:
        try:
            ok, out, err = proc.communicate_utf8_finish(res)
        except GLib.Error as exc:
            on_done(-1, "", str(exc))
            return
        rc = proc.get_exit_status() if ok else -1
        on_done(rc, out or "", err or "")

    # -- line streaming -------------------------------------------------- #
    def stream_lines(
        self,
        on_line: Callable[[str], None],
        on_done: Callable[[int], None],
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> None:
        if self.subprocess is None:
            GLib.idle_add(on_done, 127)
            return
        self._on_line = on_line
        self._on_stderr = on_stderr
        self._on_done = on_done
        self._pending = 2
        self._read_lines(
            Gio.DataInputStream.new(self.subprocess.get_stdout_pipe()), on_line
        )
        err_pipe = self.subprocess.get_stderr_pipe()
        if err_pipe is None:
            self._pending -= 1
        else:
            self._read_lines(
                Gio.DataInputStream.new(err_pipe), on_stderr or (lambda _s: None)
            )

    def _read_lines(self, stream: Gio.DataInputStream, cb) -> None:
        stream.read_line_async(GLib.PRIORITY_DEFAULT, self._cancellable, self._line_cb, (stream, cb))

    def _line_cb(self, stream: Gio.DataInputStream, res: Gio.AsyncResult, data) -> None:
        _stream, cb = data
        try:
            line, _length = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            self._pending -= 1
            if self._pending <= 0:
                self._wait_finish()
            return
        cb(line)
        self._read_lines(stream, cb)

    # -- byte streaming (microphone) ------------------------------------- #
    def stream_bytes(
        self,
        on_bytes: Callable[[bytes], None],
        on_done: Callable[[int], None],
        chunk: int = 8192,
    ) -> None:
        if self.subprocess is None:
            GLib.idle_add(on_done, 127)
            return
        self._on_bytes = on_bytes
        self._on_done = on_done
        self._chunk = chunk
        self._stream = Gio.DataInputStream.new(self.subprocess.get_stdout_pipe())
        self._read_bytes()

    def _read_bytes(self) -> None:
        self._stream.read_bytes_async(
            self._chunk, GLib.PRIORITY_DEFAULT, self._cancellable, self._bytes_cb
        )

    def _bytes_cb(self, stream: Gio.DataInputStream, res: Gio.AsyncResult) -> None:
        try:
            data = stream.read_bytes_finish(res)
        except GLib.Error:
            self._wait_finish()
            return
        if data is None or data.get_size() == 0:
            self._wait_finish()
            return
        self._on_bytes(bytes(data.get_data()))
        self._read_bytes()

    # -- shutdown -------------------------------------------------------- #
    def _wait_finish(self) -> None:
        assert self.subprocess is not None
        self.subprocess.wait_async(self._cancellable, self._wait_cb)

    def _wait_cb(self, proc: Gio.Subprocess, res: Gio.AsyncResult) -> None:
        try:
            proc.wait_finish(res)
        except GLib.Error:
            pass
        self._on_done(proc.get_exit_status())

    def cancel(self) -> None:
        self._cancellable.cancel()
        if self.subprocess is not None:
            try:
                if not self.subprocess.get_if_exited():
                    self.subprocess.force_exit()
            except GLib.Error:
                pass

    @property
    def exited(self) -> bool:
        return self.subprocess is None or self.subprocess.get_if_exited()


# --------------------------------------------------------------------------- #
# backend facade
# --------------------------------------------------------------------------- #
class Backend:
    def __init__(self) -> None:
        self.repo_root = config.repo_root()
        self.python = find_python(self.repo_root)
        self.config = config.TomlConfig()
        self.config.ensure()
        self._active: set[Proc] = set()

    # -- process factories ---------------------------------------------- #
    def track(self, proc: Proc) -> Proc:
        self._active.add(proc)
        return proc

    def assistant(self, *args: str) -> Proc:
        return self.track(
            Proc([self.python, "-m", "assistant", *args], cwd=str(self.repo_root))
        )

    def systemctl(self, *args: str) -> Proc:
        return self.track(Proc(["systemctl", "--user", *args]))

    def journalctl(self, unit: str, lines: int = 200, follow: bool = True) -> Proc:
        argv = ["journalctl", "--user", "-u", unit, "-n", str(lines), "-o", "short-iso", "--no-pager"]
        if follow:
            argv.insert(4, "-f")
        return self.track(Proc(argv))

    def pw_record(self) -> Proc:
        return self.track(
            Proc(
                ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "-"],
                silence_stderr=True,
            )
        )

    def tts(self, engine: str, voice: str, text: str) -> Optional[Proc]:
        if engine == "espeak-ng":
            argv = ["espeak-ng", "-v", voice or "en", text]
        elif engine == "espeak":
            argv = ["espeak", "-v", voice or "en", text]
        elif engine == "spd-say":
            argv = ["spd-say", "-v", voice or "en", text]
        elif engine == "piper":
            argv = ["piper", "--output-raw", "--model", voice, text]
        else:
            return None
        if not shutil.which(argv[0]):
            return None
        return self.track(Proc(argv))

    # -- helpers --------------------------------------------------------- #
    def assistant_installed(self) -> bool:
        return (self.repo_root / "assistant" / "__main__.py").exists()

    def models_root(self) -> Path:
        override = os.environ.get("UTTER_MODELS")
        if override:
            return Path(override)
        data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        return data_home / "utter" / "models"


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def parse_json(text: str) -> Any:
    """Parse JSON, tolerating a leading log line or two."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            start = text.find("[")
        if start >= 0:
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                return None
    return None


def parse_ndjson_line(line: str) -> Optional[dict]:
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_systemctl_show(text: str) -> dict[str, dict[str, str]]:
    """Parse ``systemctl show`` output for one or more units."""
    units: dict[str, dict[str, str]] = {}
    current: Optional[dict[str, str]] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            current = None
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key == "Id":
            current = units.setdefault(value, {})
        if current is None:
            current = {}
        current[key] = value
    # ``systemctl show a b`` repeats Id only when changing units; ensure every
    # block is keyed.  Fall back to treating an empty result as a failure.
    return units


def parse_pactl_sources(text: str) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name, desc = parts[1], (parts[2] if len(parts) > 2 else parts[1])
        if name.endswith(".monitor"):
            continue
        out.append({"name": name, "description": desc})
    return out


def rms_from_pcm_s16(data: bytes) -> float:
    """Return 0.0–1.0 loudness from little-endian signed 16-bit samples."""
    if len(data) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if not samples:
        return 0.0
    total = 0
    for sample in samples:
        total += sample * sample
    rms = math.sqrt(total / len(samples)) / 32768.0
    # Perceptual curve: quiet speech still moves the meter.
    return min(1.0, rms ** 0.5)
