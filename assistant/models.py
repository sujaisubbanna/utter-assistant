"""Model store: XDG manifests + content-addressed blobs, resumable pulls.

Layout (Ollama-style, XDG)::

    $XDG_DATA_HOME/utter-models/          # override: UTTER_MODELS
      manifests/<host>/<ns>/<name>/<tag>.json
      blobs/sha256-<hex>

The store deliberately lives beside the install tree, not inside it: the web
installer removes ``$PREFIX/share/utter`` on uninstall and must never delete
downloaded models. A legacy ``$XDG_DATA_HOME/utter/models`` store is moved here
once on first use (see :func:`assistant.util.models_root`).

Sources: ``hf:org/repo[:file]``, bare ``https://…``, ``file://`` (and a bare
local path). Downloads are resumable (``curl -C -`` or urllib ``Range``), with
retry/backoff, stall detection, sha256 verification, atomic rename, a pull lock
and a disk-space preflight. ``--json`` emits NDJSON progress lines.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from . import util

DEFAULT_HF_FILE = "model.safetensors"
_HF_FALLBACK_FILES = [
    "model.safetensors", "pytorch_model.bin", "model.onnx",
    "ggml-model.bin", "model.gguf", "model.bin",
]
_CHUNK = 65536


# --------------------------------------------------------------------------- #
# source resolution
# --------------------------------------------------------------------------- #
@dataclass
class Source:
    url: str
    host: str
    ns: str
    name: str
    tag: str
    filename: str
    explicit_file: bool = False
    sha256: Optional[str] = None
    size: Optional[int] = None


def resolve_source(source: str, tag: str = "latest") -> Source:
    s = (source or "").strip()
    if not s:
        raise ValueError("empty source")
    if s.startswith("hf:"):
        spec = s[3:]
        repo, _, file = spec.partition(":")
        org, _, name = repo.partition("/")
        if not org or not name:
            raise ValueError(f"bad hf source (want hf:org/repo[:file]): {source!r}")
        filename = file or DEFAULT_HF_FILE
        url = f"https://huggingface.co/{org}/{name}/resolve/main/{filename}"
        return Source(url, "huggingface.co", org, name, tag, filename, explicit_file=bool(file))
    if s.startswith("file://"):
        path = Path(s[7:])
        return Source(s, "local", "_", path.stem or "model", tag, path.name)
    if s.startswith("http://") or s.startswith("https://"):
        u = urlparse(s)
        host = (u.netloc or "remote").replace(":", "_")
        filename = Path(u.path).name or "download.bin"
        name = Path(filename).stem or "model"
        return Source(s, host, "_", name, tag, filename)
    path = Path(s)
    if path.exists():
        return Source("file://" + str(path.resolve()), "local", "_", path.stem or "model",
                      tag, path.name)
    raise ValueError(f"unrecognised source: {source!r}")


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _sha_from_etag(etag: Optional[str]) -> Optional[str]:
    if not etag:
        return None
    value = etag.strip().strip('"')
    if value.lower().startswith("sha256:"):
        value = value.split(":", 1)[1]
    if len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower()):
        return value.lower()
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop after the first response instead of chasing the redirect.

    huggingface.co answers ``/resolve/main/<file>`` with a 302 whose
    ``X-Linked-ETag`` is the file's true content sha256 and ``X-Linked-Size``
    its true length. The CDN it points at only sends the Xet dedup ``ETag``
    (a *different* hash) and no ``X-Linked-*``. Following the redirect silently
    swaps in the wrong hash, so every Xet-backed ``hf:`` pull verifies bytes
    that are actually intact against the Xet hash and rejects them.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def _content_meta(headers) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Metadata from a final (non-redirect) response."""
    size_hdr = headers.get("X-Linked-Size") or headers.get("Content-Length")
    etag = headers.get("X-Linked-ETag") or headers.get("ETag")
    sha = headers.get("X-Linked-Sha256") or _sha_from_etag(etag)
    size = int(size_hdr) if size_hdr and size_hdr.isdigit() else None
    return size, sha, etag


