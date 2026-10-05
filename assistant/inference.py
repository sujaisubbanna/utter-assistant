"""Provision and check the inference lane (vision + planner models).

The vision (UI-TARS) checkpoint ships as a multi-file (sharded safetensors)
repository, so the single-file model store cannot pull it. This module is the
**single source of truth** for provisioning it on Linux, macOS and Windows: it
creates a virtualenv, installs the platform's runtime, and downloads the
complete repo directory with ``huggingface_hub.snapshot_download``.

The **planner** is per-platform:

* Linux serves Qwen3-4B-Instruct-2507-AWQ-4bit with vLLM;
* macOS and Windows serve the ``unsloth/Qwen3-4B-Instruct-2507-GGUF``
  Q4_K_M checkpoint with llama.cpp's ``llama-server`` (the binary is fetched
  from the llama.cpp GitHub release and pinned in ``build.json``).

``scripts/install_inference.sh`` is now a thin wrapper that delegates here, so
script users and the settings UI share one implementation. The settings UI calls
this through ``python -m assistant inference install [--json]`` and streams the
NDJSON progress events.

:func:`status` reports whether the two model directories look complete (reusing
the same "config + weights" definition as the provisioner) and which planner
backend this host uses. :func:`check` probes a running planner endpoint.
"""
from __future__ import annotations

import json
import os
import platform as _platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import models, util

#: Where each repo is downloaded by default (repo-relative).
VISION_MODEL_DIRNAME = "UI-TARS-2B-SFT"
PLANNER_MODEL_DIRNAME = "Qwen3-4B-Instruct-2507-AWQ-4bit"
LLAMACPP_GGUF_DIRNAME = "Qwen3-4B-Instruct-2507-GGUF"

#: Kept for callers that still name the script; it is now a thin wrapper around
#: this module.
PROVISION_SCRIPT = "scripts/install_inference.sh"

#: Serving entrances, by platform.
VISION_SERVE_LINUX = "scripts/serve_vision.sh"
VISION_SERVE_MACOS = "scripts/serve_vision_transformers.py"
VISION_SERVE_WINDOWS = "scripts/serve_vision_transformers.py"
PLANNER_SERVE = "scripts/serve_planner.sh"
PLANNER_SERVE_LLAMACPP = "scripts/serve_planner_llamacpp.sh"

#: Default Hugging Face repos.
DEFAULT_VISION_MODEL_ID = "ByteDance-Seed/UI-TARS-2B-SFT"
DEFAULT_PLANNER_MODEL_ID = "cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit"
LLAMACPP_PLANNER_MODEL_ID = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
LLAMACPP_GGUF_FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
LLAMACPP_GGUF_QUANT = "Q4_K_M"

#: Planner backend strings reported by ``status --json``.
VLLM_BACKEND = "vllm"
LLAMACPP_BACKEND = "llamacpp"

#: llama.cpp release assets. ``releases/latest/download/nightly-tag.txt`` holds
#: the current build tag (e.g. ``b11146``); assets hang off
#: ``releases/download/<tag>/<asset>``.
LLAMACPP_NIGHTLY_TAG_URL = (
    "https://github.com/ggml-org/llama.cpp/releases/latest/download/nightly-tag.txt"
)
LLAMACPP_RELEASE_BASE = "https://github.com/ggml-org/llama.cpp/releases/download"

