"""Vision tier (T3): screenshot -> UI-TARS grounding -> coordinates.

Public modules:
    screenshot : grim capture + niri logical geometry
    client     : HTTP client for the local vLLM UI-TARS server
"""
from __future__ import annotations

from . import client, screenshot

__all__ = ["client", "screenshot"]
