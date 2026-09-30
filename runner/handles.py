"""Content-addressed, plugin-scoped handle store.

A handle is ``handle://<sha256-hex>``. It can **never** resolve to an arbitrary
path: the string is strictly validated and the on-disk path is derived only
from the validated digest + sanitized scope. Writes are atomic (temp + rename).
TTL + refcount GC reclaim bytes.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .rpc import (
    HANDLE_TOO_LARGE,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    PERMISSION_DENIED,
    PLUGIN_ERROR,
)

HANDLE_RE = re.compile(r"^handle://(?:sha256/)?([0-9a-f]{64})$")
INLINE_MAX_BYTES = 64 * 1024


class HandleError(Exception):
    def __init__(self, message: str, code: int = INTERNAL_ERROR, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass
class _Entry:
    scope: str
    path: Path
    sha256: str
    size: int
    created: float
    ttl: float
    refcount: int = 1


def default_root() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return str(Path(base) / "utter" / "handles")


class HandleStore:
    def __init__(self, root: str | os.PathLike, *, default_ttl: float = 300.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self.default_ttl = default_ttl
        self._entries: dict[tuple[str, str], _Entry] = {}

    # -- creation --------------------------------------------------------- #
    def create(self, data: bytes, scope: str = "default", ttl: float | None = None) -> str:
        if not isinstance(data, (bytes, bytearray)):
            raise HandleError("handle data must be bytes", INVALID_PARAMS)
        digest = hashlib.sha256(data).hexdigest()
        key = (scope, digest)
        ttl = self.default_ttl if ttl is None else ttl
        ent = self._entries.get(key)
        if ent is not None and ent.path.exists():
            ent.refcount += 1
            ent.ttl = ttl
            ent.created = time.time()
            return _handle(digest)
        directory = self.root / _safe_scope(scope)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        path = directory / digest
        tmp = directory / f".tmp-{secrets.token_hex(8)}"
        with open(tmp, "wb") as fh:
            fh.write(bytes(data))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic
        self._entries[key] = _Entry(scope, path, digest, len(data), time.time(), ttl)
        return _handle(digest)

    # -- access ----------------------------------------------------------- #
    def stat(self, handle: str, scope: str = "default") -> dict:
        return self._stat_ent(self._resolve(handle, scope))

    @staticmethod
    def _stat_ent(ent: _Entry) -> dict:
        return {
            "handle": _handle(ent.sha256),
            "sha256": ent.sha256,
            "size": ent.size,
            "created": ent.created,
            "ttl": ent.ttl,
            "expires": ent.created + ent.ttl,
            "refcount": ent.refcount,
        }

    def fetch(self, handle: str, scope: str = "default") -> bytes:
        ent = self._resolve(handle, scope)
        try:
            return ent.path.read_bytes()
        except OSError as exc:
            raise HandleError(f"handle unreadable: {exc}", PLUGIN_ERROR) from exc

    # alias used by some callers
    get = fetch

    def path_for(self, handle: str, scope: str | None = "default") -> Path:
        """Validated on-disk path for a handle (used to open an fd for fd.pass)."""
        return self._resolve_opt(handle, scope).path

    def fetch_inline(
        self, handle: str, scope: str | None = None, max_bytes: int = INLINE_MAX_BYTES
    ) -> dict:
        """Return ``{size, sha256, data_b64}`` or raise -32007 if too large."""
        ent = self._resolve_opt(handle, scope)
        if ent.size > max_bytes:
            raise HandleError(
                "handle too large for inline fetch; use fd.pass",
                HANDLE_TOO_LARGE,
                {"size": ent.size, "max_inline": max_bytes, "handle": _handle(ent.sha256)},
            )
        try:
            data = ent.path.read_bytes()
        except OSError as exc:
            raise HandleError(f"handle unreadable: {exc}", PLUGIN_ERROR) from exc
        return {
            "size": ent.size,
            "sha256": ent.sha256,
            "data_b64": base64.b64encode(data).decode("ascii"),
        }

    def stat_scoped(self, handle: str, scope: str | None = None) -> dict:
        return self._stat_ent(self._resolve_opt(handle, scope))

    def retain(self, handle: str, scope: str = "default") -> int:
        ent = self._resolve(handle, scope)
        ent.refcount += 1
        return ent.refcount

    def release(self, handle: str, scope: str = "default") -> int:
        ent = self._resolve(handle, scope)
        ent.refcount = max(0, ent.refcount - 1)
        return ent.refcount

    # -- GC --------------------------------------------------------------- #
    def gc(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        for ent in list(self._entries.values()):
            if ent.refcount <= 0 or (now - ent.created) > ent.ttl:
                self._drop(ent)
                removed += 1
        return removed

    def _drop(self, ent: _Entry) -> None:
        self._entries.pop((ent.scope, ent.sha256), None)
        try:
            ent.path.unlink()
        except OSError:
            pass

    def _resolve(self, handle: str, scope: str) -> _Entry:
        if not isinstance(handle, str):
            raise HandleError("malformed handle", INVALID_PARAMS)
        match = HANDLE_RE.match(handle)
        if not match:
            raise HandleError(f"malformed handle: {handle!r}", INVALID_PARAMS)
        digest = match.group(1)
        ent = self._entries.get((scope, digest))
        if ent is None:
            raise HandleError("unknown handle", PLUGIN_ERROR)
        if ent.scope != scope:
            raise HandleError("handle is not in scope", PERMISSION_DENIED)
        if (time.time() - ent.created) > ent.ttl:
            self._drop(ent)
            raise HandleError("handle expired", PLUGIN_ERROR)
        return ent

    def _resolve_opt(self, handle: str, scope: str | None) -> _Entry:
        """Resolve within an explicit scope, or across all scopes when None."""
        if scope is not None:
            return self._resolve(handle, scope)
        if not isinstance(handle, str):
            raise HandleError("malformed handle", INVALID_PARAMS)
        match = HANDLE_RE.match(handle)
        if not match:
            raise HandleError(f"malformed handle: {handle!r}", INVALID_PARAMS)
        digest = match.group(1)
        for (ent_scope, ent_digest), ent in list(self._entries.items()):
            if ent_digest == digest:
                if (time.time() - ent.created) > ent.ttl:
                    self._drop(ent)
                    raise HandleError("handle expired", PLUGIN_ERROR)
                return ent
        raise HandleError("unknown handle", PLUGIN_ERROR)


def _handle(digest: str) -> str:
    return f"handle://{digest}"


def _safe_scope(scope: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(scope))[:128]
    return cleaned or "default"
