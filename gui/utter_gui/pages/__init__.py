"""Settings pages, in sidebar order."""
from __future__ import annotations

from .base import Page
from .diagnostics import DiagnosticsPage
from .general import GeneralPage
from .llm import LlmPage
from .models import ModelsPage
from .perception import PerceptionPage
from .plugins import PluginsPage
from .safety import SafetyPage
from .tts import TtsPage
from .voice import VoicePage

PAGE_CLASSES = [
    GeneralPage,
    VoicePage,
    ModelsPage,
    LlmPage,
    TtsPage,
    PerceptionPage,
    PluginsPage,
    SafetyPage,
    DiagnosticsPage,
]

__all__ = ["Page", "PAGE_CLASSES"]
