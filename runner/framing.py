"""Content-Length framing over an async stream (LSP base protocol).

Wire format::

    Content-Length: <bytes>\\r\\n\\r\\n<utf-8 json>

Binary-safe: the header length is a byte count and the body is decoded as
UTF-8. Malformed frames raise :class:`FramingError` (a typed error).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

HEADER_SEP = b"\r\n\r\n"
MAX_HEADER_BYTES = 8192


class FramingError(Exception):
    """Malformed frame: bad/missing Content-Length, truncated body, bad JSON."""


async def read_message(reader: asyncio.StreamReader) -> Any:
    """Read one framed JSON message from ``reader``.

    Raises :class:`FramingError` for malformed frames and
    ``asyncio.IncompleteReadError`` on a clean EOF before a header.
    """
    try:
        header = await reader.readuntil(HEADER_SEP)
    except asyncio.LimitOverrunError as exc:
        raise FramingError("frame header exceeds limit") from exc
    if len(header) > MAX_HEADER_BYTES:
        raise FramingError("frame header exceeds limit")

    length: int | None = None
    for line in header[: -len(HEADER_SEP)].split(b"\r\n"):
        if not line:
            continue
        name, sep, value = line.partition(b":")
        if not sep:
            raise FramingError(f"malformed header line: {line!r}")
        if name.strip().lower() == b"content-length":
            try:
                length = int(value.strip())
            except ValueError as exc:
                raise FramingError(f"bad Content-Length: {value!r}") from exc
    if length is None:
        raise FramingError("frame header missing Content-Length")
    if length < 0:
        raise FramingError(f"negative Content-Length: {length}")

    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise FramingError("truncated frame body") from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FramingError(f"invalid JSON body: {exc}") from exc


def encode(obj: Any) -> bytes:
    """Encode one Content-Length framed message as bytes."""
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


async def write_message(writer: Any, obj: Any) -> None:
    """Write one framed JSON message to ``writer`` (an ``asyncio`` StreamWriter)."""
    writer.write(encode(obj))
    await writer.drain()