#: The static part of the serve command (port/alias/ctx are added per launch).
#: ``--reasoning off`` is mandatory: Qwen3-4B-Instruct-2507 is frequently
#: misdetected as a thinking model and would otherwise emit reasoning tokens.
LLAMACPP_STATIC_FLAGS = (
    "--host", "127.0.0.1",
    "-ngl", "auto",
    "-fa", "auto",
    "--jinja",
    "--reasoning", "off",
    "-np", "1",
    "--no-webui",
)

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
    planner_backend: str = VLLM_BACKEND

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

    * Linux   — vLLM (>=0.10) for the AWQ planner, served by
                ``scripts/serve_planner.sh``.
    * macOS   — transformers + torch (Metal/MPS) + accelerate for vision; the
                planner runs on llama.cpp (GGUF), so no vLLM wheel is needed.
    * Windows — torch (CUDA build when an NVIDIA GPU is present, else the CPU
                wheel index) + transformers + accelerate for vision; the planner
                runs on llama.cpp (GGUF).

    Every platform also gets ``huggingface_hub[cli]``, ``requests`` and ``Pillow``.
    The planner backend is reported separately in :attr:`PlatformPlan.planner_backend`.
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
    return PlatformPlan(platform=name, steps=steps + (PipStep(COMMON_PACKAGES),),
                        planner_backend=planner_backend(name))


def planner_backend(platform_name: str | None = None) -> str:
    """``"vllm"`` on Linux, ``"llamacpp"`` on macOS/Windows."""
    name = platform_name or _platform_name()
    return LLAMACPP_BACKEND if name in ("macos", "windows") else VLLM_BACKEND


def serve_planner_script(platform_name: str | None = None) -> str:
    """The planner serve script for this backend."""
    if planner_backend(platform_name) == LLAMACPP_BACKEND:
        return PLANNER_SERVE_LLAMACPP
    return PLANNER_SERVE


def planner_model_id(platform_name: str | None = None) -> str:
    """The planner HF repo: AWQ on Linux, GGUF on macOS/Windows.

    ``UTTER_PLANNER_MODEL_ID`` overrides either default.
    """
    override = os.environ.get("UTTER_PLANNER_MODEL_ID")
    if override:
        return override
    if planner_backend(platform_name) == LLAMACPP_BACKEND:
        return LLAMACPP_PLANNER_MODEL_ID
    return DEFAULT_PLANNER_MODEL_ID


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


def model_ids(platform_name: str | None = None) -> tuple[str, str]:
    """(vision_repo, planner_repo) for this host's planner backend.

    The planner repo is AWQ on Linux and GGUF on macOS/Windows (see
    :func:`planner_model_id`); both honour the ``UTTER_*_MODEL_ID`` overrides.
    """
    vision = os.environ.get("UTTER_VISION_MODEL_ID") or DEFAULT_VISION_MODEL_ID
    return vision, planner_model_id(platform_name)


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
# llama.cpp (macOS / Windows planner)
# --------------------------------------------------------------------------- #
def planner_gguf_path(root: Path | None = None) -> Path:
    """The planner GGUF file.

    ``UTTER_PLANNER_MODEL_PATH`` may point at the ``.gguf`` file directly or at
    its directory; otherwise the default is
    ``models/Qwen3-4B-Instruct-2507-GGUF/<file>``.
    """
    override = os.environ.get("UTTER_PLANNER_MODEL_PATH")
    if override:
        path = Path(override)
        if path.suffix.lower() == ".gguf":
            return path
        return path / LLAMACPP_GGUF_FILE
    base = root if root is not None else repo_root()
    return base / "models" / LLAMACPP_GGUF_DIRNAME / LLAMACPP_GGUF_FILE


def planner_path(platform_name: str | None = None, root: Path | None = None) -> Path:
    """The planner payload path: a GGUF file on llama.cpp, a dir on vLLM."""
    if planner_backend(platform_name) == LLAMACPP_BACKEND:
        return planner_gguf_path(root)
    return model_paths(root)[1]


def llamacpp_dir(root: Path | None = None) -> Path:
    """Where the extracted ``llama-server`` build lives (``UTTER_LLAMACPP_DIR``)."""
    override = os.environ.get("UTTER_LLAMACPP_DIR")
    if override:
        return Path(override)
    base = root if root is not None else repo_root()
    return base / "models" / "llama.cpp"


