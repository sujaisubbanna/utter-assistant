"""Shared helpers for the assistant CLI (stdlib only)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# XDG paths
# --------------------------------------------------------------------------- #
def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))


def xdg_runtime_dir() -> Path:
    override = os.environ.get("XDG_RUNTIME_DIR")
    if override:
        return Path(override)
    linux_default = Path(f"/run/user/{os.getuid()}")
    if linux_default.is_dir():
        return linux_default
    # macOS has no XDG runtime dir; mirror runner.socket.default_socket_path().
    import tempfile
    return Path(tempfile.gettempdir()) / f"utter-{os.getuid()}"


def models_root() -> Path:
    override = os.environ.get("UTTER_MODELS")
    if override:
        return Path(override)
    return xdg_data_home() / "utter" / "models"


def state_dir() -> Path:
    return xdg_state_home() / "utter"


def install_json_path() -> Path:
    return state_dir() / "install.json"


def runner_sock_path() -> str:
    return os.environ.get("UTTER_RUNNER_SOCK") or str(
        xdg_runtime_dir() / "utter" / "runner.sock"
    )


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def human_bytes(n: int | float | None) -> str:
    if n is None:
        return "?"
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


def emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def ndjson(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)
