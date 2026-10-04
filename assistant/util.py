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


# The model store lives at ``$XDG_DATA_HOME/utter-models`` — a sibling of the
# install tree (``$PREFIX/share/utter``), NOT inside it. When the default prefix
# is ``~/.local`` the install tree is ``~/.local/share/utter`` (= XDG_DATA_HOME/
# utter), so keeping the store under ``.../utter/models`` would let an uninstall
# of the core tree delete the downloaded models. The old location is kept as a
# one-time migration source only.
_MODELS_DIRNAME = "utter-models"
_LEGACY_MODELS_DIRNAME = "utter"
_LEGACY_MIGRATION: dict[str, str] = {}


def legacy_models_root() -> Path:
    """The pre-decoupling store: ``$XDG_DATA_HOME/utter/models`` (inside the tree)."""
    return xdg_data_home() / _LEGACY_MODELS_DIRNAME / "models"


def _dir_has_entries(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is not None
    except OSError:
        return False


def _rewrite_manifest_paths(root: Path, old_prefix: str, new_prefix: str) -> None:
    """Re-point absolute blob paths recorded in manifests after a store move."""
    base = root / "manifests"
    if not base.is_dir():
        return
    prefix = old_prefix + os.sep
    for path in sorted(base.glob("*/*/*/*.json")):
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        changed = False
        for entry in data.get("files", []) or []:
            p = entry.get("path") if isinstance(entry, dict) else None
            if isinstance(p, str) and p.startswith(prefix):
                entry["path"] = new_prefix + p[len(old_prefix):]
                changed = True
        if changed:
            atomic_write_json(path, data)


def _migrate_models(src: Path, dst: Path) -> None:
    """Move a legacy store once; raise OSError (source left intact) on failure."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            dst.rmdir()  # the caller only migrates into an empty/absent dst
        except OSError:
            pass
    shutil.move(str(src), str(dst))
    _rewrite_manifest_paths(dst, str(src), str(dst))
    eprint(f"assistant: moved model store {src} -> {dst} (now outside the install tree)")


def models_root() -> Path:
    override = os.environ.get("UTTER_MODELS")
    if override:
        return Path(override)
    canonical = xdg_data_home() / _MODELS_DIRNAME
    if _dir_has_entries(canonical):
        return canonical
    legacy = legacy_models_root()
    if _dir_has_entries(legacy) and legacy.resolve() != canonical.resolve():
        try:
            _migrate_models(legacy, canonical)
        except OSError as exc:
            if _dir_has_entries(canonical):
                return canonical  # another process completed the move first
            eprint(f"assistant: could not move models {legacy} -> {canonical}: {exc}; "
                   "keeping them where they are (not deleted)")
            _LEGACY_MIGRATION["fallback_to"] = str(legacy)
            return legacy
        _LEGACY_MIGRATION["migrated_from"] = str(legacy)
        return canonical
    return canonical


def models_status() -> dict[str, Any]:
    """Where the store is, plus any one-time legacy migration/fallback."""
    root = models_root()
    legacy = legacy_models_root()
    return {
        "root": str(root),
        "legacy_root": str(legacy),
        "legacy_present": _dir_has_entries(legacy),
        "override": os.environ.get("UTTER_MODELS"),
        "migrated_from": _LEGACY_MIGRATION.get("migrated_from"),
        "fallback_to": _LEGACY_MIGRATION.get("fallback_to"),
    }


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
