"""Diagnostics — live logs, the doctor report and a support bundle."""
from __future__ import annotations

import json
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import __version__, backend as be  # noqa: E402
from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

_MAX_LOG_LINES = 2000


class DiagnosticsPage(Page):
    id = "diagnostics"
    title = "Diagnostics"
    subtitle = "Logs, doctor report and support bundle"
    icon = "utilities-system-monitor-symbolic"
    keywords = "diagnostics logs journalctl doctor support bundle export report debug"
    needs_runner = False

    def __init__(self, window) -> None:
        super().__init__(window)
        self._log_proc = None
        self._unit = "utter-runner"
        self._doctor: dict = {}

    def build_body(self):
        logs = widgets.group("Live log", "Streams journalctl for the selected unit.")
        self._unit_combo = widgets.combo_row("Unit")
        widgets.set_string_list(self._unit_combo, [label for _u, label, _d in be.SERVICES])
        self._unit_combo.set_selected(0)
        self._unit_values = [unit for unit, _l, _d in be.SERVICES]
        self._unit_combo.connect("notify::selected", self._on_unit_changed)
        logs.add(self._unit_combo)

        self._tail_switch = widgets.switch_row("Follow logs", "journalctl --user -f")
        self._tail_switch.connect("notify::active", self._on_tail)
        logs.add(self._tail_switch)

        self._log_view = widgets.mono_view()
        self._log_view.set_wrap_mode(Gtk.WrapMode.NONE)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_child(self._log_view)
        log_scroll.set_min_content_height(260)
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_hexpand(True)
        holder = Adw.ActionRow()
        holder.set_child(log_scroll)
        logs.add(holder)

        log_actions = widgets.action_row("Actions", "Clear the buffer or copy it out")
        clear = widgets.AsyncButton("Clear", self._clear_log)
        clear.add_css_class("flat")
        log_actions.add_suffix(clear)
        logs.add(log_actions)
        self.add_group(logs)

        doctor = widgets.group("Doctor report", "Dependencies, negotiation and drift.")
        self._doctor_button = widgets.AsyncButton("Run doctor", self.refresh)
        doctor.set_header_suffix(self._doctor_button)
        self._doctor_overall = widgets.action_row("Overall", "not run yet")
        self._doctor_overall.add_prefix(widgets.dot("unknown"))
        doctor.add(self._doctor_overall)
        self._doctor_runner = widgets.action_row("Runner", "—")
        doctor.add(self._doctor_runner)
        self._doctor_plugins = widgets.action_row("Plugins", "—")
        doctor.add(self._doctor_plugins)
        self._doctor_drift = widgets.action_row("Drift", "—")
        doctor.add(self._doctor_drift)
        self._doctor_raw = Adw.ExpanderRow(title="Raw JSON")
        raw_holder = Adw.ActionRow()
        raw_view = widgets.mono_view()
        raw_view.set_wrap_mode(Gtk.WrapMode.NONE)
        raw_scroll = Gtk.ScrolledWindow()
        raw_scroll.set_child(raw_view)
        raw_scroll.set_min_content_height(200)
        raw_holder.set_child(raw_scroll)
        self._doctor_raw.add_row(raw_holder)
        self._doctor_buffer = raw_view.get_buffer()
        doctor.add(self._doctor_raw)
        self.add_group(doctor)

        bundle = widgets.group("Support bundle", "Zip of doctor, status, config and recent logs.")
        export_row = widgets.action_row("Export support bundle", "Share this when reporting an issue")
        self._export_button = widgets.AsyncButton("Export", self._on_export)
        export_row.add_suffix(self._export_button)
        bundle.add(export_row)
        self.add_group(bundle)
        return self.page

    # -- logging --------------------------------------------------------- #
    def _on_unit_changed(self, combo, _param) -> None:
        index = combo.get_selected()
        if 0 <= index < len(self._unit_values):
            self._unit = self._unit_values[index]
            if self._tail_switch.get_active():
                self._restart_tail()

    def _on_tail(self, row, _param) -> None:
        if row.get_active():
            self._restart_tail()
        else:
            self._stop_tail()

    def _restart_tail(self) -> None:
        self._stop_tail()
        self._clear_log()
        proc = self.backend.journalctl(self._unit, lines=200, follow=True)
        self._log_proc = proc

        def on_line(line: str) -> None:
            self._append_log(line)

        def on_done(_rc: int) -> None:
            self._log_proc = None

        proc.stream_lines(on_line, on_done)

    def _stop_tail(self) -> None:
        if self._log_proc is not None:
            self._log_proc.cancel()
            self._log_proc = None

    def _append_log(self, line: str) -> None:
        buffer = self._log_view.get_buffer()
        buffer.insert(buffer.get_end_iter(), line + "\n")
        if buffer.get_line_count() > _MAX_LOG_LINES:
            start = buffer.get_start_iter()
            cut = buffer.get_iter_at_line(buffer.get_line_count() - _MAX_LOG_LINES)
            buffer.delete(start, cut)
        # autoscroll if already near the bottom
        adj = self._log_view.get_parent().get_vadjustment()
        at_bottom = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 4
        if at_bottom:
            GLib.idle_add(self._scroll_log_to_end)

    def _scroll_log_to_end(self) -> bool:
        buffer = self._log_view.get_buffer()
        self._log_view.scroll_to_iter(buffer.get_end_iter(), 0.0, False, 0.0, 0.0)
        return False

    def _clear_log(self) -> None:
        self._log_view.get_buffer().set_text("")

    # -- doctor ---------------------------------------------------------- #
    def refresh(self) -> None:
        self._doctor_button.set_busy(True)
        proc = self.backend.assistant("doctor", "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            self._doctor_button.set_busy(False)
            report = be.parse_json(out) or {
                "ok": False, "connected": False,
                "error": (err or "doctor produced no output").strip(),
            }
            self._doctor = report
            self._render_doctor(report)

        proc.communicate(done)

    def _render_doctor(self, report: dict) -> None:
        ok = bool(report.get("ok"))
        connected = bool(report.get("connected"))
        self._set_dot(self._doctor_overall, "ok" if ok else "warn")
        self._doctor_overall.set_subtitle(widgets.esc(
            "all checks passed" if ok else (report.get("error") or "issues found")))
        runner = report.get("runner") or {}
        self._doctor_runner.set_subtitle(
            f"protocol {runner.get('protocol', '?')} · abi {runner.get('abi', '?')} "
            f"· v{runner.get('version', '?')}"
        )
        plugins = report.get("plugins") or []
        missing = sum(len(p.get("missing_requires") or []) for p in plugins)
        unknown = sum(len(p.get("unknown_capabilities") or []) for p in plugins)
        self._doctor_plugins.set_subtitle(
            f"{len(plugins)} loaded · {unknown} unknown cap · {missing} missing req"
            + ("" if connected else " · runner not connected")
        )
        drift = report.get("drift") or []
        self._doctor_drift.set_subtitle(widgets.esc(
            "none" if not drift else json.dumps(drift, ensure_ascii=False)))
        self._doctor_buffer.set_text(json.dumps(report, indent=2, ensure_ascii=False))

    def _set_dot(self, row: Adw.ActionRow, state: str) -> None:
        child = row.get_first_child()
        while child is not None and not isinstance(child, widgets.Dot):
            child = child.get_next_sibling()
        if isinstance(child, widgets.Dot):
            child.set_state(state)

    # -- export ---------------------------------------------------------- #
    def _on_export(self) -> None:
        default_dir = Path.home() / "Downloads"
        if not default_dir.is_dir():
            default_dir = Path.home()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        self._export_to(default_dir / f"utter-support-{timestamp}.zip")

    def _export_to(self, dest: Path) -> None:
        self._export_button.set_busy(True)
        config_text = self.backend.config.read_text()
        python = self.backend.python
        repo = str(self.backend.repo_root)
        units = be.SERVICE_UNITS

        def work() -> None:
            payload = {"meta.json": json.dumps({
                "app": "utter-gui", "version": __version__,
                "created": time.time(), "python": python, "repo": repo,
            }, indent=2)}
            payload["config.toml"] = config_text

            def run(argv: list[str]) -> str:
                try:
                    proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
                    return proc.stdout or proc.stderr
                except (OSError, subprocess.SubprocessError) as exc:
                    return f"(failed: {exc})\n"

            payload["doctor.json"] = run([python, "-m", "assistant", "doctor", "--json"])
            payload["status.json"] = run([python, "-m", "assistant", "status", "--json"])
            for unit in units:
                payload[f"logs/{unit}.log"] = run(
                    ["journalctl", "--user", "-u", unit, "-n", "300", "-o", "short-iso", "--no-pager"]
                )
            install_json = Path.home() / ".local" / "state" / "utter" / "install.json"
            if install_json.exists():
                try:
                    payload["install.json"] = install_json.read_text()
                except OSError:
                    pass
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                    for name, data in payload.items():
                        zf.writestr(name, data)
                GLib.idle_add(self._export_done, True, str(dest), "")
            except (OSError, zipfile.BadZipFile) as exc:
                GLib.idle_add(self._export_done, False, str(dest), str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _export_done(self, ok: bool, dest: str, error: str) -> bool:
        self._export_button.set_busy(False)
        self.toast(f"Bundle exported to {dest}" if ok else f"Export failed: {error}")
        return False

    # -- lifecycle ------------------------------------------------------- #
    def on_show(self) -> None:
        if not self._doctor:
            self.refresh()
        if self._tail_switch.get_active():
            self._restart_tail()

    def on_hide(self) -> None:
        self._stop_tail()
