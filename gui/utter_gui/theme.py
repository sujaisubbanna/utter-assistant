"""Deterministic matugen theming for the GTK4 settings app.

libadwaita can pick up a matugen palette from ``~/.config/gtk-4.0/gtk.css``, but
it only reloads when the GTK settings portal emits a change and that watcher is
optional. To make re-theming deterministic the app installs the matugen-generated
palette itself: a :class:`Gtk.CssProvider` at user priority that is re-parsed by
an app-owned :class:`Gio.FileMonitor`.

The palette path defaults to ``~/.local/share/utter/colors.css`` and can be
overridden with ``UTTER_THEME_CSS`` (useful for tests).

Everything here is best-effort: a missing or malformed palette is a no-op and no
exception ever escapes to the caller.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

__all__ = ["ThemeManager", "install_theme", "DEFAULT_THEME_CSS", "theme_path"]

DEFAULT_THEME_CSS = "~/.local/share/utter/colors.css"

# One above the user priority (800): our palette must beat libadwaita's own
# gtk.css import while still allowing per-user overrides if anyone needs them.
_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_USER + 1


def theme_path() -> Path:
    """Return the palette path, honouring ``UTTER_THEME_CSS``."""
    raw = os.environ.get("UTTER_THEME_CSS") or DEFAULT_THEME_CSS
    return Path(os.path.expanduser(raw))


class ThemeManager:
    """Owns the palette :class:`Gtk.CssProvider` and its file monitor."""

    def __init__(self, display: Optional[Gdk.Display] = None, path=None) -> None:
        self._path = Path(os.path.expanduser(str(path))) if path else theme_path()
        self._display: Optional[Gdk.Display] = display
        self._provider: Optional[Gtk.CssProvider] = None
        self._monitor: Optional[Gio.FileMonitor] = None
        self._installed = False
        self._idle_id = 0
        self.install()
        self._start_monitor()

    # -- public API ------------------------------------------------------ #
    @property
    def path(self) -> Path:
        return self._path

    @property
    def installed(self) -> bool:
        """True once a palette has been parsed and added to the display."""
        return self._installed

    def install(self) -> bool:
        """Parse the palette (if present) and install it. Never raises."""
        if not self._path.exists():
            return False
        try:
            provider = Gtk.CssProvider()
            errors: list[Exception] = []

            def _on_parse_error(_provider, _section, error) -> None:
                errors.append(error)

            provider.connect("parsing-error", _on_parse_error)
            provider.load_from_path(str(self._path))
        except Exception:  # noqa: BLE001 - malformed CSS must not crash the app
            return False
        if errors:
            # GTK parses what it can and reports the rest here; don't install a
            # half-valid palette.
            return False

        display = self._display or Gdk.Display.get_default()
        if display is None:
            return False
        try:
            Gtk.StyleContext.add_provider_for_display(display, provider, _PRIORITY)
        except Exception:  # noqa: BLE001
            return False

        # Swap in the fresh provider and drop the stale one so the restyle is
        # guaranteed even if re-parsing the same provider were a no-op.
        old, self._provider = self._provider, provider
        if old is not None:
            try:
                Gtk.StyleContext.remove_provider_for_display(display, old)
            except Exception:  # noqa: BLE001
                pass
        self._display = display
        self._installed = True
        return True

    def apply_to_app(self, app=None) -> bool:
        """Install (or re-install) the palette; safe to call at startup."""
        if self._display is None:
            self._display = Gdk.Display.get_default()
        return self.install()

    # -- file watching --------------------------------------------------- #
    def _start_monitor(self) -> None:
        try:
            gfile = Gio.File.new_for_path(str(self._path))
            monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        except Exception:  # noqa: BLE001 - no monitor is still okay
            return
        monitor.connect("changed", self._on_changed)
        self._monitor = monitor  # keep a reference alive

    def _on_changed(self, *_args) -> None:
        if self._idle_id:
            return
        try:
            self._idle_id = GLib.idle_add(self._reload_idle)
        except Exception:  # noqa: BLE001
            self._idle_id = 0

    def _reload_idle(self) -> bool:
        self._idle_id = 0
        self.install()
        return GLib.SOURCE_REMOVE


def install_theme(display: Optional[Gdk.Display] = None) -> ThemeManager:
    """Create a :class:`ThemeManager` and return it (keep the ref alive)."""
    return ThemeManager(display=display)
