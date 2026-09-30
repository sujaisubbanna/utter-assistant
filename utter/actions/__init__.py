"""Action executors (T2): app launch, URL open, keyboard, mouse, AT-SPI actions.

Every function returns `types.ActionResult` and must use list args (no shell).
"""
from __future__ import annotations

from utter.actions import a11y_action, keyboard, launch, mouse  # noqa: F401

__all__ = ["launch", "keyboard", "mouse", "a11y_action"]
