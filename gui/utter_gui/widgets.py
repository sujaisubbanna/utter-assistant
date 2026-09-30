"""Shared widgets and small UI builders used by every page.

Deliberately small: plain libadwaita rows, one tiny status dot, and a busy
button. Colour comes from the theme (libadwaita + the matugen palette), never
from values baked in here.
"""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

# --------------------------------------------------------------------------- #
# status dot — a single small circle, coloured by the theme via CSS classes
# --------------------------------------------------------------------------- #
_DOT_STATES = {
    "ok": "ok",
    "active": "ok",
    "running": "ok",
    "ready": "ok",
    "failed": "error",
    "error": "error",
    "warn": "warn",
    "busy": "busy",
}


def _dot_class(state: str) -> str:
    return _DOT_STATES.get((state or "").lower(), "idle")


class Dot(Gtk.Box):
    """A small status dot. Its colour is a CSS class (see ``style.css``)."""

    def __init__(self, state: str = "unknown", size: int = 8):
        super().__init__()
        self._state: Optional[str] = None
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.add_css_class("status-dot")
        self.set_state(state)

    def set_state(self, state: str) -> None:
        name = _dot_class(state)
        if name == self._state:
            return
        if self._state:
            self.remove_css_class(f"dot-{self._state}")
        self._state = name
        self.add_css_class(f"dot-{name}")


def dot(state: str) -> Dot:
    return Dot(state)


# --------------------------------------------------------------------------- #
# buttons
# --------------------------------------------------------------------------- #
class AsyncButton(Gtk.Button):
    """A button that swaps its label for a spinner while work is in flight."""

    def __init__(self, label: str, on_click: Optional[Callable[[], None]] = None):
        super().__init__()
        self._box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._spinner = Adw.Spinner()
        self._spinner.set_visible(False)
        self._label = Gtk.Label(label=label)
        self._box.append(self._spinner)
        self._box.append(self._label)
        self.set_child(self._box)
        if on_click is not None:
            self.connect("clicked", lambda _b: on_click())

    def set_busy(self, busy: bool) -> None:
        self._spinner.set_visible(busy)
        self._label.set_visible(not busy)
        self.set_sensitive(not busy)

    def set_label_text(self, text: str) -> None:
        self._label.set_label(text)


class Debounce:
    """Coalesce rapid calls (sliders) into one trailing invocation."""

    def __init__(self, ms: int, func: Callable[..., None]):
        self._ms = ms
        self._func = func
        self._src = 0

    def __call__(self, *args) -> None:
        if self._src:
            GLib.source_remove(self._src)
        self._src = GLib.timeout_add(self._ms, self._fire, args)

    def _fire(self, args):
        self._src = 0
        self._func(*args)
        return False


# --------------------------------------------------------------------------- #
# labels & headers
# --------------------------------------------------------------------------- #
def esc(text) -> str:
    """Escape text for Adw widgets (titles/subtitles render Pango markup)."""
    return GLib.markup_escape_text(str(text))


def badge(text: str, kind: str = "neutral") -> Gtk.Label:
    """Quiet inline status text — no pill. Accents only for warn/error."""
    label = Gtk.Label(label=text)
    label.add_css_class("status-text")
    if kind in ("warn", "advisory"):
        label.add_css_class("status-warn")
    elif kind in ("error", "missing"):
        label.add_css_class("status-error")
    label.set_valign(Gtk.Align.CENTER)
    return label


def header_title(title: str, subtitle: str) -> Adw.WindowTitle:
    return Adw.WindowTitle(title=esc(title), subtitle=esc(subtitle))


def mono_view() -> Gtk.TextView:
    view = Gtk.TextView()
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_monospace(True)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.set_left_margin(10)
    view.set_right_margin(10)
    return view


# --------------------------------------------------------------------------- #
# rows
# --------------------------------------------------------------------------- #
def action_row(title: str, subtitle: str = "", icon: Optional[str] = None) -> Adw.ActionRow:
    row = Adw.ActionRow(title=esc(title))
    if subtitle:
        row.set_subtitle(esc(subtitle))
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


def switch_row(title: str, subtitle: str = "") -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=esc(title))
    if subtitle:
        row.set_subtitle(esc(subtitle))
    return row


def combo_row(title: str, subtitle: str = "") -> Adw.ComboRow:
    row = Adw.ComboRow(title=esc(title))
    if subtitle:
        row.set_subtitle(esc(subtitle))
    return row


def slider_row(
    title: str, subtitle: str, lower: float, upper: float, step: float,
    value: float, on_change: Callable[[float], None],
) -> tuple[Adw.ActionRow, Gtk.Scale]:
    row = Adw.ActionRow(title=esc(title), subtitle=esc(subtitle))
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
    scale.set_value(value)
    scale.set_digits(2 if step < 1 else 0)
    scale.set_size_request(210, -1)
    scale.set_draw_value(True)
    scale.set_valign(Gtk.Align.CENTER)
    scale.set_value_pos(Gtk.PositionType.RIGHT)
    scale.connect("value-changed", lambda s: on_change(s.get_value()))
    row.add_suffix(scale)
    row.set_activatable_widget(scale)
    return row, scale


def entry_row(title: str, text: str = "", subtitle: str = "") -> Adw.EntryRow:
    row = Adw.EntryRow(title=esc(title))
    row.set_text(text)
    if subtitle:
        row.set_tooltip_text(subtitle)
    return row


def group(title: str = "", description: str = "") -> Adw.PreferencesGroup:
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(esc(title))
    if description:
        g.set_description(esc(description))
    return g


def set_string_list(row: Adw.ComboRow, labels: list[str]) -> None:
    row.set_model(Gtk.StringList.new(labels))


def clear_group(group: Adw.PreferencesGroup, rows: list) -> None:
    """Remove tracked rows from a preferences group without relying on iteration."""
    for row in list(rows):
        try:
            group.remove(row)
        except Exception:  # noqa: BLE001
            pass
    rows.clear()
