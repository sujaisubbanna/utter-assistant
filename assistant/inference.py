"""Provision and check the inference lane (vision + planner models).

The vision (UI-TARS) and planner (Qwen3-4B AWQ) checkpoints ship as multi-file
(sharded safetensors) repositories, so the single-file model store cannot pull
them. This module is the **single source of truth** for provisioning them on
Linux, macOS and Windows: it creates a virtualenv, installs the platform's
runtime, and downloads the complete repo directories with
``huggingface_hub.snapshot_download``.

``scripts/install_inference.sh`` is now a thin wrapper that delegates here, so
script users and the settings UI share one implementation. The settings UI calls
this through ``python -m assistant inference install [--json]`` and streams the
NDJSON progress events.

:func:`status` reports whether the two model directories look complete, reusing
the same "config + weights" definition as the provisioner.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import util

#: Where each repo is downloaded by default (repo-relative).
VISION_MODEL_DIRNAME = "UI-TARS-2B-SFT"
PLANNER_MODEL_DIRNAME = "Qwen3-4B-Instruct-2507-AWQ-4bit"

#: Kept for callers that still name the script; it is now a thin wrapper around
#: this module.
PROVISION_SCRIPT = "scripts/install_inference.sh"

#: Serving entrances, by platform.
VISION_SERVE_LINUX = "scripts/serve_vision.sh"
VISION_SERVE_MACOS = "scripts/serve_vision_transformers.py"
VISION_SERVE_WINDOWS = "scripts/serve_vision_transformers.py"
PLANNER_SERVE = "scripts/serve_planner.sh"

#: Default Hugging Face repos.
DEFAULT_VISION_MODEL_ID = "ByteDance-Seed/UI-TARS-2B-SFT"
DEFAULT_PLANNER_MODEL_ID = "cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit"

#: Default interpreter `uv` builds the venv from (mirrors the old script).
DEFAULT_INFERENCE_PYTHON = "3.12"

#: Installed on every platform. `requests` is used by the vision client and
#: `Pillow` downscales screenshots before upload; vLLM/transformers usually bring
#: both, but the contract is made explicit.
COMMON_PACKAGES = ("huggingface_hub[cli]", "requests>=2.31", "Pillow>=10")

#: Windows CPU-only PyTorch wheels live on PyTorch's own index; the default
#: (PyPI) wheels bundle the CUDA runtime.
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


# --------------------------------------------------------------------------- #
# platform plan
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PipStep:
    """One ``pip install`` invocation (packages + an optional index override)."""

    packages: tuple[str, ...]
    index_url: str | None = None


@dataclass(frozen=True)
class PlatformPlan:
    """The runtime packages to install for a host platform."""

    platform: str
    steps: tuple[PipStep, ...]

    @property
    def packages(self) -> tuple[str, ...]:
        """Every package in the plan, flattened (for assertions/UI)."""
        return tuple(pkg for step in self.steps for pkg in step.packages)


def cuda_available() -> bool:
    """True when an NVIDIA GPU (``nvidia-smi``) is present.

    The Windows plan uses this before PyTorch is installed; ``nvidia-smi`` is the
    standard proxy and the same check ``assistant/deps.py`` reports.
    """
    return bool(util.which("nvidia-smi"))


def platform_plan(platform_name: str | None = None, *,
                  cuda: bool | None = None) -> PlatformPlan:
    """Build the pip plan for ``platform_name`` (default: this host).

    * Linux   — vLLM (>=0.10), served by ``scripts/serve_vision.sh``.
    * macOS   — transformers + torch (Metal/MPS) + accelerate; vLLM has no wheel.
    * Windows — torch (CUDA build when an NVIDIA GPU is present, else the CPU
                wheel index) + transformers + accelerate.

    Every platform also gets ``huggingface_hub[cli]``, ``requests`` and ``Pillow``.
    """
    name = platform_name or _platform_name()
    if name == "macos":
        steps: tuple[PipStep, ...] = (
            PipStep(("transformers>=4.45", "accelerate>=1.0", "torch>=2.2")),
        )
    elif name == "windows":
        if cuda is None:
            cuda = cuda_available()
        index = None if cuda else TORCH_CPU_INDEX
        steps = (
            PipStep(("torch",), index),
            PipStep(("transformers>=4.45", "accelerate>=1.0")),
        )
    else:  # linux (and anything unknown defaults to the Linux path)
        steps = (PipStep(("vllm>=0.10",)),)
    return PlatformPlan(platform=name, steps=steps + (PipStep(COMMON_PACKAGES),))


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    """The checkout root (``.../assistant/inference.py`` -> ``...``)."""
    return Path(__file__).resolve().parent.parent


def script_path() -> Path:
    return repo_root() / PROVISION_SCRIPT


def model_paths(root: Path | None = None) -> tuple[Path, Path]:
    """(vision_dir, planner_dir), honouring the ``UTTER_*_MODEL_PATH`` overrides."""
    base = root if root is not None else repo_root()
    vision = os.environ.get("UTTER_VISION_MODEL_PATH") or str(base / "models" / VISION_MODEL_DIRNAME)
    planner = os.environ.get("UTTER_PLANNER_MODEL_PATH") or str(base / "models" / PLANNER_MODEL_DIRNAME)
    return Path(vision), Path(planner)


def model_ids() -> tuple[str, str]:
    """(vision_repo, planner_repo), honouring the ``UTTER_*_MODEL_ID`` overrides."""
    vision = os.environ.get("UTTER_VISION_MODEL_ID") or DEFAULT_VISION_MODEL_ID
    planner = os.environ.get("UTTER_PLANNER_MODEL_ID") or DEFAULT_PLANNER_MODEL_ID
    return vision, planner


def venv_dir(root: Path | None = None) -> Path:
    """The inference virtualenv (``.venv`` by default; ``UTTER_INFERENCE_VENV``)."""
    override = os.environ.get("UTTER_INFERENCE_VENV")
    if override:
        return Path(override)
    return (root if root is not None else repo_root()) / ".venv"


def venv_python(venv: Path, platform_name: str | None = None) -> Path:
    """The venv's interpreter (``Scripts/python.exe`` on Windows, ``bin/python``)."""
    if (platform_name or _platform_name()) == "windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def model_present(path: str | os.PathLike[str]) -> bool:
    """True when ``path`` looks like a complete checkpoint.

    Mirrors the old shell ``model_present``: a ``config.json`` plus at least one
    weight file (single or sharded index).
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


def _platform_name() -> str:
    """Normalised host platform: ``"linux"`` | ``"macos"`` | ``"windows"``."""
    from utter import platform

    if platform.is_windows():
        return "windows"
    if platform.is_macos():
        return "macos"
    return "linux"


def serve_script() -> str:
    """The vision serve script for this platform."""
    if _is_macos() or _is_windows():
        return VISION_SERVE_MACOS
    return VISION_SERVE_LINUX


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
    if _is_macos() or _is_windows():
        lines.append(f"planner serve: {PLANNER_SERVE} (vLLM; not available natively)")
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


def _fail(json_progress: bool, message: str) -> int:
    _emit_error(json_progress, message)
    return 1


def _make_emitter(json_progress: bool):
    def emit(line: str) -> None:
        if json_progress:
            util.ndjson({"event": "progress", "line": line})
        else:
            print(line, flush=True)

    return emit


def _run_streamed(cmd: list[str], emit, *, cwd: Path | None = None) -> int:
    """Run ``cmd``, forwarding each combined stdout/stderr line to ``emit``.

    Returns the child's exit code, or 1 when it could not be started.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        emit(f"[install_inference] could not run {cmd[0]}: {exc}")
        return 1

    stream = proc.stdout
    if stream is not None:
        for raw in stream:
            emit(raw.rstrip("\n"))
    return proc.wait()


