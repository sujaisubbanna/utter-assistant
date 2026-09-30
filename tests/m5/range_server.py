"""A tiny Range-capable HTTP server for M5 model-store tests (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RangeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, file_path: str, *, chunk_size: int = 65536, delay: float = 0.02):
        super().__init__(("127.0.0.1", 0), RangeHandler)
        self.file_path = str(file_path)
        self.chunk_size = chunk_size
        self.delay = delay
        self.ranges_seen: list[str] = []
        self.sha256 = sha256_file(self.file_path)
        self.size = os.path.getsize(self.file_path)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{os.path.basename(self.file_path)}"


class RangeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def srv(self) -> RangeServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass

    def _headers(self, status: int, length: int, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", '"' + self.srv.sha256 + '"')
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def do_HEAD(self) -> None:
        self._headers(200, self.srv.size)

    def do_GET(self) -> None:
        srv = self.srv
        if self.path == "/stats":
            body = json.dumps({"ranges": srv.ranges_seen}).encode()
            self._headers(200, len(body))
            self.wfile.write(body)
            return

        rng = self.headers.get("Range")
        start, end = 0, srv.size - 1
        if rng and rng.startswith("bytes="):
            srv.ranges_seen.append(rng)
            spec = rng[len("bytes="):].split(",")[0]
            first, _, last = spec.partition("-")
            start = int(first) if first else 0
            end = int(last) if last else srv.size - 1
            end = min(end, srv.size - 1)
            self._headers(206, end - start + 1,
                          {"Content-Range": f"bytes {start}-{end}/{srv.size}"})
        else:
            self._headers(200, srv.size)

        remaining = end - start + 1
        with open(srv.file_path, "rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(srv.chunk_size, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)
                if srv.delay:
                    time.sleep(srv.delay)
