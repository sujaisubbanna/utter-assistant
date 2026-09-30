"""Plugins — negotiation, permissions and the doctor report."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

_OK_STATES = {"running", "ready", "active", "ok", "loaded", "negotiated"}
_BAD_STATES = {"failed", "error", "crashed"}


class PermissionDialog(Adw.Dialog):
    """Enforced vs advisory permission consent for one plugin."""

    def __init__(self, plugin: dict):
        super().__init__()
        self.set_title(f"Permissions — {plugin.get('id', 'plugin')}")
        self.set_content_width(520)
        self.set_content_height(520)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title=f"Permissions — {plugin.get('id', 'plugin')}",
            subtitle="What the runner lets this plugin do",
        ))
        body = widgets.group("Consent", "Enforced permissions are blocked by the runner; "
                                         "advisory ones cannot be enforced on this platform.")

        permissions = plugin.get("permissions") or []
        if not permissions:
            row = widgets.action_row("No permissions requested", "This plugin declares none.")
            row.add_prefix(Gtk.Image.new_from_icon_name("channel-secure-symbolic"))
            body.add(row)
        for perm in permissions:
            enforced = bool(perm.get("enforced"))
            name = str(perm.get("name") or "?")
            row = Adw.ActionRow(title=name.replace("_", " ").replace("-", " ").title())
            if enforced:
                row.set_subtitle("Enforced — the runner denies this without consent.")
            else:
                row.set_subtitle("Advisory — cannot be enforced here; treat as unsafe.")
            body.add(row)

        for cap in plugin.get("unknown_capabilities") or []:
            row = widgets.action_row(f"Unknown capability: {cap}",
                                     "The runner warns about this capability string.")
            body.add(row)
        for req in plugin.get("missing_requires") or []:
            row = widgets.action_row(f"Missing requirement: {req}",
                                     "The plugin cannot run without this requirement.")
            body.add(row)

        page = Adw.PreferencesPage()
        page.add(body)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(page)
        self.set_child(toolbar)


class PluginsPage(Page):
    id = "plugins"
    title = "Plugins"
    subtitle = "Negotiated capabilities and permissions"
    icon = "application-x-addon-symbolic"
    keywords = "plugins doctor negotiation permissions capabilities enabled disabled requires drift"
    needs_runner = True

    def __init__(self, window) -> None:
        super().__init__(window)
        self._disabled = set(
            str(x) for x in self.backend.config.get_list("plugins", "disabled")
        )
        self._report: dict | None = None
        self._plugin_rows: list = []
        self._dep_rows: list = []

    def build_body(self):
        runner = widgets.group("Runner", "Protocol and ABI negotiated with the runner.")
        self._doctor_button = widgets.AsyncButton("Run doctor", self.refresh)
        runner.set_header_suffix(self._doctor_button)
        self._version_row = widgets.action_row("Runner version", "—")
        self._version_dot = widgets.dot("busy")
        self._version_row.add_prefix(self._version_dot)
        runner.add(self._version_row)
        self._proto_row = widgets.action_row("Protocol / ABI", "—")
        runner.add(self._proto_row)
        self._ok_row = widgets.action_row("Doctor status", "—")
        self._ok_dot = widgets.dot("busy")
        self._ok_row.add_prefix(self._ok_dot)
        runner.add(self._ok_row)
        restart = widgets.action_row("Apply changes", "Restart the runner to pick up enable/disable")
        restart.add_suffix(widgets.AsyncButton("Restart runner", self._restart_runner))
        runner.add(restart)
        self.add_group(runner)

        self._plugins_group = widgets.group(
            "Plugins",
            "Toggle enable/disable (saved to config, applied on runner restart).",
        )
        loading = widgets.action_row("Loading…", " ")
        self._plugins_group.add(loading)
        self._plugin_rows.append(loading)
        self.add_group(self._plugins_group)

        deps = widgets.group("Dependencies", "External tools probed by doctor.")
        self._deps_group = deps
        dep_loading = widgets.action_row("Loading…", " ")
        deps.add(dep_loading)
        self._dep_rows.append(dep_loading)
        self.add_group(deps)
        return self.page

    # -- data ------------------------------------------------------------ #
    def refresh(self) -> None:
        self._doctor_button.set_busy(True)
        proc = self.backend.assistant("doctor", "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            self._doctor_button.set_busy(False)
            report = self._parse(out) or {"ok": False, "plugins": [], "connected": False,
                                          "error": (err or "no output").strip()}
            self._report = report
            self._render(report)

        proc.communicate(done)

    def _parse(self, out: str) -> dict | None:
        from .. import backend as be
        return be.parse_json(out)

    def _render(self, report: dict) -> None:
        connected = bool(report.get("connected"))
        runner = report.get("runner") or {}
        self._version_dot.set_state("ok" if connected else "unknown")
        self._version_row.set_subtitle(str(runner.get("version") or "—"))
        self._proto_row.set_subtitle(
            f"protocol {runner.get('protocol', '?')} · abi {runner.get('abi', '?')}"
        )
        ok = bool(report.get("ok"))
        self._ok_dot.set_state("ok" if ok else "warn")
        message = "all checks passed" if ok else (report.get("error") or "issues found")
        drift = report.get("drift") or []
        if drift:
            message += f" · {len(drift)} drift"
        self._ok_row.set_subtitle(widgets.esc(message))

        self._render_plugins(connected, report)
        self._render_deps(report.get("deps") or {})

    def _render_plugins(self, connected: bool, report: dict) -> None:
        widgets.clear_group(self._plugins_group, self._plugin_rows)
        plugins = report.get("plugins") or []
        if not connected:
            row = widgets.action_row(
                "Runner not reachable",
                report.get("error") or "Start utter-runner, then run doctor again.",
            )
            row.add_prefix(Gtk.Image.new_from_icon_name("network-offline-symbolic"))
            self._plugins_group.add(row)
            self._plugin_rows.append(row)
            return
        if not plugins:
            row = widgets.action_row("No plugins loaded", "The runner reported an empty plugin set.")
            row.add_prefix(Gtk.Image.new_from_icon_name("application-x-addon-symbolic"))
            self._plugins_group.add(row)
            self._plugin_rows.append(row)
            return
        for plugin in plugins:
            row = self._plugin_row(plugin)
            self._plugins_group.add(row)
            self._plugin_rows.append(row)

    def _plugin_row(self, plugin: dict) -> Adw.ExpanderRow:
        pid = str(plugin.get("id") or "?")
        status = str(plugin.get("status") or "")
        row = Adw.ExpanderRow(title=widgets.esc(pid))
        row.set_subtitle(widgets.esc(
            f"{plugin.get('kind', '?')} · {status or 'unknown'} · epoch {plugin.get('epoch', '?')}"
        ))
        dot = widgets.dot(self._state_for(status))
        row.add_prefix(dot)

        toggle = Gtk.Switch()
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_active(pid not in self._disabled)
        toggle.set_tooltip_text("Enable / disable on next runner restart")
        toggle.connect("state-set", self._on_toggle, pid)
        row.add_suffix(toggle)

        negotiated = plugin.get("negotiated") or {}
        neg = Adw.ActionRow(title="Negotiated")
        neg.set_subtitle(f"protocol {negotiated.get('protocol', '?')} · abi {negotiated.get('abi', '?')}")
        row.add_row(neg)

        unknown = plugin.get("unknown_capabilities") or []
        if unknown:
            item = Adw.ActionRow(title="Unknown capabilities",
                                 subtitle=widgets.esc(", ".join(map(str, unknown))))
            item.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            row.add_row(item)
        missing = plugin.get("missing_requires") or []
        if missing:
            item = Adw.ActionRow(title="Missing requirements",
                                 subtitle=widgets.esc(", ".join(map(str, missing))))
            item.add_prefix(Gtk.Image.new_from_icon_name("dialog-error-symbolic"))
            row.add_row(item)
        if plugin.get("error"):
            item = Adw.ActionRow(title="Error", subtitle=widgets.esc(plugin["error"]))
            item.add_prefix(Gtk.Image.new_from_icon_name("dialog-error-symbolic"))
            row.add_row(item)

        perms = plugin.get("permissions") or []
        enforced = sum(1 for p in perms if p.get("enforced"))
        advisory = len(perms) - enforced
        perm_row = Adw.ActionRow(
            title="Permissions",
            subtitle=f"{enforced} enforced · {advisory} advisory",
        )
        perm_row.add_suffix(widgets.AsyncButton(
            "Review", lambda p=plugin: PermissionDialog(p).present(self.window)))
        row.add_row(perm_row)
        return row

    def _state_for(self, status: str) -> str:
        status = (status or "").lower()
        if status in _OK_STATES:
            return "ok"
        if status in _BAD_STATES:
            return "failed"
        return "inactive"

    def _on_toggle(self, switch, active: bool, pid: str) -> bool:
        # Return False so the switch still updates; persist intent, apply on restart.
        if pid in self._disabled and active:
            self._disabled.discard(pid)
        elif not active:
            self._disabled.add(pid)
        try:
            self.backend.config.set("plugins", "disabled", sorted(self._disabled))
            state = "enabled" if active else "disabled"
            self.toast(f"{pid} {state} — restart the runner to apply")
        except OSError as exc:
            self.toast(f"Could not save: {exc}")
        return False

    def _restart_runner(self) -> None:
        proc = self.backend.systemctl("restart", "utter-runner")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            if rc == 0:
                self.toast("Runner restarted")
            else:
                self.toast(f"Restart failed: {(err or out).strip()[:120]}")
            self.refresh()

        proc.communicate(done)

    def _render_deps(self, deps: dict) -> None:
        widgets.clear_group(self._deps_group, self._dep_rows)
        if not deps:
            row = widgets.action_row("No dependency data", "doctor returned none")
            self._deps_group.add(row)
            self._dep_rows.append(row)
            return
        for name in sorted(deps):
            present = bool(deps[name])
            label = name.replace("_", " ").title()
            row = widgets.action_row(label, "available" if present else "missing")
            row.add_prefix(widgets.dot("ok" if present else "failed"))
            self._deps_group.add(row)
            self._dep_rows.append(row)

    def on_runner_state(self, connected: bool) -> None:
        if connected:
            self.refresh()

    def on_show(self) -> None:
        self.refresh()