def llamacpp_server_path(root: Path | None = None, platform_name: str | None = None) -> Path:
    """The ``llama-server`` executable (``UTTER_LLAMACPP_SERVER`` override)."""
    override = os.environ.get("UTTER_LLAMACPP_SERVER")
    if override:
        return Path(override)
    name = "llama-server.exe" if (platform_name or _platform_name()) == "windows" else "llama-server"
    return llamacpp_dir(root) / name


def llamacpp_build_path(root: Path | None = None) -> Path:
    """The pinned-build record written after a successful install."""
    return llamacpp_dir(root) / "build.json"


def llama_tag(build_tag: str) -> str:
    """Normalise a build tag to llama.cpp's ``bNNNNN`` form."""
    tag = str(build_tag).strip()
    return tag if tag.startswith("b") else f"b{tag}"


def llamacpp_assets(build_tag: str, platform_name: str, *,
                    arch: str | None = None, cuda: bool | None = None) -> tuple[str, ...]:
    """The release asset name(s) for a build tag and platform.

    Windows CUDA needs the separate ``cudart`` archive alongside the server.
    """
    tag = llama_tag(build_tag)
    if platform_name == "windows":
        if cuda is None:
            cuda = cuda_available()
        if cuda:
            return (f"llama-{tag}-bin-win-cuda-12.4-x64.zip",
                    f"cudart-llama-bin-win-cuda-12.4-x64.zip")
        return (f"llama-{tag}-bin-win-cpu-x64.zip",)
    if platform_name == "macos":
        machine = (arch or _platform.machine()).lower()
        if machine in ("arm64", "aarch64"):
            return (f"llama-{tag}-bin-macos-arm64.tar.gz",)
        return (f"llama-{tag}-bin-macos-x64.tar.gz",)
    return ()


def resolve_llamacpp_tag(timeout: float = 15.0) -> str | None:
    """Resolve the current llama.cpp build tag; ``UTTER_LLAMACPP_TAG`` wins.

    Reads ``releases/latest/download/nightly-tag.txt`` (e.g. ``b11146``). Returns
    None when the tag is neither pinned by env nor resolvable.
    """
    override = (os.environ.get("UTTER_LLAMACPP_TAG") or "").strip()
    if override:
        return override
    try:
        req = urllib.request.Request(LLAMACPP_NIGHTLY_TAG_URL)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            tag = resp.read(64).decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return tag or None


def serve_planner_command(server: str | os.PathLike[str], model: str | os.PathLike[str], *,
                          port: int | str = 8001, served_name: str = "qwen3-4b",
                          ctx: int | str = 4096, ngl: str = "auto") -> list[str]:
    """The argv to launch ``llama-server`` for the planner (mirrors the shell)."""
    return [
        str(server),
        "--model", str(model),
        "--alias", served_name,
        "--host", "127.0.0.1",
        "--port", str(port),
        "-c", str(ctx),
        "-ngl", str(ngl),
        "-fa", "auto",
        "--jinja",
        "--reasoning", "off",
        "-np", "1",
        "--no-webui",
    ]


def _planner_present(platform_name: str | None = None, root: Path | None = None) -> bool:
    """Backend-aware planner readiness."""
    if planner_backend(platform_name) == LLAMACPP_BACKEND:
        gguf = planner_gguf_path(root)
        try:
            return gguf.is_file() and gguf.stat().st_size > 0
        except OSError:
            return False
    return model_present(model_paths(root)[1])


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
    """Whether the vision and planner payloads look complete.

    JSON shape: ``{"vision": bool, "planner": bool, "vision_path": str,
    "planner_path": str, "planner_backend": "vllm"|"llamacpp"}``.
    """
    vision, _ = model_paths()
    backend = planner_backend()
    return {
        "vision": model_present(vision),
        "planner": _planner_present(),
        "vision_path": str(vision),
        "planner_path": str(planner_path()),
        "planner_backend": backend,
    }


