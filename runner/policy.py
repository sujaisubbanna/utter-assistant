"""Provenance enforcement and the action op registry (TRUST.md §1-§4).

Two provenance classes:

* ``user``   — the user's utterance / explicit input. Trusted.
* ``screen`` — a11y / OCR / clipboard / titles / web. Untrusted.

Untrusted content may **select** among precomputed candidates; it may never
**author** concrete ``args``. A screen-derived concrete argument is rejected
with ``-32006``. Consequential ops drive an argument-bearing confirmation
through ``host.confirm`` and are re-validated afterwards (TOCTOU).
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .rpc import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PERMISSION_DENIED,
    UNTRUSTED_ARG,
    RpcError,
)


class Provenance(str, enum.Enum):
    USER = "user"
    SCREEN = "screen"

    @classmethod
    def parse(cls, value: Any) -> "Provenance":
        if isinstance(value, cls):
            return value
        try:
            return cls(value or "user")
        except ValueError:
            raise RpcError(INVALID_PARAMS, f"bad provenance: {value!r}") from None


@dataclass(frozen=True)
class OpPolicy:
    op: str
    enabled: bool = True
    needs_confirm: bool = False
    schemes: tuple[str, ...] = ()
    select_only: bool = True
    concrete_args: tuple[str, ...] = ()


class PolicyError(RpcError):
    """Rejected by policy; carries a PROTOCOL.md error code."""


class ConfirmationRequired(Exception):
    """Raised when an op needs (argument-bearing) confirmation."""

    def __init__(self, op: str, args: dict, provenance: Provenance, summary: str):
        super().__init__(summary)
        self.op = op
        self.arguments = args
        self.provenance = provenance
        self.summary = summary


# op registry: action.terminal is OFF by default; open_url schemes restricted.
DEFAULT_OPS: dict[str, OpPolicy] = {
    "ensure_url": OpPolicy("ensure_url", schemes=("http", "https", "mailto"), concrete_args=("url",)),
    "open_url": OpPolicy("open_url", schemes=("http", "https", "mailto"), concrete_args=("url",)),
    "terminal": OpPolicy("terminal", enabled=False, needs_confirm=True, concrete_args=("command", "argv")),
    "input": OpPolicy("input", enabled=False, needs_confirm=True,
                      concrete_args=("text", "key", "chord", "action", "button")),
    "niri": OpPolicy("niri", concrete_args=("app_id", "window_id", "command")),
    "launch_app": OpPolicy("launch_app", concrete_args=("app_id", "command")),
}


def _norm(op: str) -> str:
    op = str(op)
    return op[len("action."):] if op.startswith("action.") else op


class Policy:
    def __init__(
        self,
        ops: dict[str, OpPolicy] | None = None,
        *,
        enabled_ops: list[str] | None = None,
        disabled_ops: list[str] | None = None,
    ):
        self.ops = dict(DEFAULT_OPS)
        if ops:
            self.ops.update({_norm(k): v for k, v in ops.items()})
        for op in enabled_ops or ():
            self._set_enabled(_norm(op), True)
        for op in disabled_ops or ():
            self._set_enabled(_norm(op), False)

    def _set_enabled(self, op: str, enabled: bool) -> None:
        pol = self.ops.get(op)
        if pol is None:
            self.ops[op] = OpPolicy(op, enabled=enabled)
        else:
            self.ops[op] = dataclasses.replace(pol, enabled=enabled)

    def describe(self) -> list[dict]:
        return [
            {"op": p.op, "enabled": p.enabled, "needs_confirm": p.needs_confirm,
             "schemes": list(p.schemes)}
            for p in self.ops.values()
        ]

    def validate(self, op: str, args: Any, provenance: Provenance, *, confirmed: bool = False) -> None:
        prov = Provenance.parse(provenance)
        pol = self.ops.get(_norm(op))
        if pol is None:
            raise PolicyError(METHOD_NOT_FOUND, f"unknown action op {op!r}")
        args = args if isinstance(args, dict) else {}

        # (a) untrusted content may select, never author concrete args
        if prov is Provenance.SCREEN and pol.select_only:
            concrete = [k for k in pol.concrete_args if k in args]
            if concrete:
                raise PolicyError(
                    UNTRUSTED_ARG,
                    f"untrusted ({prov.value}) args rejected for op {pol.op!r}: "
                    + ", ".join(concrete),
                    {"op": pol.op, "fields": concrete},
                )

        # (b) op registry / enablement
        if not pol.enabled:
            raise PolicyError(PERMISSION_DENIED, f"op {pol.op!r} is disabled by policy")

        self._validate_args(pol, args)

        # (c) consequential ops need argument-bearing confirmation
        if pol.needs_confirm and not confirmed:
            raise ConfirmationRequired(pol.op, dict(args), prov, self._summary(pol.op, args))

    @staticmethod
    def _validate_args(pol: OpPolicy, args: dict) -> None:
        if pol.schemes:
            url = args.get("url")
            if not isinstance(url, str) or not url:
                raise PolicyError(INVALID_PARAMS, f"{pol.op} requires a string 'url'")
            try:
                scheme = urlparse(url).scheme.lower()
            except ValueError:
                scheme = ""
            if scheme not in pol.schemes:
                raise PolicyError(
                    PERMISSION_DENIED,
                    f"url scheme {scheme!r} not allowed for {pol.op!r}",
                    {"allowed": list(pol.schemes)},
                )

    @staticmethod
    def _summary(op: str, args: dict) -> str:
        if op in ("open_url", "ensure_url"):
            return f"Open URL: {args.get('url')}"
        if op == "terminal":
            return f"Run command: {args.get('command') or args.get('argv')}"
        if op == "input":
            return f"Inject input: {args.get('text') or args.get('key') or args.get('chord')}"
        return f"{op}: {args}"
