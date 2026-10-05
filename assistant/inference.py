"""Provision and check the inference lane (vision + planner models).

The vision (UI-TARS) and planner (Qwen3-4B AWQ) checkpoints ship as multi-file
(sharded safetensors) repositories, so the single-file model store cannot pull
them. ``scripts/install_inference.sh`` downloads the complete repo directories
instead. This module is the programmatic front door for that script so the
settings UI can run it and stream progress as NDJSON.

:func:`status` reports whether the two model directories look complete, reusing
the same "config + weights" definition as the shell provisioner.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import util

#: Where ``install_inference.sh`` downloads each repo by default (repo-relative).
VISION_MODEL_DIRNAME = "UI-TARS-2B-SFT"
PLANNER_MODEL_DIRNAME = "Qwen3-4B-Instruct-2507-AWQ-4bit"

#: The script the settings UI / CLI runs to provision the stack.
PROVISION_SCRIPT = "scripts/install_inference.sh"

#: Serving entrances, by platform.
VISION_SERVE_LINUX = "scripts/serve_vision.sh"
VISION_SERVE_MACOS = "scripts/serve_vision_transformers.py"
PLANNER_SERVE = "scripts/serve_planner.sh"

WINDOWS_MESSAGE = "inference install is not supported on Windows yet"


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    """The checkout root (``.../assistant/inference.py`` -> ``...``)."""
    return Path(__file__).resolve().parent.parent


def script_path() -> Path:
    return repo_root() / PROVISION_SCRIPT


def model_paths(root: Path | None = None) -> tuple[Path, Path]:
    """(vision_dir, planner_dir), honouring the same overrides as the script."""
    base = root if root is not None else repo_root()
    vision = os.environ.get("UTTER_VISION_MODEL_PATH") or str(base / "models" / VISION_MODEL_DIRNAME)
    planner = os.environ.get("UTTER_PLANNER_MODEL_PATH") or str(base / "models" / PLANNER_MODEL_DIRNAME)
    return Path(vision), Path(planner)


def model_present(path: str | os.PathLike[str]) -> bool:
    """True when ``path`` looks like a complete checkpoint.

    Mirrors ``model_present`` in ``scripts/install_inference.sh``: a
    ``config.json`` plus at least one weight file (single or sharded index).
    """
    directory = Path(path)
    if not (directory.is_dir() and (directory / "config.json").is_file()):
        return False
    if any(directory.glob("*.safetensors")):
        return True
    return (directory / "model.safetensors.index.json").is_file()


# --------------------------------------------------------------------------- #
# platform
# --------------------------------------------------------------------------- #
def _is_windows() -> bool:
    from utter import platform

    return platform.is_windows()


def _is_macos() -> bool:
    from utter import platform

    return platform.is_macos()


def serve_script() -> str:
    """The vision serve script for this platform."""
    return VISION_SERVE_MACOS if _is_macos() else VISION_SERVE_LINUX


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def status() -> dict:
    """Whether the vision and planner model dirs look complete.

    JSON shape: ``{"vision": bool, "planner": bool, "vision_path": str,
    "planner_path": str}``.
    """
    vision, planner = model_paths()
    return {
        "vision": model_present(vision),
        "planner": model_present(planner),
        "vision_path": str(vision),
        "planner_path": str(planner),
    }


def human(data: dict) -> str:
    lines = [
        f"vision:  {'present' if data['vision'] else 'missing'}  ({data['vision_path']})",
        f"planner: {'present' if data['planner'] else 'missing'}  ({data['planner_path']})",
        f"vision serve:  {serve_script()}",
    ]
    if _is_macos():
        lines.append(f"planner serve: {PLANNER_SERVE} (vLLM; not available on macOS)")
    else:
        lines.append(f"planner serve: {PLANNER_SERVE}")
    if not (data["vision"] and data["planner"]):
        lines.append("hint: run `python -m assistant inference install` to download the missing models")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# install (streaming)
# --------------------------------------------------------------------------- #
def _emit_error(json_progress: bool, message: str) -> None:
    if json_progress:
        util.ndjson({"event": "error", "error": message})
    else:
        util.eprint(message)


def install(*, json_progress: bool = False) -> int:
    """Run ``scripts/install_inference.sh``, streaming its output.

    With ``json_progress`` the output is NDJSON: ``{"event":"start"}``, one
    ``{"event":"progress","line":…}`` per output line, then ``{"event":"done",
    "ok":true}`` or ``{"event":"error","error":…}``. Returns 0 on success, 1 on
    failure (including Windows, which is unsupported).
    """
    if json_progress:
        util.ndjson({"event": "start"})

    if _is_windows():
        _emit_error(json_progress, WINDOWS_MESSAGE)
        return 1

    script = script_path()
    if not script.is_file():
        _emit_error(json_progress, f"provisioner not found: {script}")
        return 1

    bash = util.which("bash") or "bash"
    try:
        proc = subprocess.Popen(
            [bash, str(script)],
            cwd=str(repo_root()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        _emit_error(json_progress, f"could not start {script.name}: {exc}")
        return 1

    stream = proc.stdout
    if stream is not None:
        for raw in stream:
            line = raw.rstrip("\n")
            if json_progress:
                util.ndjson({"event": "progress", "line": line})
            else:
                print(line, flush=True)

    rc = proc.wait()
    if rc == 0:
        if json_progress:
            util.ndjson({"event": "done", "ok": True})
        return 0
    _emit_error(json_progress, f"install_inference.sh exited {rc}")
    return 1