def human(data: dict) -> str:
    backend = data.get("planner_backend") or planner_backend()
    lines = [
        f"vision:  {'present' if data['vision'] else 'missing'}  ({data['vision_path']})",
        f"planner: {'present' if data['planner'] else 'missing'}  ({data['planner_path']})",
        f"vision serve:  {serve_script()}",
        f"planner serve: {serve_planner_script()} ({backend})",
    ]
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


def _place_file(src: Path, dst: Path) -> None:
    """Put ``src`` at ``dst``, hard-linking when possible, else copying."""
    try:
        if dst.exists():
            dst.unlink()
    except OSError:
        pass
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _planner_gguf_ready(root: Path, platform_name: str) -> bool:
    """True when a usable GGUF (or an explicit complete planner dir) is present."""
    gguf = planner_gguf_path(root)
    try:
        if gguf.is_file() and gguf.stat().st_size > 0:
            return True
    except OSError:
        return False
    override = os.environ.get("UTTER_PLANNER_MODEL_PATH")
    return bool(override and model_present(override))


def _install_planner_gguf(emit, root: Path, platform_name: str) -> bool:
    """Download the Q4_K_M GGUF into the planner model directory."""
    target = planner_gguf_path(root)
    if _planner_gguf_ready(root, platform_name):
        emit(f"[install_inference] planner GGUF already present in {target}")
        return True
    repo = planner_model_id(platform_name)
    source = f"hf:{repo}:{LLAMACPP_GGUF_FILE}"
    emit(f"[install_inference] planner model: {repo} ({LLAMACPP_GGUF_QUANT})")
    emit(f"[install_inference] downloading {source}")
    try:
        result = models.pull(source, tag=LLAMACPP_GGUF_QUANT, quiet=True)
    except (RuntimeError, ValueError, OSError) as exc:
        emit(f"[install_inference] planner GGUF download failed: {exc}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    _place_file(Path(result["path"]), target)
    emit(f"[install_inference] planner GGUF ready "
         f"({util.human_bytes(result['bytes'])} sha256:{result['sha256'][:16]}…)")
    return True


def _extract_archive(archive: Path, dest: Path) -> None:
    """Extract a ``.zip`` / ``.tar.gz`` release asset into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tf:
            try:
                tf.extractall(dest, filter="data")
            except TypeError:  # pragma: no cover - Python < 3.12
                tf.extractall(dest)


def _copy_tree_files(src: Path, dst: Path) -> None:
    """Flatten every file under ``src`` into ``dst`` (release archives nest a dir)."""
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        if path.is_file():
            shutil.copyfile(path, dst / path.name)


def _find_llamacpp_server(directory: Path, platform_name: str) -> Path | None:
    name = "llama-server.exe" if platform_name == "windows" else "llama-server"
    matches = sorted(directory.rglob(name))
    return matches[0] if matches else None


def _install_llamacpp_server(emit, root: Path, platform_name: str) -> bool:
    """Fetch + pin the llama.cpp ``llama-server`` build for this platform."""
    server = llamacpp_server_path(root, platform_name)
    if server.is_file():
        emit(f"[install_inference] llama-server already present at {server}")
        return True

    pin = util.read_json(llamacpp_build_path(root))
    pinned_tag = pin.get("tag") if isinstance(pin, dict) else None
    tag = os.environ.get("UTTER_LLAMACPP_TAG") or pinned_tag or resolve_llamacpp_tag()
    if not tag:
        emit("[install_inference] could not resolve the llama.cpp build tag; "
             "set UTTER_LLAMACPP_TAG (e.g. b11146) and retry")
        return False

    assets = llamacpp_assets(str(tag), platform_name)
    if not assets:
        emit(f"[install_inference] no llama.cpp build published for {platform_name}")
        return False

    directory = llamacpp_dir(root)
    staging = Path(tempfile.mkdtemp(prefix="utter-llamacpp-"))
    try:
        downloads: list[dict] = []
        for index, asset in enumerate(assets):
            url = f"{LLAMACPP_RELEASE_BASE}/{llama_tag(tag)}/{asset}"
            emit(f"[install_inference] fetching {asset} ({llama_tag(tag)})")
            try:
                result = models.pull(url, tag=llama_tag(tag), quiet=True)
            except (RuntimeError, ValueError, OSError) as exc:
                emit(f"[install_inference] download failed: {asset}: {exc}")
                return False
            downloads.append({"asset": asset, "url": url,
                              "sha256": result["sha256"], "bytes": result["bytes"]})
            _extract_archive(Path(result["path"]), staging / str(index))
        _copy_tree_files(staging, directory)
        found = _find_llamacpp_server(directory, platform_name)
        if found is None:
            emit("[install_inference] extracted archives did not contain llama-server")
            return False
        util.atomic_write_json(llamacpp_build_path(root), {
            "tag": llama_tag(tag),
            "platform": platform_name,
            "assets": downloads,
            "server": str(found),
        })
        emit(f"[install_inference] llama-server ready at {found}")
        return True
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _install_llamacpp(emit, root: Path, platform_name: str) -> bool:
    """The macOS/Windows planner: GGUF checkpoint + pinned llama-server build."""
    if not _install_planner_gguf(emit, root, platform_name):
        return False
    return _install_llamacpp_server(emit, root, platform_name)


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

    vision_id, _ = model_ids(platform_name)
    vision_dir, _ = model_paths(root)

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
    elif planner_backend(platform_name) == LLAMACPP_BACKEND:
        if not _install_llamacpp(emit, root, platform_name):
            return _fail(json_progress, "could not install the llama.cpp planner")
    else:
        planner_id = planner_model_id(platform_name)
        _, planner_dir = model_paths(root)
        if not planner_id:
            emit("[install_inference] no planner model id set; skipping")
        elif model_present(planner_dir):
            emit(f"[install_inference] planner model already present in {planner_dir}")
        else:
            emit(f"[install_inference] planner model: {planner_id}")
            emit(f"[install_inference] downloading {planner_id} -> {planner_dir}")
            if _hf_download(interpreter, planner_id, planner_dir, emit, root) != 0:
                return _fail(json_progress, f"could not download {planner_id}")

    emit("[install_inference] done")
    if platform_name in ("macos", "windows"):
        emit("[install_inference] serves the vision model via "
             "scripts/serve_vision_transformers.py")
    else:
        emit("[install_inference] next: scripts/serve_vision.sh   # http://127.0.0.1:8000/v1 (uitars)")
    emit(f"[install_inference] next: {serve_planner_script(platform_name)}  "
         "# http://127.0.0.1:8001/v1 (qwen3-4b)")

    if json_progress:
        util.ndjson({"event": "done", "ok": True})
    return 0


# --------------------------------------------------------------------------- #
# check (probe a running planner endpoint)
# --------------------------------------------------------------------------- #
def planner_base_url() -> str:
    """The planner OpenAI endpoint (``UTTER_PLANNER_BASE_URL`` or :8001)."""
    override = os.environ.get("UTTER_PLANNER_BASE_URL")
    if override:
        return override.rstrip("/")
    port = os.environ.get("UTTER_PLANNER_PORT", "8001")
    return f"http://127.0.0.1:{port}/v1"


def _planner_served_name() -> str:
    return os.environ.get("UTTER_PLANNER_SERVED_NAME", "qwen3-4b")


def _http_json(method: str, url: str, payload: dict | None = None,
               timeout: float = 8.0) -> dict:
    """Minimal JSON HTTP call (stdlib; monkeypatchable for tests)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


#: A trivial tool used by :func:`check` to pin the tool-calling contract.
_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "focus_app",
        "description": "Focus a desktop application by name.",
        "parameters": {
            "type": "object",
            "properties": {"app": {"type": "string"}},
            "required": ["app"],
        },
    },
}

