"""General / Services — autostart, service control and live active-state."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import backend as be  # noqa: E402
from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

_POLL_MS = 4000


class GeneralPage(Page):
    id = "general"
    title = "General"
    subtitle = "Startup, services and connection"
    icon = "preferences-system-symbolic"
    keywords = "general services startup autostart systemd runner bridge vision planner audio"
    needs_runner = False

    def __init__(self, window) -> None:
        super().__init__(window)
        self._timer = 0
        self._busy = False
        self._rows: dict[str, dict] = {}
        self._autostart_row: Adw.SwitchRow | None = None
        self._conn_row: Adw.ActionRow | None = None
        self._plugin_row: Adw.ActionRow | None = None

    # -- layout ---------------------------------------------------------- #
    def build_body(self):
        startup = widgets.group("Startup")
        self._autostart_row = widgets.switch_row(
            "Start on login",
            "Enable the utter-runner user service.",
        )
        self._autostart_row.connect("notify::active", self._on_autostart_toggled)
        self._autostart_guard = False
        startup.add(self._autostart_row)

        self._trigger_combo = widgets.combo_row("Trigger mode")
        self._trigger_combo.set_subtitle("hotkey = own evdev push-to-talk · bridge = reuse vocalinux")
        widgets.set_string_list(self._trigger_combo, ["hotkey", "bridge"])
        current_trigger = str(self.backend.config.get("general", "trigger", "hotkey"))
        self._trigger_combo.set_selected(1 if current_trigger == "bridge" else 0)
        self._trigger_combo.connect("notify::selected", self._on_trigger_changed)
        startup.add(self._trigger_combo)
        self.add_group(startup)

        services = widgets.group(
            "Services",
            "User units that run the assistant. State updates live.",
        )
        for unit, label, desc in be.SERVICES:
            row = Adw.ActionRow(title=label, subtitle=desc)
            dot = widgets.dot("unknown")
            row.add_prefix(dot)
            menu_button = self._service_menu(unit)
            row.add_suffix(menu_button)
            services.add(row)
            self._rows[unit] = {"row": row, "dot": dot, "menu": menu_button}
        self.add_group(services)

        connection = widgets.group("Connection")
        self._conn_row = widgets.action_row("Runner socket", "checking…")
        self._conn_dot = widgets.dot("busy")
        self._conn_row.add_prefix(self._conn_dot)
        connection.add(self._conn_row)
        self._plugin_row = widgets.action_row("Plugins", "—")
        connection.add(self._plugin_row)
        self.add_group(connection)
        return self.page

    def _service_menu(self, unit: str) -> Gtk.MenuButton:
        actions = Gio.SimpleActionGroup()
        handlers = {
            "start": lambda: self._systemctl("start", unit),
            "stop": lambda: self._systemctl("stop", unit),
            "restart": lambda: self._systemctl("restart", unit),
            "logs": lambda: self.window.show_page("diagnostics"),
        }
        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            actions.add_action(action)
        menu = Gio.Menu()
        menu.append("Start", "svc.start")
        menu.append("Stop", "svc.stop")
        menu.append("Restart", "svc.restart")
        menu.append("Show logs", "svc.logs")
        button = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu)
        button.add_css_class("flat")
        button.insert_action_group("svc", actions)
        button.set_tooltip_text(f"Control {unit}")
        return button

    # -- data ------------------------------------------------------------ #
    def refresh(self) -> None:
        self._refresh_services()
        self._refresh_autostart()
        self._refresh_connection()

    def on_show(self) -> None:
        self.refresh()
        if not self._timer:
            self._timer = GLib.timeout_add(_POLL_MS, self._tick)

    def on_hide(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self) -> bool:
        self.refresh()
        return True

    def _refresh_services(self) -> None:
        if self._busy:
            return
        self._busy = True
        proc = self.backend.systemctl(
            "show", *be.SERVICE_UNITS,
            "--property=Id,LoadState,ActiveState,SubState,UnitFileState",
        )
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            self._busy = False
            if rc != 0:
                return
            parsed = be.parse_systemctl_show(out)
            for unit, refs in self._rows.items():
                props = parsed.get(unit, {})
                load = props.get("LoadState", "")
                active = props.get("ActiveState", "")
                sub = props.get("SubState", "")
                unit_file = props.get("UnitFileState", "")
                if load in ("not-found", "", "masked"):
                    state, text = "unknown", "not installed"
                elif active == "active":
                    state, text = "active", f"active ({sub})" if sub else "active"
                elif active == "failed":
                    state, text = "failed", "failed"
                elif active == "activating":
                    state, text = "busy", "starting…"
                else:
                    state, text = "inactive", active or "inactive"
                refs["dot"].set_state(state)
                refs["menu"].set_sensitive(load != "not-found")
                refs["row"].set_subtitle(text)
                if unit_file:
                    refs["row"].set_tooltip_text(f"{unit} · UnitFileState={unit_file}")

        proc.communicate(done)

    def _refresh_autostart(self) -> None:
        proc = self.backend.systemctl("is-enabled", "utter-runner")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            state = (out or err).strip()
            self._autostart_guard = True
            self._autostart_row.set_active(state == "enabled")
            self._autostart_guard = False
            if state == "enabled":
                subtitle = "Started with your graphical session"
            elif state in ("", "not-found", "masked"):
                subtitle = "Runner unit not installed yet"
            else:
                subtitle = f"Currently {state}"
            self._autostart_row.set_subtitle(subtitle)

        proc.communicate(done)

    def _refresh_connection(self) -> None:
        proc = self.backend.assistant("status", "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            data = be.parse_json(out) or {}
            connected = bool(data.get("connected"))
            if connected:
                self._conn_dot.set_state("ok")
                plugins = data.get("plugins") or []
                self._conn_row.set_subtitle("connected")
                self._plugin_row.set_subtitle(f"{len(plugins)} plugin(s) loaded")
            else:
                self._conn_dot.set_state("unknown")
                message = data.get("error") or (err.strip() if err else "")
                self._conn_row.set_subtitle(widgets.esc(message or "runner socket unavailable"))
                self._plugin_row.set_subtitle("—")

        proc.communicate(done)

    # -- actions --------------------------------------------------------- #
    def _on_autostart_toggled(self, row, _param) -> None:
        if self._autostart_guard:
            return
        verb = "enable" if row.get_active() else "disable"
        proc = self.backend.systemctl(verb, "utter-runner")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            if rc == 0:
                self.toast(f"Autostart {verb}d")
            else:
                self.toast(f"Could not {verb} autostart: {(err or out).strip()[:120]}")
            self._refresh_autostart()

        proc.communicate(done)

    def _on_trigger_changed(self, combo, _param) -> None:
        index = combo.get_selected()
        value = ["hotkey", "bridge"][index] if index in (0, 1) else "hotkey"
        try:
            self.backend.config.set("general", "trigger", value)
            self.toast(f"Trigger set to {value}")
        except OSError as exc:
            self.toast(f"Could not save config: {exc}")

    def _systemctl(self, action: str, unit: str) -> None:
        proc = self.backend.systemctl(action, unit)
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            if rc == 0:
                self.toast(f"{action} {unit}")
            else:
                self.toast(f"{action} failed: {(err or out).strip()[:120]}")
            self._refresh_services()

        proc.communicate(done)

    def on_runner_state(self, connected: bool) -> None:
        if not hasattr(self, "_conn_dot"):
            return
        if connected:
            self._conn_dot.set_state("ok")
        else:
            self._conn_dot.set_state("unknown")
