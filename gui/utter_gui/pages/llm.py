"""LLM — provider, endpoint, model and the decision head."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import backend as be  # noqa: E402
from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class LlmPage(Page):
    id = "llm"
    title = "LLM"
    subtitle = "Planner model and the constrained decision head"
    icon = "applications-science-symbolic"
    keywords = "llm vllm ollama llama.cpp remote planner model endpoint base url decide threshold decision head"
    needs_runner = False

    def __init__(self, window) -> None:
        super().__init__(window)
        self._guard = False
        self._debounce = widgets.Debounce(400, self._save_threshold)

    def build_body(self):
        cfg = self.backend.config

        provider = widgets.group("Provider", "OpenAI-compatible endpoint used by the planner.")
        self._provider_combo = widgets.combo_row("Provider")
        widgets.set_string_list(self._provider_combo, [label for _v, label, _u in be.LLM_PROVIDERS])
        current_provider = str(cfg.get("router", "llm_provider", "vllm"))
        self._provider_combo.set_selected(self._index("router", "llm_provider",
            [v for v, _l, _u in be.LLM_PROVIDERS], "vllm"))
        self._provider_combo.connect("notify::selected", self._on_provider_changed)
        provider.add(self._provider_combo)

        self._url_row = widgets.entry_row("Base URL", str(cfg.get("router", "llm_base_url", "")))
        self._url_row.set_show_apply_button(True)
        self._url_row.connect("apply", lambda r: self._save("router", "llm_base_url", r.get_text()))
        provider.add(self._url_row)

        self._model_row = widgets.entry_row("Model", str(cfg.get("router", "llm_model", "")))
        self._model_row.set_show_apply_button(True)
        self._model_row.connect("apply", lambda r: self._save("router", "llm_model", r.get_text()))
        provider.add(self._model_row)

        self._fallback_row = widgets.switch_row(
            "Use the LLM fallback", "Consult the planner when no rule matches.")
        self._fallback_row.set_active(bool(cfg.get("router", "llm_fallback", True)))
        self._fallback_row.connect("notify::active", lambda r, _p: self._save(
            "router", "llm_fallback", bool(r.get_active())))
        provider.add(self._fallback_row)
        self.add_group(provider)

        decision = widgets.group(
            "Decision head",
            "A Jev-style constrained choice over precomputed candidates.",
        )
        self._head_row = widgets.switch_row("Enable decision head")
        self._head_row.set_active(bool(cfg.get("router", "decision_head_enabled", True)))
        self._head_row.connect("notify::active", lambda r, _p: self._save(
            "router", "decision_head_enabled", bool(r.get_active())))
        decision.add(self._head_row)

        threshold = float(cfg.get("router", "decide_threshold", 0.5))
        self._threshold_row, self._threshold_scale = widgets.slider_row(
            "Minimum confidence",
            "Probability required before the head is allowed to act.",
            0.0, 1.0, 0.05, threshold, lambda v: self._debounce(v),
        )
        decision.add(self._threshold_row)
        self.add_group(decision)

        test = widgets.group("Connection")
        row = widgets.action_row("Test endpoint", "GET <base URL>/models")
        self._test_button = widgets.AsyncButton("Test", self._test_endpoint)
        row.add_suffix(self._test_button)
        test.add(row)
        self.add_group(test)
        return self.page

    def _index(self, section, key, values, default) -> int:
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

    def _save_threshold(self, value: float) -> None:
        self._save("router", "decide_threshold", round(float(value), 2))

    def _on_provider_changed(self, combo, _param) -> None:
        index = combo.get_selected()
        if index < 0 or index >= len(be.LLM_PROVIDERS):
            return
        value, _label, default_url = be.LLM_PROVIDERS[index]
        self._save("router", "llm_provider", value)
        if default_url and not self._url_row.get_text().strip():
            self._url_row.set_text(default_url)
            self._save("router", "llm_base_url", default_url)

    def _test_endpoint(self) -> None:
        url = self._url_row.get_text().strip().rstrip("/") + "/models"
        if not url.startswith("http"):
            self.toast("Set a base URL first")
            return
        self._test_button.set_busy(True)
        proc = self.backend.track(be.Proc(
            ["curl", "-sS", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}", url]
        ))
        self.track(proc)

        def done(rc: int, out: str, err: str) -> None:
            self._test_button.set_busy(False)
            code = (out or "").strip()
            if rc == 0 and code.startswith("2"):
                self.toast(f"Endpoint OK ({code})")
            else:
                self.toast(f"Endpoint failed: {code or (err or '').strip()[:80]}")

        proc.communicate(done)