def _linked_meta(headers) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Metadata from HF's ``/resolve`` redirect: only X-Linked-* are content facts.

    ``Content-Length`` there describes the tiny redirect body, so it is ignored.
    """
    size_hdr = headers.get("X-Linked-Size")
    etag = headers.get("X-Linked-ETag")
    size = int(size_hdr) if size_hdr and size_hdr.isdigit() else None
    return size, _sha_from_etag(etag), etag


def _head_followed(url: str, timeout: float) -> tuple[Optional[int], Optional[str], Optional[str]]:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _content_meta(resp.headers)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None, None, None


def head(url: str, timeout: float = 15.0) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Return (size, sha256, etag) for ``url`` (None values when unknown)."""
    # First hop only: keep HF's X-Linked-* headers, which the CDN omits.
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        req = urllib.request.Request(url, method="HEAD")
        with opener.open(req, timeout=timeout) as resp:
            return _content_meta(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            headers = getattr(exc, "headers", None)
            if headers is not None:
                size, sha, etag = _linked_meta(headers)
                if size is not None or sha:
                    if size is None:  # got the hash but not the size
                        followed = _head_followed(url, timeout)
                        return followed[0], sha or followed[1], etag or followed[2]
                    return size, sha, etag
        finally:
            try:
                exc.close()
            except OSError:
                pass
    except (urllib.error.URLError, OSError, ValueError):
        pass
    # Generic servers (or no X-Linked-*): follow redirects as before.
    return _head_followed(url, timeout)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# pull lock
# --------------------------------------------------------------------------- #
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _acquire_lock(root: Path, src: Source) -> Path:
    locks = root / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    path = locks / f"{src.host}_{src.ns}_{src.name}_{src.tag}.lock"
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return path
        except FileExistsError:
            try:
                pid = int(path.read_text().strip())
            except (OSError, ValueError):
                pid = None
            if pid is not None and not _pid_alive(pid):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            raise RuntimeError(f"pull already in progress (lock: {path})")
    raise RuntimeError("could not acquire the pull lock")


def _release_lock(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #
Progress = Callable[[int, Optional[int]], None]

# The currently-running curl child, so a SIGINT/SIGTERM can stop it cleanly.
_ACTIVE_CHILD: Optional[subprocess.Popen] = None


def terminate_active_child() -> None:
    child = _ACTIVE_CHILD
    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except OSError:
            pass


# A download strategy performs one attempt and returns True when the blob is
# complete; raising _AttemptFailed signals a retryable failure. Retry/backoff is
# shared by _download_with_retries so both transports behave identically.
DownloadStrategy = Callable[[str, Path, Optional[int], Progress, float], bool]


class _AttemptFailed(Exception):
    """One download attempt failed; the shared loop decides whether to retry."""


def _attempt_curl(url: str, partial: Path, total: Optional[int], progress: Progress,
                  stall_timeout: float) -> bool:
    global _ACTIVE_CHILD
    cmd = ["curl", "-L", "--fail", "--silent", "--show-error", "-C", "-",
           "-o", str(partial), url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _ACTIVE_CHILD = proc
    last_size = partial.stat().st_size if partial.exists() else 0
    last_change = time.monotonic()
    try:
        while proc.poll() is None:
            time.sleep(0.2)
            size = partial.stat().st_size if partial.exists() else 0
            if size != last_size:
                last_size = size
                last_change = time.monotonic()
                progress(size, total)
            elif time.monotonic() - last_change > stall_timeout:
                proc.kill()
                break
        rc = proc.wait()
    finally:
        _ACTIVE_CHILD = None
        if proc.stderr is not None:
            proc.stderr.close()
    if rc == 0:
        return True
    raise _AttemptFailed(url)


def _attempt_urllib(url: str, partial: Path, total: Optional[int], progress: Progress,
                    stall_timeout: float) -> bool:
    existing = partial.stat().st_size if partial.exists() else 0
    req = urllib.request.Request(url)
    if existing:
        req.add_header("Range", f"bytes={existing}-")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if existing and getattr(resp, "status", 200) != 206:
                existing = 0  # server ignored Range -> restart
            mode = "ab" if existing else "wb"
            downloaded = existing
            with open(partial, mode) as fh:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    progress(downloaded, total)
        return True
    except (urllib.error.URLError, OSError) as exc:
        raise _AttemptFailed(exc) from exc


def _download_with_retries(strategy: DownloadStrategy, url: str, partial: Path,
                           total: Optional[int], progress: Progress, retries: int,
                           stall_timeout: float) -> Path:
    last: object = url
    for attempt in range(1, retries + 1):
        if total and partial.exists() and partial.stat().st_size >= total:
            return partial
        try:
            if strategy(url, partial, total, progress, stall_timeout):
                return partial
        except _AttemptFailed as exc:
            last = exc.args[0] if exc.args else url
        if attempt < retries:
            time.sleep(min(2 ** attempt, 5))
    raise RuntimeError(f"download failed after {retries} attempts: {last}")


def _download(src: Source, blobs: Path, progress: Progress, retries: int,
              stall_timeout: float) -> Path:
    if src.sha256:
        partial = blobs / f"sha256-{src.sha256}.partial"
    else:
        partial = blobs / f"{src.host}_{src.ns}_{src.name}_{src.tag}.partial"
    strategy = _attempt_curl if util.which("curl") else _attempt_urllib
    return _download_with_retries(strategy, src.url, partial, src.size, progress,
                                  retries, stall_timeout)


# --------------------------------------------------------------------------- #
# manifests
# --------------------------------------------------------------------------- #
def _manifest_path(root: Path, src: Source) -> Path:
    return root / "manifests" / src.host / src.ns / src.name / f"{src.tag}.json"


def _write_manifest(root: Path, src: Source, blob: Path, digest: str) -> Path:
    manifest = {
        "name": src.name,
        "tag": src.tag,
        "host": src.host,
        "ns": src.ns,
        "created": time.time(),
        "files": [{
            "name": src.filename,
            "source": src.url,
            "sha256": digest,
            "bytes": blob.stat().st_size,
            "path": str(blob),
        }],
    }
    path = _manifest_path(root, src)
    util.atomic_write_json(path, manifest)
    return path


def _iter_manifests(root: Path) -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    base = root / "manifests"
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*/*/*/*.json")):
        data = util.read_json(path)
        if isinstance(data, dict):
            out.append((path, data))
    return out


def _referenced_blobs(root: Path) -> set[str]:
    refs: set[str] = set()
    for _path, data in _iter_manifests(root):
        for f in data.get("files", []) or []:
            if f.get("path"):
                refs.add(str(Path(f["path"]).resolve()))
    return refs


def _gc_blobs(root: Path) -> list[str]:
    blobs = root / "blobs"
    if not blobs.is_dir():
        return []
    refs = _referenced_blobs(root)
    removed: list[str] = []
    for blob in blobs.iterdir():
        if not blob.is_file():
            continue
        if str(blob.resolve()) not in refs:
            try:
                blob.unlink()
                removed.append(blob.name)
            except OSError:
                pass
    return removed


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def _plan(src: Source, root: Path) -> None:
    """Resolve remote metadata (size/sha, HF fallback) and preflight disk space."""
    size, sha, _etag = head(src.url)
    if size is None and src.host == "huggingface.co" and not src.explicit_file:
        for candidate in _HF_FALLBACK_FILES:
            url = f"https://huggingface.co/{src.ns}/{src.name}/resolve/main/{candidate}"
            size, sha, _etag = head(url)
            if size is not None:
                src.url, src.filename = url, candidate
                break
    if size is None:
        raise RuntimeError(f"could not resolve {src.url} (HEAD failed)")
    src.size, src.sha256 = size, sha
    free = shutil.disk_usage(root).free
    if size and free < size * 1.05:
        raise RuntimeError(
            f"not enough disk space: need {util.human_bytes(size)}, "
            f"free {util.human_bytes(free)}"
        )


def _transfer(src: Source, blobs: Path, progress: Progress, retries: int,
              stall_timeout: float) -> tuple[Path, str]:
    """Download to a partial path and verify its sha256, returning (partial, digest)."""
    partial = _download(src, blobs, progress, retries, stall_timeout)
    digest = _sha256_file(partial)
    if src.sha256 and digest != src.sha256:
        try:
            partial.unlink()
        except OSError:
            pass
        raise RuntimeError(f"sha256 mismatch: expected {src.sha256}, got {digest}")
    return partial, digest


def _materialize(root: Path, src: Source, partial: Path, digest: str,
                 blobs: Path) -> tuple[Path, Path]:
    """Move the verified partial to its content-addressed blob and write the manifest."""
    final = blobs / f"sha256-{digest}"
    os.replace(partial, final)
    manifest = _write_manifest(root, src, final, digest)
    return final, manifest


def pull(source: str, *, tag: str = "latest", json_progress: bool = False,
         retries: int = 3, stall_timeout: float = 20.0, quiet: bool = False) -> dict:
    src = resolve_source(source, tag)
    root = util.models_root()
    blobs = root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)

    def progress(downloaded: int, total: Optional[int]) -> None:
        if json_progress:
            util.ndjson({
                "event": "progress", "name": src.name, "tag": src.tag,
                "downloaded": downloaded, "total": total,
                "percent": round(downloaded / total * 100, 1) if total else None,
            })
        elif not quiet:
            util.eprint(f"  {util.human_bytes(downloaded)}"
                        + (f" / {util.human_bytes(total)}" if total else ""))

    if json_progress:
        util.ndjson({"event": "start", "name": src.name, "tag": src.tag, "source": src.url})

    lock = _acquire_lock(root, src)
    try:
        if src.url.startswith("file://"):
            local = Path(src.url[7:])
            if not local.is_file():
                raise RuntimeError(f"local file not found: {local}")
            digest = _sha256_file(local)
            final = blobs / f"sha256-{digest}"
            if not final.exists():
                shutil.copyfile(local, final)
            manifest = _write_manifest(root, src, final, digest)
        else:
            _plan(src, root)
            partial, digest = _transfer(src, blobs, progress, retries, stall_timeout)
            final, manifest = _materialize(root, src, partial, digest, blobs)
        result = {"name": src.name, "tag": src.tag, "sha256": digest,
                  "bytes": final.stat().st_size, "path": str(final),
                  "manifest": str(manifest), "source": src.url}
        if json_progress:
            util.ndjson({"event": "done", **result})
        return result
    finally:
        _release_lock(lock)


def list_models() -> list[dict]:
    out: list[dict] = []
    for path, data in _iter_manifests(util.models_root()):
        files = data.get("files", []) or []
        out.append({
            "name": data.get("name"),
            "tag": data.get("tag"),
            "host": data.get("host"),
            "ns": data.get("ns"),
            "bytes": sum(int(f.get("bytes") or 0) for f in files),
            "files": len(files),
            "manifest": str(path),
        })
    return out


def show(name: str) -> list[dict]:
    matches: list[dict] = []
    for path, data in _iter_manifests(util.models_root()):
        full = f"{data.get('name')}:{data.get('tag')}"
        if name in (data.get("name"), full):
            entry = dict(data)
            entry["manifest"] = str(path)
            matches.append(entry)
    return matches


def rm(name: str) -> dict:
    removed: list[str] = []
    for path, data in _iter_manifests(util.models_root()):
        full = f"{data.get('name')}:{data.get('tag')}"
        if name in (data.get("name"), full):
            try:
                path.unlink()
                removed.append(str(path))
            except OSError:
                pass
    gc = _gc_blobs(util.models_root())
    return {"removed_manifests": removed, "removed_blobs": gc}


def prune() -> dict:
    root = util.models_root()
    partials: list[str] = []
    blobs = root / "blobs"
    if blobs.is_dir():
        for path in blobs.glob("*.partial"):
            try:
                path.unlink()
                partials.append(path.name)
            except OSError:
                pass
    gc = _gc_blobs(root)
    return {"removed_partials": partials, "removed_blobs": gc}


def human_list(models: list[dict]) -> str:
    if not models:
        return "(no models installed)"
    lines = [f"{'NAME':<24} {'TAG':<10} {'SIZE':>10}  FILES"]
    for m in models:
        lines.append(f"{str(m['name']):<24} {str(m['tag']):<10} "
                     f"{util.human_bytes(m['bytes']):>10}  {m['files']}")
    return "\n".join(lines)


def human_show(entries: list[dict]) -> str:
    if not entries:
        return "(not found)"
    lines: list[str] = []
    for e in entries:
        lines.append(f"{e.get('name')}:{e.get('tag')}  ({e.get('host')}/{e.get('ns')})")
        for f in e.get("files", []) or []:
            lines.append(f"  {f.get('name')}  {util.human_bytes(f.get('bytes'))}  "
                         f"sha256:{str(f.get('sha256'))[:16]}…")
            lines.append(f"    source: {f.get('source')}")
            lines.append(f"    path:   {f.get('path')}")
    return "\n".join(lines)