def _base_python() -> str | None:
    """The interpreter used for a plain ``python -m venv`` (not for ``uv``)."""
    override = os.environ.get("UTTER_INFERENCE_PYTHON")
    if override:
        return override
    return util.which("python3") or util.which("python")


def _ensure_venv(venv: Path, platform_name: str, emit) -> int:
    """Create ``.venv`` if missing. Returns 0 on success, 1 on failure."""
    interpreter = venv_python(venv, platform_name)
    if interpreter.is_file():
        emit(f"[install_inference] {venv} already exists")
        return 0

    uv = util.which("uv")
    if uv:
        python = os.environ.get("UTTER_INFERENCE_PYTHON") or DEFAULT_INFERENCE_PYTHON
        emit(f"[install_inference] using uv: {uv}")
        emit(f"[install_inference] creating {venv} (uv, python {python})")
        return _run_streamed([uv, "venv", "--python", python, str(venv)], emit)

    base = _base_python()
    if not base:
        emit("[install_inference] error: no python3/python found; "
             "set UTTER_INFERENCE_PYTHON")
        return 1
    emit("[install_inference] uv not found; using python -m venv + pip")
    emit(f"[install_inference] creating {venv} ({base})")
    return _run_streamed([base, "-m", "venv", str(venv)], emit)


