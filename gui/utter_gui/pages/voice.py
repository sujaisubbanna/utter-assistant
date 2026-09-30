"""Voice — push-to-talk keys, STT backend, input device and mic level."""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import backend as be  # noqa: E402
from .. import keys, widgets  # noqa: E402
from .base import Page  # noqa: E402


class KeyCaptureDialog(Adw.Dialog):
    """Modal dialog that captures a single key press as an evdev name."""

    def __init__(self, title: str, current: str, on_captured: Callable[[str], None]):
        super().__init__()
        self.set_title(title)
        self.set_content_width(380)
        self.set_content_height(260)
        self._on_captured = on_captured

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        prompt = Gtk.Label(label="Press a key now")
        box.append(prompt)

        self._preview = Gtk.Label(label=f"Current: {keys.display_name(current)}")
        self._preview.add_css_class("dim-label")
        self._preview.add_css_class("monospace")
        box.append(self._preview)

        caption = Gtk.Label(
            label="Escape cancels · modifiers are captured too",
            wrap=True, justify=Gtk.Justification.CENTER,
        )
        caption.add_css_class("dim-label")
        caption.add_css_class("caption")
        box.append(caption)

        self.set_child(box)

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.add_controller(controller)
        self.connect("map", lambda *_a: self.grab_focus())

    def _on_key(self, _ctrl, keyval: int, keycode: int, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        name = keys.name_for_gdk_keycode(keycode)
        if not name:
            self._preview.set_text(f"Unmapped key (code {keycode}) — try another")
            return True
        self._on_captured(name)
        self.close()
        return True


class MicMonitor:
    """Streams the default input and reports a smoothed level."""

    def __init__(self, page: "VoicePage", bar: Gtk.LevelBar, status: Gtk.Label):
        self.page = page
        self.bar = bar
        self.status = status
        self._proc = None
        self._level = 0.0

    def start(self) -> None:
        if self._proc is not None:
            return
        proc = self.page.backend.pw_record()
        self.page.track(proc)
        self._proc = proc
        self.status.set_text("listening…")

        def on_bytes(data: bytes) -> None:
            level = be.rms_from_pcm_s16(data)
            self._level = max(level, self._level * 0.72)
            self.bar.set_value(self._level)

        def on_done(_rc: int) -> None:
            self._proc = None
            self._level = 0.0
            self.bar.set_value(0.0)
            self.status.set_text("stopped — is pw-record available?")

        proc.stream_bytes(on_bytes, on_done)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.cancel()
            self._proc = None
        self.bar.set_value(0.0)


class VoicePage(Page):
    id = "voice"
    title = "Voice"
    subtitle = "Push-to-talk, recognition and audio input"
    icon = "audio-input-microphone-symbolic"
    keywords = "voice ptt push to talk key stt whisper faster-whisper vosk parakeet microphone audio language"
    needs_runner = False

    def __init__(self, window) -> None:
        super().__init__(window)
        self._key_labels: dict[str, Gtk.Label] = {}
        self._source_names: list[str] = [""]
        self._monitor: Optional[MicMonitor] = None
        self._source_guard = False

    def build_body(self):
        cfg = self.backend.config

        ptt = widgets.group("Push-to-talk keys", "Captured raw from the evdev listener.")
        dict_row, dict_label = self._key_row(
            "Dictation key", "Transcript is typed into the focused field.",
            "dictation_key", str(cfg.get("ptt", "dictation_key", "")),
        )
        asst_row, asst_label = self._key_row(
            "Assistant key", "Transcript is run as a screen action.",
            "assistant_key", str(cfg.get("ptt", "assistant_key", "")),
        )
        self._key_labels = {"dictation_key": dict_label, "assistant_key": asst_label}
        ptt.add(dict_row)
        ptt.add(asst_row)
        self.add_group(ptt)

        stt = widgets.group("Speech-to-text", "Language model that turns speech into text.")
        self._backend_combo = widgets.combo_row("Backend")
        widgets.set_string_list(self._backend_combo, [label for _v, label, _d in be.STT_BACKENDS])
        self._backend_combo.set_selected(self._index_for("stt", "backend",
            [v for v, _l, _d in be.STT_BACKENDS], "faster_whisper"))
        self._backend_combo.connect("notify::selected", self._on_backend_changed)
        stt.add(self._backend_combo)

        self._model_row = widgets.entry_row("Model", str(cfg.get("stt", "model", "")))
        self._model_row.set_show_apply_button(True)
        self._model_row.connect("apply", lambda r: self._save("stt", "model", r.get_text()))
        stt.add(self._model_row)

        self._language_row = widgets.entry_row("Language", str(cfg.get("stt", "language", "auto")))
        self._language_row.set_show_apply_button(True)
        self._language_row.set_tooltip_text("ISO code such as en, de, or auto to detect")
        self._language_row.connect("apply", lambda r: self._save("stt", "language", r.get_text()))
        stt.add(self._language_row)

        self._device_combo = widgets.combo_row("Compute device")
        widgets.set_string_list(self._device_combo, ["cuda", "cpu", "auto", "int8"])
        self._device_combo.set_selected(self._index_for("stt", "device",
            ["cuda", "cpu", "auto", "int8"], "cuda"))
        self._device_combo.connect("notify::selected", self._on_device_changed)
        stt.add(self._device_combo)
        self.add_group(stt)

        audio = widgets.group("Input device", "PipeWire source the hotkey listener records from.")
        self._source_combo = widgets.combo_row("Microphone")
        self._source_combo.set_subtitle("Default input follows the system default source")
        self._source_combo.connect("notify::selected", self._on_source_changed)
        audio.add(self._source_combo)

        self._level_bar = Gtk.LevelBar.new_for_interval(0.0, 1.0)
        self._level_bar.set_size_request(180, -1)
        self._level_bar.set_valign(Gtk.Align.CENTER)
        level_row = widgets.action_row("Input level", "Live RMS from the microphone")
        level_row.add_suffix(self._level_bar)
        audio.add(level_row)

        self._monitor_switch = widgets.switch_row(
            "Monitor microphone", "Starts pw-record to show a live level.")
        self._monitor_switch.connect("notify::active", self._on_monitor_toggled)
        audio.add(self._monitor_switch)
        self.add_group(audio)

        test = widgets.group("Test", "Verify the setup end to end.")
        hint = widgets.action_row(
            "Test dictation",
            "Hold your dictation key, speak, then release — the text is typed into the focused field.",
        )
        test.add(hint)
        self.add_group(test)
        return self.page

    # -- builders -------------------------------------------------------- #
    def _key_row(
        self, title: str, subtitle: str, field: str, current: str
    ) -> tuple[Adw.ActionRow, Gtk.Label]:
        row = widgets.action_row(title, subtitle)
        value = Gtk.Label(label=keys.display_name(current))
        value.add_css_class("monospace")
        value.add_css_class("dim-label")
        row.add_suffix(value)
        button = widgets.AsyncButton("Capture", lambda r=row, t=title, f=field: self._capture(f, t))
        button.add_css_class("flat")
        row.add_suffix(button)
        return row, value

    def _index_for(self, section: str, key: str, values: list[str], default: str) -> int:
        current = str(self.backend.config.get(section, key, default))
        try:
            return values.index(current)
        except ValueError:
            return values.index(default)

    def _save(self, section: str, key: str, value) -> None:
        try:
            self.backend.config.set(section, key, value)
            self.toast(f"Saved {section}.{key}")
        except OSError as exc:
            self.toast(f"Could not save: {exc}")

    # -- key capture ----------------------------------------------------- #
    def _capture(self, field: str, title: str) -> None:
        current = str(self.backend.config.get("ptt", field, ""))
        dialog = KeyCaptureDialog(title, current, lambda name: self._captured(field, name))
        dialog.present(self.window)

    def _captured(self, field: str, name: str) -> None:
        try:
            self.backend.config.set("ptt", field, name)
        except OSError as exc:
            self.toast(f"Could not save key: {exc}")
            return
        label = self._key_labels.get(field)
        if label is not None:
            label.set_label(keys.display_name(name))
        suffix = keys.display_name(name)
        if keys.is_modifier(name):
            suffix += " (modifier)"
        self.toast(f"{field.replace('_', ' ').capitalize()} → {suffix}")

    # -- handlers -------------------------------------------------------- #
    def _on_backend_changed(self, combo, _param) -> None:
        index = combo.get_selected()
        if index < 0 or index >= len(be.STT_BACKENDS):
            return
        value = be.STT_BACKENDS[index][0]
        self._save("stt", "backend", value)

    def _on_device_changed(self, combo, _param) -> None:
        values = ["cuda", "cpu", "auto", "int8"]
        index = combo.get_selected()
        if 0 <= index < len(values):
            self._save("stt", "device", values[index])

    def _on_source_changed(self, combo, _param) -> None:
        if self._source_guard:
            return
        index = combo.get_selected()
        if 0 <= index < len(self._source_names):
            self._save("audio", "device", self._source_names[index])

    def _on_monitor_toggled(self, row, _param) -> None:
        if row.get_active():
            self._monitor.start()
        else:
            self._monitor.stop()

    # -- lifecycle ------------------------------------------------------- #
    def refresh(self) -> None:
        self._discover_sources()

    def on_show(self) -> None:
        self.refresh()

    def on_hide(self) -> None:
        if self._monitor_switch.get_active():
            self._monitor_switch.set_active(False)

    def _discover_sources(self) -> None:
        proc = be.Proc(["pactl", "list", "short", "sources"])
        self.backend.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            sources = be.parse_pactl_sources(out) if rc == 0 else []
            names = [""] + [s["name"] for s in sources]
            labels = ["Default input"] + [
                s.get("description") or s["name"] for s in sources
            ]
            if names == self._source_names:
                return
            self._source_names = names
            current = str(self.backend.config.get("audio", "device", ""))
            # Guard: changing the model/selection must not look like a user edit.
            self._source_guard = True
            try:
                widgets.set_string_list(self._source_combo, labels)
                try:
                    self._source_combo.set_selected(names.index(current))
                except ValueError:
                    self._source_combo.set_selected(0)
            finally:
                self._source_guard = False
            if not sources:
                self._source_combo.set_subtitle("pactl not available — default input in use")

        proc.communicate(done)
