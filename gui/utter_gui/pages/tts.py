"""TTS — enable speech output, pick an engine and voice, and test it."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import backend as be  # noqa: E402
from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class TtsPage(Page):
    id = "tts"
    title = "Speech"
    subtitle = "Text-to-speech output"
    icon = "audio-speakers-symbolic"
    keywords = "tts speech text to speech espeak piper voice speak output"
    needs_runner = False

    def build_body(self):
        cfg = self.backend.config

        output = widgets.group("Speech output", "Spoken confirmation of actions and replies.")
        self._enabled_row = widgets.switch_row("Enable text-to-speech")
        self._enabled_row.set_active(bool(cfg.get("tts", "enabled", False)))
        self._enabled_row.connect("notify::active", self._on_enabled)
        output.add(self._enabled_row)

        self._engine_combo = widgets.combo_row("Engine")
        labels = []
        self._engine_values = []
        for value, label, binaries in be.TTS_ENGINES:
            available = any(be.which(b) for b in binaries)
            labels.append(label if available else f"{label} (not installed)")
            self._engine_values.append(value)
        widgets.set_string_list(self._engine_combo, labels)
        current = str(cfg.get("tts", "engine", "espeak-ng"))
        try:
            self._engine_combo.set_selected(self._engine_values.index(current))
        except ValueError:
            self._engine_combo.set_selected(0)
        self._engine_combo.connect("notify::selected", self._on_engine)
        output.add(self._engine_combo)

        self._voice_row = widgets.entry_row("Voice", str(cfg.get("tts", "voice", "en")))
        self._voice_row.set_show_apply_button(True)
        self._voice_row.set_tooltip_text("Engine-specific voice name, language code or model path")
        self._voice_row.connect("apply", lambda r: self._save("tts", "voice", r.get_text()))
        output.add(self._voice_row)
        self.add_group(output)

        test = widgets.group("Test")
        self._phrase_row = widgets.entry_row("Phrase", "utter is ready")
        self._phrase_row.set_show_apply_button(False)
        test.add(self._phrase_row)
        test_row = widgets.action_row("Speak the phrase", "Runs the selected engine locally")
        self._test_button = widgets.AsyncButton("Test", self._test)
        test_row.add_suffix(self._test_button)
        test.add(test_row)
        self.add_group(test)
        return self.page

    def _save(self, section: str, key: str, value) -> None:
        try:
            self.backend.config.set(section, key, value)
            self.toast(f"Saved {section}.{key}")
        except OSError as exc:
            self.toast(f"Could not save: {exc}")

    def _on_enabled(self, row, _param) -> None:
        self._save("tts", "enabled", bool(row.get_active()))

    def _on_engine(self, combo, _param) -> None:
        index = combo.get_selected()
        if 0 <= index < len(self._engine_values):
            self._save("tts", "engine", self._engine_values[index])

    def _test(self) -> None:
        engine = self._engine_values[self._engine_combo.get_selected()]
        voice = self._voice_row.get_text().strip()
        phrase = self._phrase_row.get_text().strip() or "utter is ready"
        proc = self.backend.tts(engine, voice, phrase)
        if proc is None:
            self.toast(f"{engine} is not installed")
            return
        self._test_button.set_busy(True)
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            self._test_button.set_busy(False)
            if rc == 0:
                self.toast("Spoken")
            else:
                self.toast(f"{engine} failed: {(err or out).strip()[:120]}")

        proc.communicate(done)
