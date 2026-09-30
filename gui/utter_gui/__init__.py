"""utter-gui — a native GTK4 + libadwaita settings window for utter.

The window is a *client*: it reads and writes configuration and asks the
``assistant`` CLI / runner to do the real work. No business logic lives here.
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__", "APP_ID", "APP_NAME"]

APP_ID = "org.utter.Settings"
APP_NAME = "utter"