def _hf_download(interpreter: Path, repo: str, directory: Path, emit,
                 cwd: Path | None = None) -> int:
    """Download a complete repo directory with the venv's ``huggingface_hub``."""
    directory.mkdir(parents=True, exist_ok=True)
    code = (
        "import sys; from huggingface_hub import snapshot_download; "
        "snapshot_download(sys.argv[1], local_dir=sys.argv[2])"
    )
    return _run_streamed(
        [str(interpreter), "-c", code, repo, str(directory)], emit, cwd=cwd
    )


def _install_planner() -> bool:
    value = (os.environ.get("UTTER_INSTALL_PLANNER_MODEL") or "1").strip().lower()
    return value not in ("0", "no", "false", "off", "skip")


def install(*, json_progress: bool = False) -> int:
    """Provision the inference lane: venv, runtime packages, model repos.

    With ``json_progress`` the output is NDJSON: ``{"event":"start"}``, one
    ``{"event":"progress","line":…}`` per output line, then ``{"event":"done",
    "ok":true}`` or ``{"event":"error","error":…}``. Returns 0 on success, 1 on
    failure. Works on Linux, macOS and Windows — the platform plan is chosen in
    :func:`platform_plan`.
    """
    emit = _make_emitter(json_progress)
    if json_progress:
        util.ndjson({"event": "start"})

    root = repo_root()
    platform_name = _platform_name()
    emit(f"[install_inference] repo={root} platform={platform_name}")

    venv = venv_dir(root)
    if _ensure_venv(venv, platform_name, emit) != 0:
        return _fail(json_progress, "could not create the inference virtualenv")

    interpreter = venv_python(venv, platform_name)
    uv = util.which("uv")
    pip_bootstrapped = False

    def pip_install(packages: tuple[str, ...], index_url: str | None = None) -> int:
        nonlocal pip_bootstrapped
        if uv:
            cmd = [uv, "pip", "install", "--python", str(interpreter), *packages]
        else:
            if not pip_bootstrapped:
                if _run_streamed([str(interpreter), "-m", "pip", "install", "--upgrade", "pip"],
                                 emit, cwd=root) != 0:
                    return 1
                pip_bootstrapped = True
            cmd = [str(interpreter), "-m", "pip", "install", *packages]
        if index_url:
            cmd += ["--index-url", index_url]
        return _run_streamed(cmd, emit, cwd=root)

    plan = platform_plan(platform_name)
    for step in plan.steps:
        where = f" (index {step.index_url})" if step.index_url else ""
        emit(f"[install_inference] installing {', '.join(step.packages)}{where}")
        if pip_install(step.packages, step.index_url) != 0:
            return _fail(json_progress, f"pip install failed: {', '.join(step.packages)}")

    vision_id, planner_id = model_ids()
    vision_dir, planner_dir = model_paths(root)

    emit(f"[install_inference] vision model: {vision_id}")
    if model_present(vision_dir):
        emit(f"[install_inference] vision model already present in {vision_dir}")
    else:
        emit(f"[install_inference] downloading {vision_id} -> {vision_dir}")
        if _hf_download(interpreter, vision_id, vision_dir, emit, root) != 0:
            return _fail(json_progress, f"could not download {vision_id}")

    if not _install_planner():
        emit("[install_inference] skipping the planner model "
             f"(UTTER_INSTALL_PLANNER_MODEL={os.environ.get('UTTER_INSTALL_PLANNER_MODEL')})")
    elif not planner_id:
        emit("[install_inference] no planner model id set; skipping")
    elif model_present(planner_dir):
        emit(f"[install_inference] planner model already present in {planner_dir}")
    else:
        emit(f"[install_inference] planner model: {planner_id}")
        emit(f"[install_inference] downloading {planner_id} -> {planner_dir}")
        if _hf_download(interpreter, planner_id, planner_dir, emit, root) != 0:
            return _fail(json_progress, f"could not download {planner_id}")

    emit("[install_inference] done")
    if platform_name == "macos":
        emit("[install_inference] macOS serves the vision model via "
             "scripts/serve_vision_transformers.py")
    elif platform_name == "windows":
        emit("[install_inference] Windows serves the vision model via "
             "scripts/serve_vision_transformers.py")
    else:
        emit("[install_inference] next: scripts/serve_vision.sh   # http://127.0.0.1:8000/v1 (uitars)")
        emit("[install_inference] next: scripts/serve_planner.sh  # http://127.0.0.1:8001/v1 (qwen3-4b)")

    if json_progress:
        util.ndjson({"event": "done", "ok": True})
    return 0
