"""Agent-facing command line for Utter."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import wave
import sys
from pathlib import Path

SCHEMA = "utter.cli/v1"
EXIT = {"ok": 0, "failed": 1, "usage": 2, "blocked": 3,
        "unavailable": 4, "not_found": 5}


def _out(args, command: str, *, data=None, error=None, code=0) -> int:
    if getattr(args, "json", False):
        value = {"schema": SCHEMA, "ok": code == 0, "command": command}
        if data is not None:
            value["data"] = data
        if error is not None:
            value["error"] = error
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif error:
        print(f"{error['code']}: {error['message']}", file=sys.stderr)
    elif data is not None:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return code


def _err(args, command, code, stable, message):
    return _out(args, command, error={"code": stable, "message": message}, code=code)


def _profiles():
    from .router import profiles
    return profiles.load()


def _tts_engine():
    return shutil.which("espeak-ng") or shutil.which("espeak")


def _stt_config():
    from .config import load_config
    return load_config().stt


def _transcribe_pcm(pcm):
    from .voice.stt import Transcriber
    return Transcriber(_stt_config()).transcribe(pcm)


def _dispatch(args) -> int:
    command = args.command
    if command == "assistant" and not args.dry_run and not args.confirm:
        return _err(args, command, 3, "E_BLOCKED", "Action execution requires --confirm. Use --dry-run to inspect the route first.")
    if command == "listen" and not args.transcribe_only and not args.dry_run and not args.confirm:
        return _err(args, command, 3, "E_BLOCKED", "Acting on a captured utterance requires --confirm.")
    try:
        if command in ("assistant", "dictation"):
            if args.dry_run:
                if command == "assistant":
                    from .daemon import Utter, _setup_logging
                    from .config import load_config
                    app = Utter(load_config(args.config), dry_run=True)
                    logging.disable(logging.CRITICAL)
                    app.setup()
                    ok = app.handle_utterance(args.text)
                    return _out(args, command, data={"accepted": ok, "dry_run": True},
                                error=None if ok else {"code": "E_NO_ACTION", "message": "No action matched."}, code=0 if ok else 1)
                return _out(args, command, data={"typed": False, "dry_run": True,
                             "characters": len(args.text)})
            if command == "dictation":
                from .actions.keyboard import type_text
                result = type_text(args.text)
                ok = bool(result.ok)
                return _out(args, command, data={"typed": ok, "characters": len(args.text)},
                            error=None if ok else {"code": "E_BACKEND_UNAVAILABLE", "message": result.message},
                            code=0 if ok else 4)
            from .daemon import Utter, _setup_logging
            from .config import load_config
            app = Utter(load_config(args.config), dry_run=False)
            _setup_logging(args.log_level or "WARNING")
            app.setup()
            ok = app.handle_utterance(args.text)
            return _out(args, command, data={"accepted": ok},
                        error=None if ok else {"code": "E_NO_ACTION", "message": "No action matched."}, code=0 if ok else 1)
        if command == "capabilities":
            from assistant.deps import probe_deps
            deps = probe_deps()
            try:
                import torch
                gpu = {"available": bool(torch.cuda.is_available()), "name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}
            except Exception:
                gpu = {"available": False, "name": None}
            model_dirs = [Path(os.environ.get("UTTER_MODELS_DIR", "~/.local/share/utter/models")).expanduser(), Path("~/.local/share/vocalinux/models/whispercpp").expanduser(), Path("models")]
            models = sorted({p.name for d in model_dirs if d.is_dir() for p in d.iterdir() if p.is_file()})
            try:
                from assistant.runner_client import RunnerClient
                from assistant.util import runner_sock_path
                client = RunnerClient(runner_sock_path(), timeout=0.4); client.connect(); connected = True; client.close()
            except Exception:
                connected = False
            backends = {k: deps.get(k, False) for k in ("wtype", "ydotool", "ydotoold", "pw_play")}
            backends.update({"keyd": bool(shutil.which("keyd")), "pipewire": bool(shutil.which("pw-cli"))})
            return _out(args, command, data={"backends": backends, "tts": Path(_tts_engine()).name if _tts_engine() else None, "gpu": gpu, "models": models, "runner_connected": connected})
        if command == "schema":
            return _out(args, command, data={"schema": SCHEMA, "commands": COMMANDS, "exit_codes": EXIT, "error_codes": ERROR_CODES})
        if command == "apps":
            entries = [{"id": p.id, "name": p.name, "aliases": p.aliases} for p in _profiles().values()]
            return _out(args, "apps list", data=entries)
        if command == "actions":
            actions = ["launch", "close", "focus", "search", "click", "type", "key", "scroll", "media"]
            if args.app:
                profile = _profiles().get(args.app)
                if profile is None:
                    return _err(args, command, 5, "E_NOT_FOUND", f"Unknown app: {args.app}")
                actions = sorted(set(actions + list(profile.shortcuts)))
            return _out(args, "actions list", data={"app": args.app, "actions": actions})
        if command == "profiles":
            return _out(args, command, data=[{"id": p.id, "name": p.name, "kind": p.kind} for p in _profiles().values()])
        if command == "status":
            from assistant.doctor import build_report
            report = build_report(timeout=args.timeout)
            return _out(args, command, data=report, code=0 if report.get("connected") else 4,
                        error=None if report.get("connected") else {"code": "E_RUNNER_UNAVAILABLE", "message": report.get("error", "Runner is unavailable.")})
        if command == "doctor":
            from assistant.doctor import build_report
            return _out(args, command, data=build_report(timeout=args.timeout))
        if command == "version":
            from . import __version__
            return _out(args, command, data={"version": __version__})
        if command == "speak":
            engine = _tts_engine()
            if not engine:
                return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", "Install espeak-ng or espeak to enable local TTS.")
            if args.dry_run:
                return _out(args, command, data={"spoken": False, "dry_run": True, "engine": Path(engine).name})
            try:
                proc = subprocess.run([engine, args.text], capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.SubprocessError) as exc:
                return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", str(exc))
            ok = proc.returncode == 0
            return _out(args, command, data={"spoken": ok, "engine": Path(engine).name},
                        error=None if ok else {"code": "E_ACTION_FAILED", "message": proc.stderr.strip() or "TTS engine failed."}, code=0 if ok else 1)
        if command == "transcribe":
            try:
                import numpy as np
                with wave.open(args.file, "rb") as source:
                    if source.getcomptype() != "NONE" or source.getframerate() != 16000 or source.getnchannels() not in (1, 2):
                        return _err(args, command, 2, "E_USAGE", "Input must be uncompressed mono/stereo PCM WAV at 16000 Hz.")
                    width, channels = source.getsampwidth(), source.getnchannels()
                    raw = source.readframes(source.getnframes())
                dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
                if dtype is None:
                    return _err(args, command, 2, "E_USAGE", "Unsupported WAV sample width.")
                pcm = np.frombuffer(raw, dtype=dtype)
                if width == 1:
                    pcm = (pcm.astype(np.float32) - 128.0) / 128.0
                else:
                    pcm = pcm.astype(np.float32) / float(2 ** (width * 8 - 1))
                if channels == 2:
                    pcm = pcm.reshape(-1, 2).mean(axis=1)
                transcript = _transcribe_pcm(pcm)
                return _out(args, command, data={"text": transcript})
            except FileNotFoundError:
                return _err(args, command, 5, "E_NOT_FOUND", f"Audio file not found: {args.file}")
            except (ImportError, RuntimeError, OSError, wave.Error, ValueError) as exc:
                return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", str(exc))
        if command == "listen":
            try:
                import numpy as np
                import sounddevice as sd
                from .config import load_config
                cfg = load_config()
                frames = max(1, int(args.timeout * cfg.audio.sample_rate))
                pcm = sd.rec(frames, samplerate=cfg.audio.sample_rate, channels=cfg.audio.channels, dtype="float32", device=cfg.audio.device or None, blocking=True)
                if cfg.audio.sample_rate != 16000:
                    return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", "One-shot STT currently requires a 16000 Hz capture device.")
                pcm = np.asarray(pcm).reshape(-1) if cfg.audio.channels == 1 else np.asarray(pcm).mean(axis=1)
                transcript = _transcribe_pcm(pcm)
                if args.transcribe_only:
                    return _out(args, command, data={"text": transcript})
                from .daemon import Utter
                app = Utter(cfg, dry_run=args.dry_run); app.setup()
                ok = app.handle_utterance(transcript)
                return _out(args, command, data={"text": transcript, "accepted": ok},
                            error=None if ok else {"code": "E_NO_ACTION", "message": "No action matched."}, code=0 if ok else 1)
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", str(exc))
        if command == "listen":
            return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", "One-shot audio capture is unavailable: sounddevice/PipeWire support is not installed.")
    except (OSError, RuntimeError, ImportError, ValueError) as exc:
        return _err(args, command, 4, "E_BACKEND_UNAVAILABLE", str(exc))
    return _err(args, command, 2, "E_USAGE", "Unsupported command.")


COMMANDS = {
    "assistant": {"args": ["text"], "flags": ["--dry-run", "--json", "--confirm", "--non-interactive"]},
    "dictation": {"args": ["text"], "flags": ["--dry-run", "--json", "--non-interactive"]},
    "listen": {"flags": ["--transcribe-only", "--timeout", "--dry-run", "--confirm", "--json"]},
    "speak": {"args": ["text"], "flags": ["--dry-run", "--json", "--non-interactive"]},
    "transcribe": {"flags": ["--file", "--json"]},
    "capabilities": {"flags": ["--json"]}, "schema": {"flags": ["--json"]},
    "apps list": {"flags": ["--json"]}, "actions list": {"flags": ["--app", "--json"]},
    "profiles": {"flags": ["--json"]}, "status": {"flags": ["--json", "--timeout"]},
    "doctor": {"flags": ["--json", "--timeout"]}, "version": {"flags": ["--json"]},
}
ERROR_CODES = {"E_USAGE": 2, "E_ACTION_FAILED": 1, "E_BLOCKED": 3,
               "E_BACKEND_UNAVAILABLE": 4, "E_RUNNER_UNAVAILABLE": 4,
               "E_NOT_FOUND": 5, "E_NO_ACTION": 1}


def build_parser():
    p = argparse.ArgumentParser(prog="utter", description="Local voice-to-desktop assistant")
    p.add_argument("--version", action="version", version="utter")
    p.add_argument("--assistant", dest="legacy_assistant", metavar="TEXT")
    p.add_argument("--dictation", dest="legacy_dictation", metavar="TEXT")
    p.add_argument("--text", dest="legacy_text", help=argparse.SUPPRESS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--bridge", action="store_true")
    p.add_argument("--config")
    p.add_argument("--log-level")
    p.add_argument("--json", action="store_true")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--confirm", action="store_true")
    sub = p.add_subparsers(dest="command")
    for name, help_text in (("assistant", "Run a spoken-style command"), ("dictation", "Type into the focused field"), ("speak", "Speak text")):
        q = sub.add_parser(name, help=help_text); q.add_argument("text"); q.add_argument("--dry-run", action="store_true"); q.add_argument("--json", action="store_true"); q.add_argument("--non-interactive", action="store_true"); q.add_argument("--confirm", action="store_true"); q.add_argument("--config"); q.add_argument("--log-level")
    q = sub.add_parser("listen", help="Capture and act on one utterance"); q.add_argument("--transcribe-only", action="store_true"); q.add_argument("--timeout", type=float, default=10); q.add_argument("--dry-run", action="store_true"); q.add_argument("--confirm", action="store_true"); q.add_argument("--json", action="store_true")
    q = sub.add_parser("transcribe", help="Transcribe an audio file"); q.add_argument("--file", required=True); q.add_argument("--json", action="store_true")
    for name in ("capabilities", "schema", "profiles", "status", "doctor", "version"):
        q = sub.add_parser(name); q.add_argument("--json", action="store_true")
        if name in ("status", "doctor"): q.add_argument("--timeout", type=float, default=5)
    q = sub.add_parser("apps"); ss=q.add_subparsers(dest="subcommand", required=True); z=ss.add_parser("list"); z.add_argument("--json", action="store_true")
    q = sub.add_parser("actions"); ss=q.add_subparsers(dest="subcommand", required=True); z=ss.add_parser("list"); z.add_argument("--app"); z.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command:
        return _dispatch(args)
    if args.legacy_assistant is not None:
        args.command, args.text = "assistant", args.legacy_assistant
        return _dispatch(args)
    if args.legacy_dictation is not None:
        args.command, args.text = "dictation", args.legacy_dictation
        return _dispatch(args)
    if args.legacy_text is not None:
        from .daemon import main as daemon_main
        return daemon_main(["--text", args.legacy_text] + (["--dry-run"] if args.dry_run else []) + (["--bridge"] if args.bridge else []) + (["--config", args.config] if args.config else []))
    from .daemon import main as daemon_main
    return daemon_main((["--bridge"] if args.bridge else []) + (["--config", args.config] if args.config else []) + (["--log-level", args.log_level] if args.log_level else []))


if __name__ == "__main__":
    raise SystemExit(main())
