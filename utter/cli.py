"""Agent-facing command line for Utter."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import wave
import sys
import re
import tempfile
import tomllib
from pathlib import Path

SCHEMA = "utter.cli/v1"
EXIT = {"ok": 0, "failed": 1, "usage": 2, "blocked": 3,
        "unavailable": 4, "not_found": 5}


class CLIUsageError(Exception):
    pass


class CLIArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIUsageError(message)


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


def _gpu_info():
    """Report physical GPU presence independently from torch availability."""
    from utter import platform
    if platform.is_macos():
        from utter.runtime import probe_macos_gpu
        return probe_macos_gpu()
    for tool, runtime in (("nvidia-smi", "cuda"), ("rocm-smi", "rocm")):
        path = shutil.which(tool)
        if path:
            try:
                if runtime == "cuda":
                    proc = subprocess.run([path, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=2)
                    name = next((line.strip() for line in proc.stdout.splitlines() if line.strip()), "NVIDIA GPU")
                else:
                    proc = subprocess.run([path, "--showproductname"], capture_output=True, text=True, timeout=2)
                    name = next((line.strip() for line in proc.stdout.splitlines() if "product" in line.casefold()), "AMD GPU")
                if proc.returncode == 0:
                    return {"available": True, "name": name, "runtime": runtime}
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        import torch
        if torch.cuda.is_available():
            runtime = "rocm" if getattr(torch.version, "hip", None) else "cuda"
            return {"available": True, "name": torch.cuda.get_device_name(0), "runtime": runtime}
    except Exception:
        pass
    # DRM vendor ids tell us a GPU is physically enumerated even if its compute
    # runtime is not installed or initialized.
    for device in Path("/sys/class/drm").glob("card[0-9]*/device"):
        try:
            vendor = (device / "vendor").read_text(encoding="ascii").strip().lower()
        except OSError:
            continue
        if vendor in ("0x10de", "0x1002", "0x8086"):
            label = {"0x10de": "NVIDIA GPU", "0x1002": "AMD GPU", "0x8086": "Intel GPU"}[vendor]
            for filename in ("product_name", "product"):
                try:
                    label = (device / filename).read_text(encoding="utf-8").strip() or label
                    break
                except OSError:
                    pass
            return {"available": True, "name": label, "runtime": "unknown"}
    return {"available": False, "name": None, "runtime": "unknown"}


def _config_path(args):
    if getattr(args, "config", None):
        return Path(args.config).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "utter" / "config.toml"


def _public_path(path: Path) -> str:
    try:
        return "~/" + path.expanduser().resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return str(path)


def _config_data(path):
    from dataclasses import asdict
    from .config import load_config
    cfg = load_config(path if path.exists() else None)
    return asdict(cfg)


def _setting_spec(key):
    """Resolve a dotted public config key and its expected type/default."""
    parts = key.split(".")
    if parts == ["log_level"] or parts == ["daemon", "log_level"]:
        return "daemon", "log_level", str, "INFO"
    if len(parts) == 3 and parts[0] == "macos" and parts[1] == "runtime":
        from .config import MacosRuntimeConfig
        from dataclasses import fields
        field_name = parts[2]
        field = next((f for f in fields(MacosRuntimeConfig) if f.name == field_name), None)
        if field is None:
            return None
        default = getattr(MacosRuntimeConfig(), field_name)
        return "macos.runtime", field_name, type(default), default
    if len(parts) != 2:
        return None
    from .config import Config
    from dataclasses import fields
    section, field_name = parts
    if section not in {f.name for f in fields(Config)}:
        return None
    instance = getattr(Config(), section)
    field = next((f for f in fields(instance) if f.name == field_name), None)
    if field is None:
        return None
    default = getattr(instance, field_name)
    return section, field_name, type(default), default


def _toml_value(value):
    if value is None or isinstance(value, (dict, tuple)):
        raise ValueError("settings values must be TOML scalar values or arrays")
    if isinstance(value, list) and any(not isinstance(v, (str, int, float, bool)) or v is None for v in value):
        raise ValueError("settings arrays may contain only strings, numbers, or booleans")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _write_setting(path: Path, section: str, key: str, value):
    """Edit one TOML assignment while preserving other content/comments."""
    rendered = _toml_value(value)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        shipped_defaults = Path(__file__).resolve().parent.parent / "config.default.toml"
        text = shipped_defaults.read_text(encoding="utf-8") if shipped_defaults.exists() else ""
    # Validate the existing document before attempting a line-preserving edit.
    if text:
        tomllib.loads(text)
    lines = text.splitlines()
    current = ""
    section_start = None
    section_end = len(lines)
    assignment = None
    for index, line in enumerate(lines):
        match = re.match(r"^\s*\[([^]]+)\]\s*(?:#.*)?$", line)
        if match:
            if current == section and section_end == len(lines):
                section_end = index
            current = match.group(1)
            if current == section:
                section_start = index
        elif current == section and re.match(rf"^\s*{re.escape(key)}\s*=", line):
            assignment = index
    if assignment is not None:
        lines[assignment] = f"{key} = {rendered}"
    elif section_start is not None:
        lines.insert(section_end, f"{key} = {rendered}")
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", f"{key} = {rendered}"])
    updated = "\n".join(lines) + "\n"
    tomllib.loads(updated)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _profile_override_path(app_id):
    from .router.profiles import USER_PROFILES_DIR
    if not app_id or len(app_id) > 120 or "/" in app_id or app_id.startswith(".") or any(ord(c) < 32 for c in app_id):
        raise ValueError("invalid app profile id")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", app_id)
    return USER_PROFILES_DIR / f"{safe}.yaml"


def _save_voice_command(app_id, phrase, chord, *, remove=False):
    import yaml
    phrase = re.sub(r"\s+", " ", (phrase or "").strip().lower()).rstrip(".!?,")
    if not phrase or len(phrase) > 100 or any(ord(c) < 32 for c in phrase):
        raise ValueError("phrase must contain 1 to 100 printable characters")
    path = _profile_override_path(app_id)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw if isinstance(raw, dict) else {}
    raw.setdefault("id", app_id)
    commands = raw.get("commands") or {}
    if not isinstance(commands, dict):
        raise ValueError("profile commands must be a mapping")
    if remove:
        commands.pop(phrase, None)
    else:
        if not re.fullmatch(r"[A-Za-z0-9_+\-]{1,40}", chord or ""):
            raise ValueError("key chord may contain letters, digits, underscore, plus, or hyphen (max 40 characters)")
        commands[phrase] = chord
    if commands:
        raw["commands"] = commands
    else:
        raw.pop("commands", None)
    return path, raw


def _err(args, command, code, stable, message):
    return _out(args, command, error={"code": stable, "message": message}, code=code)


def _cmd_assistant(args) -> int:
    command = args.command
    if command == "assistant" and not args.dry_run and not args.confirm:
        return _err(args, command, 3, "E_BLOCKED", "Action execution requires --confirm. Use --dry-run to inspect the route first.")
    if args.dry_run:
        if command == "assistant":
            child_args = [sys.executable, "-m", "utter.daemon", "--text", args.text,
                          "--dry-run", "--json-plan", "--log-level", "CRITICAL"]
            if args.config:
                child_args.extend(["--config", args.config])
            try:
                proc = subprocess.run(child_args, capture_output=True, text=True,
                                      timeout=4.0, check=False)
            except subprocess.TimeoutExpired:
                return _err(args, command, 4, "E_PREVIEW_TIMEOUT",
                            "Dry-run routing exceeded its 4 second limit.")
            if proc.stderr:
                sys.stderr.write(proc.stderr)
            try:
                preview = json.loads(proc.stdout)
            except json.JSONDecodeError:
                return _err(args, command, 4, "E_BACKEND_UNAVAILABLE",
                            "The route preview process returned invalid JSON.")
            ok = bool(preview.get("accepted"))
            return _out(args, command, data={"accepted": ok, "dry_run": True,
                         "plan": preview.get("plan")},
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


def _cmd_capabilities(args) -> int:
    command = args.command
    from assistant.deps import probe_deps
    from utter import platform, runtime
    deps = probe_deps()
    gpu = _gpu_info()
    model_dirs = [Path(os.environ.get("UTTER_MODELS_DIR", "~/.local/share/utter/models")).expanduser(), Path("~/.local/share/vocalinux/models/whispercpp").expanduser(), Path("models")]
    models = sorted({p.name for d in model_dirs if d.is_dir() for p in d.iterdir() if p.is_file() and not p.name.startswith(".")})
    try:
        from assistant.runner_client import RunnerClient
        from assistant.util import runner_sock_path
        client = RunnerClient(runner_sock_path(), timeout=0.4); client.connect(); connected = True; client.close()
    except Exception:
        connected = False
    rt_info = runtime.probe_runtime()
    if platform.is_macos():
        backends = {
            "quartz": bool(platform.has_module("Quartz") or shutil.which("osascript")),
            "apple_speech": bool(platform.has_module("Speech")),
            "whisper_cpp": bool(platform.has_module("pywhispercpp") or shutil.which("whisper-cli")),
            "vocamac": bool(shutil.which("VocaMac") or Path("/Applications/VocaMac.app").exists()),
            "say": bool(shutil.which("say")),
            "screencapture": bool(shutil.which("screencapture")),
        }
        tts_name = "say" if shutil.which("say") else None
        ollama_models = rt_info.get("llm", {}).get("models", [])
        all_models = sorted(set(models + ollama_models))
        return _out(args, command, data={"backends": backends, "tts": tts_name, "gpu": gpu, "models": all_models, "runner_connected": connected, "runtime": rt_info})
    backends = {k: deps.get(k, False) for k in ("wtype", "ydotool", "ydotoold", "pw_play")}
    backends.update({"keyd": bool(shutil.which("keyd")), "pipewire": bool(shutil.which("pw-cli"))})
    return _out(args, command, data={"backends": backends, "tts": Path(_tts_engine()).name if _tts_engine() else None, "gpu": gpu, "models": models, "runner_connected": connected, "runtime": rt_info})


def _cmd_schema(args) -> int:
    command = args.command
    schema_path = Path(__file__).resolve().parent / "data" / "cli.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    return _out(args, command, data={"schema": SCHEMA, "commands": COMMANDS, "exit_codes": EXIT, "error_codes": ERROR_CODES, "json_schema": schema_doc})


def _cmd_settings(args) -> int:
    path = _config_path(args)
    if args.subcommand == "list":
        return _out(args, "settings list", data={"path": _public_path(path), "settings": _config_data(path)})
    if args.subcommand == "get":
        spec = _setting_spec(args.key)
        if not spec:
            return _err(args, "settings get", 5, "E_NOT_FOUND", f"Unknown setting: {args.key}")
        data = _config_data(path)
        section, key, _, default = spec
        current = data.get("log_level", default) if section == "daemon" else data[section][key]
        return _out(args, "settings get", data={"key": args.key, "value": current, "path": _public_path(path)})
    spec = _setting_spec(args.key)
    if not spec:
        return _err(args, "settings set", 5, "E_NOT_FOUND", f"Unknown setting: {args.key}")
    section, key, expected, default_value = spec
    try:
        value = json.loads(args.value)
        if type(value) is not expected and not (expected is float and type(value) is int):
            raise ValueError(f"expected a JSON {expected.__name__} for {args.key}")
        if expected is list and any(type(item) is not type(default_value[0] if default_value else "") for item in value):
            raise ValueError(f"array items for {args.key} must be {type(default_value[0] if default_value else '').__name__} values")
        if key == "sample_rate" and not 8000 <= value <= 192000:
            raise ValueError("audio.sample_rate must be between 8000 and 192000")
        if key == "channels" and value not in (1, 2):
            raise ValueError("audio.channels must be 1 or 2")
        if key == "decide_threshold" and not 0 <= value <= 1:
            raise ValueError("router.decide_threshold must be between 0 and 1")
        rendered_section = "daemon" if section == "daemon" else section
        if args.dry_run:
            return _out(args, "settings set", data={"key": args.key, "value": value, "written": False, "path": _public_path(path)})
        if not args.confirm:
            return _err(args, "settings set", 3, "E_BLOCKED", "Writing settings requires --confirm; use --dry-run to preview.")
        _write_setting(path, rendered_section, key, value)
        return _out(args, "settings set", data={"key": args.key, "value": value, "written": True, "path": _public_path(path)})
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        return _err(args, "settings set", 2, "E_INVALID_SETTING", str(exc))


def _cmd_commands(args) -> int:
    from .router.profiles import load as load_profiles
    action = args.subcommand
    if action == "list":
        profiles = load_profiles()
        if args.app:
            profile = profiles.get(args.app)
            if profile is None:
                return _err(args, "commands list", 5, "E_NOT_FOUND", f"Unknown app: {args.app}")
            entries = ([{"app": args.app, "phrase": phrase, "chord": chord, "kind": "custom"} for phrase, chord in sorted(profile.commands.items())]
                       + [{"app": args.app, "phrase": name, "chord": chord, "kind": "shortcut"} for name, chord in sorted(profile.shortcuts.items())])
        else:
            entries = ([{"app": profile.id, "phrase": phrase, "chord": chord, "kind": "custom"} for profile in profiles.values() for phrase, chord in sorted(profile.commands.items())]
                       + [{"app": profile.id, "phrase": name, "chord": chord, "kind": "shortcut"} for profile in profiles.values() for name, chord in sorted(profile.shortcuts.items())])
        return _out(args, "commands list", data=entries)
    remove = action == "remove"
    try:
        if args.app not in load_profiles():
            return _err(args, f"commands {action}", 5, "E_NOT_FOUND", f"Unknown app: {args.app}")
        path, raw = _save_voice_command(args.app, args.phrase, getattr(args, "chord", ""), remove=remove)
        if args.dry_run:
            return _out(args, f"commands {action}", data={"app": args.app, "phrase": args.phrase, "chord": raw.get("commands", {}).get(re.sub(r"\s+", " ", args.phrase.strip().lower()).rstrip(".!?,")), "written": False, "path": _public_path(path)})
        if not args.confirm:
            return _err(args, f"commands {action}", 3, "E_BLOCKED", "Writing command shortcuts requires --confirm; use --dry-run to preview.")
        import yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".profile-", suffix=".yaml", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                yaml.safe_dump(raw, stream, sort_keys=False, allow_unicode=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except BaseException:
            try: os.unlink(temp_path)
            except OSError: pass
            raise
        return _out(args, f"commands {action}", data={"app": args.app, "phrase": args.phrase, "chord": raw.get("commands", {}).get(re.sub(r"\s+", " ", args.phrase.strip().lower()).rstrip(".!?,")), "written": True, "path": _public_path(path)})
    except (ValueError, OSError) as exc:
        return _err(args, f"commands {action}", 2, "E_INVALID_COMMAND", str(exc))


def _cmd_apps(args) -> int:
    entries = [{"id": p.id, "name": p.name, "aliases": p.aliases} for p in _profiles().values()]
    return _out(args, "apps list", data=entries)


def _cmd_actions(args) -> int:
    actions = ["launch", "close", "focus", "search", "click", "type", "key", "scroll", "media"]
    if args.app:
        profile = _profiles().get(args.app)
        if profile is None:
            return _err(args, "actions list", 5, "E_NOT_FOUND", f"Unknown app: {args.app}")
        actions = sorted(set(actions + list(profile.shortcuts)))
    return _out(args, "actions list", data={"app": args.app, "actions": actions})


def _cmd_profiles(args) -> int:
    return _out(args, "profiles", data=[{"id": p.id, "name": p.name, "kind": p.kind} for p in _profiles().values()])


def _cmd_status(args) -> int:
    from assistant.doctor import build_report
    report = build_report(timeout=args.timeout)
    return _out(args, "status", data=report, code=0 if report.get("connected") else 4,
                error=None if report.get("connected") else {"code": "E_RUNNER_UNAVAILABLE", "message": report.get("error", "Runner is unavailable.")})


def _cmd_doctor(args) -> int:
    from assistant.doctor import build_report
    return _out(args, "doctor", data=build_report(timeout=args.timeout))


def _cmd_version(args) -> int:
    from . import __version__
    return _out(args, "version", data={"version": __version__})


def _cmd_speak(args) -> int:
    command = args.command
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


def _cmd_transcribe(args) -> int:
    command = args.command
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


def _cmd_listen(args) -> int:
    command = args.command
    if not args.transcribe_only and not args.dry_run and not args.confirm:
        return _err(args, command, 3, "E_BLOCKED", "Acting on a captured utterance requires --confirm.")
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


_COMMAND_HANDLERS = {
    "assistant": _cmd_assistant,
    "dictation": _cmd_assistant,
    "capabilities": _cmd_capabilities,
    "schema": _cmd_schema,
    "settings": _cmd_settings,
    "commands": _cmd_commands,
    "apps": _cmd_apps,
    "actions": _cmd_actions,
    "profiles": _cmd_profiles,
    "status": _cmd_status,
    "doctor": _cmd_doctor,
    "version": _cmd_version,
    "speak": _cmd_speak,
    "transcribe": _cmd_transcribe,
    "listen": _cmd_listen,
}


def _dispatch(args) -> int:
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler is None:
        return _err(args, args.command, 2, "E_USAGE", "Unsupported command.")
    try:
        return handler(args)
    except (OSError, RuntimeError, ImportError, ValueError) as exc:
        return _err(args, args.command, 4, "E_BACKEND_UNAVAILABLE", str(exc))


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
    "settings list": {"flags": ["--json", "--config"]},
    "settings get": {"args": ["key"], "flags": ["--json", "--config"]},
    "settings set": {"args": ["key"], "flags": ["--value", "--dry-run", "--confirm", "--json", "--config"]},
    "commands list": {"flags": ["--app", "--json"]},
    "commands set": {"args": ["app", "phrase", "chord"], "flags": ["--dry-run", "--confirm", "--json"]},
    "commands remove": {"args": ["app", "phrase"], "flags": ["--dry-run", "--confirm", "--json"]},
}
ERROR_CODES = {"E_USAGE": 2, "E_ACTION_FAILED": 1, "E_BLOCKED": 3,
               "E_BACKEND_UNAVAILABLE": 4, "E_RUNNER_UNAVAILABLE": 4,
               "E_NOT_FOUND": 5, "E_NO_ACTION": 1,
               "E_INVALID_SETTING": 2, "E_INVALID_COMMAND": 2,
               "E_PREVIEW_TIMEOUT": 4}


def build_parser():
    shared = CLIArgumentParser(add_help=False)
    shared.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    shared.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    shared.add_argument("--confirm", action="store_true", default=argparse.SUPPRESS)
    shared.add_argument("--non-interactive", action="store_true", default=argparse.SUPPRESS)
    shared.add_argument("--config", default=argparse.SUPPRESS)
    shared.add_argument("--log-level", default=argparse.SUPPRESS)
    p = CLIArgumentParser(prog="utter", description="Local voice-to-desktop assistant", parents=[shared])
    p.add_argument("--version", action="version", version="utter")
    p.add_argument("--assistant", dest="legacy_assistant", metavar="TEXT")
    p.add_argument("--dictation", dest="legacy_dictation", metavar="TEXT")
    p.add_argument("--text", dest="legacy_text", help=argparse.SUPPRESS)
    p.add_argument("--bridge", action="store_true")
    sub = p.add_subparsers(dest="command")
    for name, help_text in (("assistant", "Run a spoken-style command"), ("dictation", "Type into the focused field"), ("speak", "Speak text")):
        q = sub.add_parser(name, help=help_text, parents=[shared]); q.add_argument("text")
    q = sub.add_parser("listen", help="Capture and act on one utterance", parents=[shared]); q.add_argument("--transcribe-only", action="store_true"); q.add_argument("--timeout", type=float, default=10)
    q = sub.add_parser("transcribe", help="Transcribe an audio file", parents=[shared]); q.add_argument("--file", required=True)
    for name in ("capabilities", "schema", "profiles", "status", "doctor", "version"):
        q = sub.add_parser(name, parents=[shared])
        if name in ("status", "doctor"): q.add_argument("--timeout", type=float, default=5)
    q = sub.add_parser("apps", parents=[shared]); ss=q.add_subparsers(dest="subcommand", required=True); ss.add_parser("list", parents=[shared])
    q = sub.add_parser("actions", parents=[shared]); ss=q.add_subparsers(dest="subcommand", required=True); z=ss.add_parser("list", parents=[shared]); z.add_argument("--app")
    q = sub.add_parser("settings", parents=[shared]); ss=q.add_subparsers(dest="subcommand", required=True)
    ss.add_parser("list", parents=[shared])
    z=ss.add_parser("get", parents=[shared]); z.add_argument("key")
    z=ss.add_parser("set", parents=[shared]); z.add_argument("key"); z.add_argument("--value", required=True, help="JSON value")
    q = sub.add_parser("commands", parents=[shared]); ss=q.add_subparsers(dest="subcommand", required=True)
    z=ss.add_parser("list", parents=[shared]); z.add_argument("--app")
    z=ss.add_parser("set", parents=[shared]); z.add_argument("app"); z.add_argument("phrase"); z.add_argument("chord")
    z=ss.add_parser("remove", parents=[shared]); z.add_argument("app"); z.add_argument("phrase")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CLIUsageError as exc:
        if "--json" in argv:
            print(json.dumps({"schema": SCHEMA, "ok": False, "command": "usage",
                              "error": {"code": "E_USAGE", "message": str(exc)}}, indent=2))
        else:
            print(f"utter: {exc}", file=sys.stderr)
        return 2
    for key, default in (("dry_run", False), ("json", False), ("confirm", False),
                         ("non_interactive", False), ("config", None), ("log_level", None)):
        vars(args).setdefault(key, default)
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
