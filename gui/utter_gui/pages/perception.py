"""Perception — vision, accessibility and the provenance model."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class PerceptionPage(Page):
    id = "perception"
    title = "Perception"
    subtitle = "Vision, accessibility and provenance"
    icon = "camera-photo-symbolic"
    keywords = "perception vision screenshot accessibility a11y provenance trust uitars grounding"
    needs_runner = False

    def build_body(self):
        cfg = self.backend.config

        vision = widgets.group(
            "Vision (T3)",
            "Last resort: screenshot grounding, used only when rules and accessibility cannot resolve.",
        )
        self._enabled = widgets.switch_row("Enable vision")
        self._enabled.set_active(bool(cfg.get("vision", "enabled", True)))
        self._enabled.connect("notify::active", lambda r, _p: self._save(
            "vision", "enabled", bool(r.get_active())))
        vision.add(self._enabled)

        self._model = widgets.entry_row("Model", str(cfg.get("vision", "model", "uitars")))
        self._model.set_show_apply_button(True)
        self._model.connect("apply", lambda r: self._save("vision", "model", r.get_text()))
        vision.add(self._model)

        self._endpoint = widgets.entry_row("Endpoint", str(cfg.get("vision", "base_url", "")))
        self._endpoint.set_show_apply_button(True)
        self._endpoint.connect("apply", lambda r: self._save("vision", "base_url", r.get_text()))
        vision.add(self._endpoint)

        self._width = Adw.SpinRow.new_with_range(640, 3840, 64)
        self._width.set_title("Screenshot width")
        self._width.set_subtitle("UI-TARS recommends 1344 — the biggest latency lever")
        self._width.set_value(float(cfg.get("vision", "target_width", 1344)))
        self._width.connect("notify::value", lambda r, _p: self._debounced(
            "vision", "target_width", int(r.get_value())))
        vision.add(self._width)

        self._cuda = widgets.entry_row("GPU devices", str(cfg.get("vision", "cuda_visible_devices", "0")))
        self._cuda.set_show_apply_button(True)
        self._cuda.set_tooltip_text("CUDA_VISIBLE_DEVICES for the vision server")
        self._cuda.connect("apply", lambda r: self._save("vision", "cuda_visible_devices", r.get_text()))
        vision.add(self._cuda)
        self.add_group(vision)

        a11y = widgets.group(
            "Accessibility (T1)",
            "Reads the AT-SPI tree to find and invoke elements without pixels.",
        )
        self._a11y = widgets.switch_row("Use the accessibility tree")
        self._a11y.set_active(bool(cfg.get("perception", "accessibility_enabled", True)))
        self._a11y.connect("notify::active", lambda r, _p: self._save(
            "perception", "accessibility_enabled", bool(r.get_active())))
        a11y.add(self._a11y)
        self.add_group(a11y)

        trust = widgets.group(
            "Provenance & trust",
            "How untrusted content is kept from authoring actions.",
        )
        for title, body in (
            ("Tiers are tried cheapest first",
             "T0 app/window context, T1 accessibility, T2 keyboard shortcuts, T3 vision grounding."),
            ("Untrusted content selects, never authors",
             "Screen text, accessibility labels, OCR, window titles and the clipboard may only "
             "choose among precomputed candidates — they can never create an action's arguments."),
            ("Rejection code −32006",
             "An action built from untrusted input is refused with error −32006."),
        ):
            row = Adw.ExpanderRow(title=title)
            label = Gtk.Label(label=body, wrap=True, xalign=0)
            label.add_css_class("dim-label")
            label.set_margin_top(6)
            label.set_margin_bottom(12)
            label.set_margin_start(12)
            label.set_margin_end(12)
            holder = Adw.ActionRow()
            holder.set_child(label)
            row.add_row(holder)
            trust.add(row)
        self.add_group(trust)
        return self.page

    def _debounced(self, section: str, key: str, value) -> None:
        if not hasattr(self, "_deb"):
            self._deb = widgets.Debounce(500, lambda s, k, v: self._save(s, k, v))
        self._deb(section, key, value)

    def _save(self, section: str, key: str, value) -> None:
        try:
            self.backend.config.set(section, key, value)
            self.toast(f"Saved {section}.{key}")
        except OSError as exc:
            self.toast(f"Could not save: {exc}")
