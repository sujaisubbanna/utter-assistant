"""Context providers (T0): compositor state, clipboard, accessibility tree.

All providers are best-effort and must never raise into the daemon loop; they
return empty/None on failure so the router can degrade gracefully.
"""
from __future__ import annotations

from utter.context import clipboard, niri  # noqa: F401

# `compositor` (backend detection/selection) is imported lazily by callers so
# `python -m utter.context.compositor` runs without a double-import warning.
__all__ = ["niri", "clipboard", "atspi", "compositor", "textfields"]
