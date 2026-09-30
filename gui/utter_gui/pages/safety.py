"""Safety — confirmation policy, dangerous operations and allow-lists."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

_DANGEROUS = {
    "action.terminal": ("Allow terminal commands", "Types and runs shell commands (high risk)"),
    "action.input": ("Allow input injection", "Synthetic keyboard and mouse events (high risk)"),
}


class SafetyPage(Page):
    id = "safety"
    title = "Safety"
    subtitle = "Confirmation policy and dangerous operations"
    icon = "security-high-symbolic"
    keywords = "safety confirm confirmation policy terminal input allowlist blocklist dangerous actions"
    needs_runner = False

    def __init__(self, window) -> None:
        super().__init__(window)
        self._guard = False

    def build_body(self):
        cfg = self.backend.config

        self.danger_banner = Adw.Banner(revealed=False)
        self.danger_banner.set_title("Dangerous operations are enabled")
        self.danger_banner.set_button_label("Review")
        self.danger_banner.connect("button-clicked", lambda _b: self.toast(
            "Disable the dangerous toggles below to reduce risk"))

        confirm = widgets.group(
            "Confirmation policy",
            "Consequential actions wait for an explicit confirmation.",
        )
        self._confirm_switch = widgets.switch_row("Confirm consequential actions")
        self._confirm_switch.set_active(bool(cfg.get("actions", "confirm_enabled", True)))
        self._confirm_switch.connect("notify::active", lambda r, _p: self._save(
            "actions", "confirm_enabled", bool(r.get_active())))
        confirm.add(self._confirm_switch)

        phrases = cfg.get_list("actions", "require_confirm")
        self._phrases_row = widgets.entry_row("Require confirmation for", ", ".join(map(str, phrases)))
        self._phrases_row.set_show_apply_button(True)
        self._phrases_row.set_tooltip_text("Comma-separated verbs or phrases")
        self._phrases_row.connect("apply", lambda r: self._save(
            "actions", "require_confirm", self._split(r.get_text())))
        confirm.add(self._phrases_row)
        self.add_group(confirm)

        dangerous = widgets.group(
            "Dangerous operations",
            "Off by default and never enabled implicitly.",
        )
        self._op_switches: dict[str, Gtk.Switch] = {}
        for op, (title, subtitle) in _DANGEROUS.items():
            row = widgets.switch_row(title, subtitle)
            row.set_active(op in self._enabled_ops())
            row.connect("notify::active", self._on_op_active, op)
            dangerous.add(row)
            self._op_switches[op] = row
        self.add_group(dangerous)

        lists = widgets.group("Allow-lists", "Fine-grained limits on what may run.")
        self._allow_row = widgets.entry_row(
            "Allowed terminal commands",
            ", ".join(map(str, cfg.get_list("policy", "allow_commands"))))
        self._allow_row.set_show_apply_button(True)
        self._allow_row.set_tooltip_text("Comma-separated commands; empty means any")
        self._allow_row.connect("apply", lambda r: self._save(
            "policy", "allow_commands", self._split(r.get_text())))
        lists.add(self._allow_row)

        self._block_row = widgets.entry_row(
            "Blocked phrases",
            ", ".join(map(str, cfg.get_list("policy", "blocked_phrases"))))
        self._block_row.set_show_apply_button(True)
        self._block_row.connect("apply", lambda r: self._save(
            "policy", "blocked_phrases", self._split(r.get_text())))
        lists.add(self._block_row)

        self._click_row = Adw.SpinRow.new_with_range(0, 1000, 5)
        self._click_row.set_title("Click duration (ms)")
        self._click_row.set_value(float(cfg.get("actions", "click_duration_ms", 40)))
        self._click_row.connect("notify::value", lambda r, _p: self._debounced(
            "actions", "click_duration_ms", int(r.get_value())))
        lists.add(self._click_row)
        self.add_group(lists)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.danger_banner)
        box.append(self.page)
        self._refresh_banner()
        return box

    # -- helpers --------------------------------------------------------- #
    def _split(self, text: str) -> list[str]:
        return [part.strip() for part in text.split(",") if part.strip()]

    def _enabled_ops(self) -> list[str]:
        return [str(x) for x in self.backend.config.get_list("policy", "enabled_ops")]

    def _save(self, section: str, key: str, value) -> None:
        try:
            self.backend.config.set(section, key, value)
            self.toast(f"Saved {section}.{key}")
            self._refresh_banner()
        except OSError as exc:
            self.toast(f"Could not save: {exc}")

    def _debounced(self, section: str, key: str, value) -> None:
        if not hasattr(self, "_deb"):
            self._deb = widgets.Debounce(500, self._save)
        self._deb(section, key, value)

    def _refresh_banner(self) -> None:
        self.danger_banner.set_revealed(bool(self._enabled_ops()))

    def _on_op_active(self, row, _param, op: str) -> None:
        if self._guard:
            return
        active = bool(row.get_active())
        currently = op in self._enabled_ops()
        if active and not currently:
            # revert right away, ask first
            self._guard = True
            row.set_active(False)
            self._guard = False
            self._confirm_enable(op)
        elif not active and currently:
            self._set_op(op, False)

    def _confirm_enable(self, op: str) -> None:
        dialog = Adw.AlertDialog(
            heading=f"Enable {op}?",
            body="This lets the assistant perform high-risk desktop actions. "
                 "Only enable it if you understand the risk.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("enable", "Enable")
        dialog.set_response_appearance("enable", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_d, response: str) -> None:
            if response == "enable":
                self._set_op(op, True)

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def _set_op(self, op: str, on: bool) -> None:
        ops = self._enabled_ops()
        if on and op not in ops:
            ops.append(op)
        elif not on and op in ops:
            ops = [x for x in ops if x != op]
        try:
            self.backend.config.set("policy", "enabled_ops", sorted(ops))
        except OSError as exc:
            self.toast(f"Could not save: {exc}")
            return
        self._guard = True
        self._op_switches[op].set_active(on)
        self._guard = False
        self._refresh_banner()
        self.toast(f"{op} {'enabled' if on else 'disabled'}")
