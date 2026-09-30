"""Models — installed store, resumable pulls with progress, and recommendations."""
from __future__ import annotations

import shutil
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import backend as be  # noqa: E402
from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class ModelsPage(Page):
    id = "models"
    title = "Models"
    subtitle = "Download, inspect and remove model files"
    icon = "folder-download-symbolic"
    keywords = "models download pull remove size huggingface recommend hardware store"
    needs_runner = False

    def __init__(self, window) -> None:
        super().__init__(window)
        self._models: list[dict] = []
        self._installed_group = widgets.group("Installed")
        self._installed_rows: list = []
        self._rec_rows: list = []
        self._pulling = False

    # -- layout ---------------------------------------------------------- #
    def build_body(self):
        cfg = self.backend.config

        # Installed
        self._refresh_button = widgets.AsyncButton("Refresh", self._on_refresh_clicked)
        self._installed_group.set_header_suffix(self._refresh_button)
        self._add_installed(self._placeholder_row("Checking the model store…"))
        self.add_group(self._installed_group)

        # Pull
        pull = widgets.group("Pull a model", "Resumable download with sha256 verification.")
        self._source_row = widgets.entry_row("Source")
        self._source_row.set_show_apply_button(False)
        self._source_row.set_tooltip_text("hf:org/repo[:file] | https://… | file://…")
        pull.add(self._source_row)
        self._tag_row = widgets.entry_row("Tag", "latest")
        self._tag_row.set_show_apply_button(False)
        pull.add(self._tag_row)
        self._pull_button = widgets.AsyncButton("Pull", self._start_pull)
        pull_row = widgets.action_row("Start download", "Progress streams from the assistant CLI")
        pull_row.add_suffix(self._pull_button)
        pull.add(pull_row)
        self.add_group(pull)

        # Download progress
        self._progress_group = widgets.group("Download")
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_show_text(False)
        self._progress_label = Gtk.Label(label="", xalign=0)
        self._progress_label.add_css_class("dim-label")
        self._progress_status = Gtk.Label(label="idle", xalign=0)
        self._progress_status.add_css_class("monospace")
        self._progress_status.add_css_class("caption")
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        progress_box.append(self._progress_bar)
        progress_box.append(self._progress_status)
        progress_box.append(self._progress_label)
        holder = Adw.ActionRow()
        holder.set_child(progress_box)
        self._progress_group.add(holder)
        self.add_group(self._progress_group)

        # Recommendations
        self._rec_group = widgets.group(
            "Recommended for this hardware",
            "Detected from your CPU, RAM and GPUs. Nothing is installed automatically.",
        )
        rec_placeholder = self._placeholder_row("Detecting hardware…")
        self._rec_group.add(rec_placeholder)
        self._rec_rows.append(rec_placeholder)
        self.add_group(self._rec_group)

        # Storage
        storage = widgets.group("Storage")
        self._storage_row = widgets.action_row("Model store", str(self.backend.models_root()))
        self._storage_row.set_subtitle_selectable(True)
        storage.add(self._storage_row)
        self._usage_row = widgets.action_row("Disk usage", "—")
        storage.add(self._usage_row)
        prune_row = widgets.action_row("Housekeeping", "Remove partial downloads and orphan blobs")
        prune_row.add_suffix(widgets.AsyncButton("Prune", self._prune))
        storage.add(prune_row)
        self.add_group(storage)

        self.refresh()
        return self.page

    def _placeholder_row(self, text: str) -> Adw.ActionRow:
        row = widgets.action_row(text, " ")
        row.add_prefix(Gtk.Image.new_from_icon_name("content-loading-symbolic"))
        return row

    def _add_installed(self, row) -> None:
        self._installed_group.add(row)
        self._installed_rows.append(row)

    # -- data ------------------------------------------------------------ #
    def refresh(self) -> None:
        self._load_models()
        self._load_recommendations()
        self._update_storage()

    def _on_refresh_clicked(self) -> None:
        self._load_models(button=self._refresh_button)

    def on_show(self) -> None:
        self.refresh()

    def _load_models(self, button=None) -> None:
        if button is not None:
            button.set_busy(True)
        proc = self.backend.assistant("models", "list", "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            if button is not None:
                button.set_busy(False)
            data = be.parse_json(out) or {}
            models = data.get("models") if isinstance(data, dict) else data
            self._models = models or []
            self._render_models(rc, err)

        proc.communicate(done)

    def _render_models(self, rc: int, err: str) -> None:
        widgets.clear_group(self._installed_group, self._installed_rows)
        if rc != 0 and not self._models:
            row = widgets.action_row("Could not list models", (err or "").strip()[:160])
            row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            self._add_installed(row)
            return
        if not self._models:
            empty = widgets.action_row(
                "No models installed",
                "Pull one below, or use a recommendation.",
            )
            empty.add_prefix(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
            self._add_installed(empty)
            return
        for model in self._models:
            self._add_installed(self._model_row(model))

    def _model_row(self, model: dict) -> Adw.ExpanderRow:
        name = str(model.get("name") or "?")
        tag = str(model.get("tag") or "latest")
        host = str(model.get("host") or "")
        size = be.human_bytes(model.get("bytes"))
        files = int(model.get("files") or 0)
        row = Adw.ExpanderRow(title=widgets.esc(f"{name}:{tag}"))
        row.set_subtitle(widgets.esc(f"{host} · {size} · {files} file(s)"))

        manifest = Adw.ActionRow(title="Manifest")
        manifest.set_subtitle(widgets.esc(model.get("manifest") or "—"))
        manifest.set_subtitle_selectable(True)
        row.add_row(manifest)

        remove = Adw.ActionRow(title="Remove", subtitle="Deletes the manifest and unreferenced blobs")
        button = widgets.AsyncButton("Remove", lambda: self._confirm_remove(name, tag))
        button.add_css_class("destructive-action")
        remove.add_suffix(button)
        row.add_row(remove)
        return row

    def _confirm_remove(self, name: str, tag: str) -> None:
        dialog = Adw.AlertDialog(
            heading="Remove model?",
            body=f"{name}:{tag} and any unreferenced blobs will be deleted.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_d, response: str) -> None:
            if response == "remove":
                self._remove(f"{name}:{tag}")

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def _remove(self, full_name: str) -> None:
        proc = self.backend.assistant("models", "rm", full_name, "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            if rc == 0:
                self.toast(f"Removed {full_name}")
            else:
                self.toast(f"Remove failed: {(err or out).strip()[:120]}")
            self._load_models()
            self._update_storage()

        proc.communicate(done)

    # -- pulls ----------------------------------------------------------- #
    def _start_pull(self) -> None:
        if self._pulling:
            return
        source = self._source_row.get_text().strip()
        if not source:
            self.toast("Enter a source such as hf:org/repo")
            return
        tag = self._tag_row.get_text().strip() or "latest"
        self._pulling = True
        self._pull_button.set_busy(True)
        self._progress_bar.set_fraction(0.0)
        self._progress_status.set_text(f"starting {source}…")
        self._progress_label.set_text("")

        proc = self.backend.assistant("models", "pull", source, "--tag", tag, "--json")
        self.track(proc)

        def on_line(line: str) -> None:
            event = be.parse_ndjson_line(line)
            if not event:
                return
            kind = event.get("event")
            if kind == "start":
                self._progress_status.set_text(f"downloading {event.get('name')}:{event.get('tag')}")
            elif kind == "progress":
                downloaded = event.get("downloaded") or 0
                total = event.get("total")
                if total:
                    self._progress_bar.set_fraction(min(1.0, downloaded / total))
                    self._progress_label.set_text(
                        f"{be.human_bytes(downloaded)} / {be.human_bytes(total)}"
                    )
                else:
                    self._progress_bar.pulse()
                    self._progress_label.set_text(be.human_bytes(downloaded))
            elif kind == "done":
                self._progress_bar.set_fraction(1.0)
                self._progress_status.set_text("done")
                self._progress_label.set_text(be.human_bytes(event.get("bytes")))
            elif kind == "error":
                self._progress_status.set_text(f"error: {event.get('error')}")

        def on_done(rc: int) -> None:
            self._pulling = False
            self._pull_button.set_busy(False)
            if rc == 0:
                self.toast(f"Pulled {source}")
                self._source_row.set_text("")
            else:
                self.toast("Pull failed — see Download progress")
            self._load_models()
            self._update_storage()

        proc.stream_lines(on_line, on_done)

    # -- recommendations ------------------------------------------------- #
    def _add_rec(self, row) -> None:
        self._rec_group.add(row)
        self._rec_rows.append(row)

    def _load_recommendations(self) -> None:
        proc = self.backend.assistant("recommend", "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            widgets.clear_group(self._rec_group, self._rec_rows)
            data = be.parse_json(out) or {}
            suggestions = data.get("suggestions")
            hardware = data.get("hardware")
            if not suggestions:
                row = widgets.action_row(
                    "Recommendation unavailable", (err or "could not probe hardware").strip()[:160]
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
                self._add_rec(row)
                return
            if hardware:
                summary = widgets.action_row("Detected hardware", self._hardware_summary(hardware))
                summary.add_prefix(Gtk.Image.new_from_icon_name("computer-symbolic"))
                self._add_rec(summary)
            stt = suggestions.get("stt", {})
            self._add_rec(self._rec_row(
                "Speech-to-text",
                f"{stt.get('backend', '?')} · {stt.get('model', '?')} ({stt.get('device', '?')})",
                stt.get("reason", ""),
                lambda: self._use_stt(stt),
            ))
            decision = suggestions.get("decision_llm", {})
            self._add_rec(self._rec_row(
                "Decision model",
                f"{decision.get('model', '?')} {decision.get('quant', '')}".strip(),
                decision.get("reason", ""),
                lambda: self._use_llm(decision),
            ))
            planner = suggestions.get("planner_llm", {})
            self._add_rec(self._rec_row(
                "Planner model",
                f"{planner.get('model', '?')} {planner.get('quant', '')}".strip(),
                planner.get("reason", ""),
                lambda: self._use_llm(planner),
            ))
            vision = suggestions.get("vision", {})
            self._add_rec(self._rec_row(
                "Vision",
                str(vision.get("model", "?")),
                vision.get("reason", ""),
                lambda: self._use_vision(vision),
            ))

        proc.communicate(done)

    def _rec_row(self, title, value, reason, on_use) -> Adw.ActionRow:
        row = widgets.action_row(title, value)
        if reason:
            row.set_tooltip_text(reason)
        button = widgets.AsyncButton("Use", lambda: on_use())
        button.add_css_class("flat")
        row.add_suffix(button)
        return row

    def _hardware_summary(self, hardware: dict) -> str:
        cpu = (hardware.get("cpu") or {}).get("model", "CPU")
        ram = hardware.get("ram_gb") or 0
        gpus = ", ".join(
            f"{g.get('name')} ({g.get('vram_gb', 0):.0f} GB)" for g in hardware.get("gpus", [])
        ) or "no GPU"
        return f"{cpu} · {ram:.0f} GB RAM · {gpus}"

    def _use_stt(self, stt: dict) -> None:
        backends = {"faster-whisper": "faster_whisper", "whisper.cpp": "whisper_cpp"}
        backend = backends.get(str(stt.get("backend")), str(stt.get("backend", "faster_whisper")))
        values = {"backend": backend, "model": stt.get("model", "")}
        if stt.get("device"):
            values["device"] = stt["device"]
        self._write("stt", values, "Speech-to-text settings updated")

    def _use_llm(self, llm: dict) -> None:
        model = f"{llm.get('model', '')} {llm.get('quant', '')}".strip()
        self._write("router", {"llm_model": model}, "Planner model updated — adjust to your served name")

    def _use_vision(self, vision: dict) -> None:
        model = str(vision.get("model", ""))
        if model and model != "none":
            self._write("vision", {"enabled": True, "model": model}, "Vision model updated")
        else:
            self._write("vision", {"enabled": False}, "Vision disabled (accessibility-only)")

    def _write(self, section: str, values: dict, message: str) -> None:
        try:
            self.backend.config.set_many(section, values)
            self.toast(message)
        except OSError as exc:
            self.toast(f"Could not save: {exc}")

    # -- storage --------------------------------------------------------- #
    def _update_storage(self) -> None:
        total = sum(int(m.get("bytes") or 0) for m in self._models)
        try:
            usage = shutil.disk_usage(self.backend.models_root())
            free = be.human_bytes(usage.free)
        except OSError:
            free = "?"
        self._usage_row.set_subtitle(f"{be.human_bytes(total)} installed · {free} free")

    def _prune(self) -> None:
        proc = self.backend.assistant("models", "prune", "--json")
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            data = be.parse_json(out) or {}
            if rc == 0:
                removed = len(data.get("removed_partials") or []) + len(data.get("removed_blobs") or [])
                self.toast(f"Pruned {removed} item(s)")
            else:
                self.toast(f"Prune failed: {(err or out).strip()[:120]}")
            self._load_models()
            self._update_storage()

        proc.communicate(done)
