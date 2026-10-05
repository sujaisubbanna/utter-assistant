"""Per-user token + endpoint files for the loopback-TCP transport (stdlib only).

On Windows the runner listens on ``127.0.0.1`` with a mandatory random token.
Both live under ``%LOCALAPPDATA%\\utter`` by default. The real protection is
**NTFS ACL inheritance** from the per-user profile directory — ``chmod`` is
best-effort only (on Windows it flips the read-only bit, nothing more). On
non-Windows the TCP path is only used by tests, and the store lives under
``$XDG_STATE_HOME`` / ``~/.local/state``.

The endpoint JSON is written atomically (temp file + ``os.replace``) so a client
never reads a torn ``{"host": "127.0.0.1", "port": N}`` record.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path

from . import platform as _platform

_TOKEN_NAME = "runner-token"
_ENDPOINT_NAME = "runner.endpoint"


def default_dir() -> Path:
    """Per-user runner state directory for the TCP transport."""
    if _platform.is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "utter"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "utter"


def default_token_path() -> str:
    return str(default_dir() / _TOKEN_NAME)


def default_endpoint_path() -> str:
    return str(default_dir() / _ENDPOINT_NAME)


def _chmod_best_effort(path: str | Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _fchmod_best_effort(fd: int, mode: int) -> None:
    fn = getattr(os, "fchmod", None)
    if fn is None:
        return
    try:
        fn(fd, mode)
    except OSError:
        pass


def read_token(path: str | os.PathLike) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_token(path: str | os.PathLike, token: str) -> None:
    """Atomically persist ``token`` to ``path`` (mode 0600 best-effort)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-token-")
    try:
        _fchmod_best_effort(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _chmod_best_effort(p, 0o600)


def load_or_create_token(path: str | os.PathLike) -> str:
    """Return the stored token, creating it with ``O_CREAT|O_EXCL`` if absent.

    Idempotent: concurrent/no-op callers get the same token. If an existing file
    is empty (a crashed first writer) it is replaced atomically.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        existing = read_token(p)
        if existing:
            return existing
        fd = os.open(str(p), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    _fchmod_best_effort(fd, 0o600)
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    _chmod_best_effort(p, 0o600)
    return token


def ensure_token(path: str | os.PathLike, token: str = "") -> str:
    """Ensure ``path`` holds ``token`` (or a fresh random one) and return it."""
    if not token:
        return load_or_create_token(path)
    if read_token(path) != token:
        write_token(path, token)
    return token


def write_endpoint(path: str | os.PathLike, host: str, port: int) -> None:
    """Atomically write ``{"host": host, "port": port}`` to ``path``."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-endpoint-")
    try:
        _fchmod_best_effort(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"host": str(host), "port": int(port)}, fh)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _chmod_best_effort(p, 0o600)


def read_endpoint(path: str | os.PathLike) -> dict | None:
    """Return ``{"host", "port"}`` or ``None`` when absent/invalid."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    host = data.get("host")
    port = data.get("port")
    if not isinstance(host, str) or not host or not isinstance(port, int):
        return None
    return {"host": host, "port": port}


def remove_endpoint(path: str | os.PathLike) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


__all__ = [
    "default_dir",
    "default_token_path",
    "default_endpoint_path",
    "read_token",
    "write_token",
    "load_or_create_token",
    "ensure_token",
    "write_endpoint",
    "read_endpoint",
    "remove_endpoint",
]