#: A trivial response_format schema used by :func:`check` (nested wrapper!).
_CHECK_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


def check(base_url: str | None = None, *, timeout: float = 8.0) -> dict:
    """Smoke-check a running planner endpoint.

    Probes ``/v1/models``, then asks for one tool call (asserting
    ``finish_reason == "tool_calls"``) and one ``json_schema`` response (asserting
    valid JSON). Does **not** start a server: when nothing is listening it returns
    a clear message pointing at the right serve script.
    """
    base = (base_url or planner_base_url()).rstrip("/")
    model = _planner_served_name()
    result: dict = {
        "ok": False, "reachable": False, "base_url": base,
        "models": None, "tool_call": None, "json_schema": None, "errors": [],
    }
    try:
        listing = _http_json("GET", f"{base}/models", timeout=timeout)
        result["reachable"] = True
        result["models"] = [m.get("id") for m in listing.get("data", []) if isinstance(m, dict)]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        result["errors"].append(f"models probe failed: {exc}")
        result["detail"] = (
            f"no planner server reachable at {base}; start "
            f"`{serve_planner_script()}` and retry"
        )
        return result

    try:
        response = _http_json("POST", f"{base}/chat/completions", {
            "model": model,
            "temperature": 0.0,
            "messages": [{"role": "user",
                          "content": "Call focus_app with app='firefox'."}],
            "tools": [_CHECK_TOOL],
            "tool_choice": "auto",
        }, timeout=timeout)
        choice = response["choices"][0]
        message = choice.get("message") or {}
        finish = choice.get("finish_reason")
        calls = message.get("tool_calls") or []
        tool_ok = finish == "tool_calls" and bool(calls)
        result["tool_call"] = {"ok": tool_ok, "finish_reason": finish,
                               "tool_calls": calls}
        if not tool_ok:
            result["errors"].append(
                f"tool call: expected finish_reason='tool_calls', got {finish!r}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        result["errors"].append(f"tool-call request failed: {exc}")
        result["tool_call"] = {"ok": False, "error": str(exc)}

    try:
        response = _http_json("POST", f"{base}/chat/completions", {
            "model": model,
            "temperature": 0.0,
            "messages": [{"role": "user",
                          "content": 'Respond with JSON: {"ok": true}'}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "ok_result",
                                                "schema": _CHECK_SCHEMA}},
        }, timeout=timeout)
        content = (response["choices"][0].get("message") or {}).get("content")
        parsed = json.loads(content) if isinstance(content, str) else None
        schema_ok = isinstance(parsed, dict)
        result["json_schema"] = {"ok": schema_ok, "content": content, "parsed": parsed}
        if not schema_ok:
            result["errors"].append("json_schema: response content was not valid JSON object")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        result["errors"].append(f"json_schema request failed: {exc}")
        result["json_schema"] = {"ok": False, "error": str(exc)}

    result["ok"] = (
        result["reachable"]
        and bool(result["tool_call"] and result["tool_call"].get("ok"))
        and bool(result["json_schema"] and result["json_schema"].get("ok"))
    )
    return result


def human_check(data: dict) -> str:
    lines = [f"planner check: {'OK' if data.get('ok') else 'FAILED'}  ({data.get('base_url')})"]
    if not data.get("reachable"):
        lines.append(f"  server:       unreachable — {data.get('detail', 'not running')}")
        return "\n".join(lines)
    models = data.get("models") or []
    lines.append(f"  /v1/models:   {len(models)} model(s)" + (f" [{', '.join(str(m) for m in models)}]" if models else ""))
    tool = data.get("tool_call") or {}
    lines.append(f"  tool call:    {'ok' if tool.get('ok') else 'failed'}"
                 f" (finish_reason={tool.get('finish_reason')!r})")
    schema = data.get("json_schema") or {}
    lines.append(f"  json_schema:  {'ok' if schema.get('ok') else 'failed'}")
    for error in data.get("errors", []):
        lines.append(f"  ! {error}")
    return "\n".join(lines)
