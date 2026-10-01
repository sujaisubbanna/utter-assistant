"""Reply-text parsing for the session D-Bus helpers (stdlib only).

This module holds the *text* half of :mod:`utter.context.backends.dbus`: the
GVariant recursive-descent parser used for ``gdbus call`` output, the simpler
``qdbus`` / ``dbus-send`` parsers, and :func:`parse_reply` which dispatches on
the tool. :func:`tool_kind` lives here because both call encoding (in
``dbus.py``) and reply parsing need to know which flavour of CLI tool is in
play.
"""
from __future__ import annotations

import os
from typing import Any


def tool_kind(tool: str) -> str:
    base = os.path.basename(tool or "")
    if base.startswith("qdbus"):
        return "qdbus"
    if base == "dbus-send":
        return "dbus-send"
    return "gdbus"


# --------------------------------------------------------------------------- #
# reply parsing
# --------------------------------------------------------------------------- #
class _GV:
    """Recursive-descent parser for GVariant text as printed by ``gdbus call``."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def _ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def parse(self) -> Any:
        self._ws()
        v = self.value()
        self._ws()
        return v

    def value(self) -> Any:
        self._ws()
        if self.i >= len(self.s):
            raise ValueError("unexpected end of GVariant text")
        c = self.s[self.i]
        if c == "(":
            return self._seq(")", tuple)
        if c == "[":
            return self._seq("]", list)
        if c == "{":
            return self._dict()
        if c == "<":
            self.i += 1
            v = self.value()
            self._ws()
            self._expect(">")
            return v
        if c in "'\"":
            return self._string(c)
        if c == "@":  # type annotation: @as [] / @a{sv} {}
            while self.i < len(self.s) and not self.s[self.i].isspace():
                self.i += 1
            return self.value()
        return self._word()

    def _expect(self, ch: str) -> None:
        if self.i >= len(self.s) or self.s[self.i] != ch:
            raise ValueError(f"expected {ch!r} at {self.i} in {self.s!r}")
        self.i += 1

    def _seq(self, close: str, factory):
        self.i += 1
        items: list = []
        while True:
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == close:
                self.i += 1
                return factory(items)
            items.append(self.value())
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def _dict(self) -> dict:
        self.i += 1
        out: dict = {}
        while True:
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            k = self.value()
            self._ws()
            self._expect(":")
            v = self.value()
            out[k] = v
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def _string(self, quote: str) -> str:
        self.i += 1
        out: list[str] = []
        esc = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "0": "\0"}
        while self.i < len(self.s):
            c = self.s[self.i]
            self.i += 1
            if c == "\\" and self.i < len(self.s):
                n = self.s[self.i]
                self.i += 1
                if n == "u" and self.i + 4 <= len(self.s):
                    out.append(chr(int(self.s[self.i:self.i + 4], 16)))
                    self.i += 4
                elif n == "U" and self.i + 8 <= len(self.s):
                    out.append(chr(int(self.s[self.i:self.i + 8], 16)))
                    self.i += 8
                else:
                    out.append(esc.get(n, n))
            elif c == quote:
                return "".join(out)
            else:
                out.append(c)
        raise ValueError("unterminated string in GVariant text")

    def _word(self) -> Any:
        start = self.i
        while self.i < len(self.s) and (self.s[self.i].isalnum() or self.s[self.i] in "._-+"):
            self.i += 1
        word = self.s[start:self.i]
        if not word:
            raise ValueError(f"unexpected {self.s[self.i]!r} at {self.i}")
        if word in ("true", "false"):
            return word == "true"
        if word in ("nothing",):
            return None
        if word == "just":
            return self.value()
        if word in ("byte", "int16", "uint16", "int32", "uint32", "int64", "uint64", "double", "handle", "objectpath", "signature"):
            return self.value()  # typed scalar: the value follows
        try:
            if word.startswith("0x"):
                return int(word, 16)
            return int(word)
        except ValueError:
            pass
        try:
            return float(word)
        except ValueError:
            return word


def parse_gvariant(text: str) -> Any:
    """Parse ``gdbus call`` output. A single-value tuple ``(x,)`` is unwrapped to ``x``."""
    v = _GV(text.strip()).parse()
    if isinstance(v, tuple) and len(v) == 1:
        return v[0]
    return v


def parse_qdbus(text: str) -> Any:
    """Parse ``qdbus`` output: a scalar, or one item per line for arrays."""
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    if len(lines) == 1:
        return _scalar(lines[0])
    return [_scalar(ln) for ln in lines]


def parse_dbus_send(text: str) -> Any:
    """Parse ``dbus-send --print-reply``: typed lines after the ``method return`` header."""
    values: list[Any] = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("method return") or ln.startswith("array ["):
            continue
        if ln.startswith("variant"):
            ln = ln[len("variant"):].strip()
        parts = ln.split(None, 1)
        if len(parts) != 2:
            continue
        kind, val = parts
        if kind == "string" or kind == "object path" or kind == "signature":
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                val = bytes(val[1:-1], "utf-8").decode("unicode_escape")
            values.append(val)
        elif kind == "boolean":
            values.append(val.strip() == "true")
        elif kind in ("int16", "uint16", "int32", "uint32", "int64", "uint64", "byte"):
            try:
                values.append(int(val.strip()))
            except ValueError:
                values.append(val.strip())
        elif kind == "double":
            try:
                values.append(float(val.strip()))
            except ValueError:
                values.append(val.strip())
    if len(values) == 1:
        return values[0]
    return values


def _scalar(s: str) -> Any:
    t = s.strip()
    if t in ("true", "false"):
        return t == "true"
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return s


def parse_reply(tool: str, text: str) -> Any:
    kind = tool_kind(tool)
    if kind == "qdbus":
        return parse_qdbus(text)
    if kind == "dbus-send":
        return parse_dbus_send(text)
    return parse_gvariant(text)


__all__ = ["tool_kind", "parse_gvariant", "parse_qdbus", "parse_dbus_send", "parse_reply"]
