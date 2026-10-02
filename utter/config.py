"""Config loading. TOML at ~/.config/utter/config.toml with defaults from config.default.toml."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _xdg_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "utter"


@dataclass
class HotkeyConfig:
    key: str = "KEY_RIGHTCTRL"


@dataclass
class PTTConfig:
    # Both keys are evdev key names, handled by utter's own listener.
    #   dictation -> transcript is typed;  assistant -> transcript is executed.
    # (keyd maps physical Right Alt -> Insert on this machine.)
    dictation_key: str = "KEY_F13"
    assistant_key: str = "KEY_INSERT"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    device: str = ""


@dataclass
class STTConfig:
    backend: str = "faster_whisper"
    model: str = "distil-small.en"
    device: str = "cuda"  # Linux default (CUDA/NVIDIA; ignored on macOS)
    compute_type: str = "float16"
    # Spoken language. "auto" = resolve from the system locale (LC_ALL/
    # LC_MESSAGES/LANG), else let Whisper auto-detect. Independent of the
    # settings-app UI language. Use a code like "en", "en-GB", "de-DE".
    language: str = "auto"


@dataclass
class TTSConfig:
    """Spoken replies (``[tts]``), independent of the UI language.

    ``engine`` picks a local Linux engine: ``auto`` (piper → espeak-ng →
    espeak → spd-say), ``none``, or an engine name to force. ``language``
    follows the same rules as ``[stt] language`` (default ``"auto"``).
    ``voice`` is engine-specific (espeak voice name, Piper voice model/path);
    empty derives a default from ``language`` or uses the engine default.
    ``enabled`` gates Linux spoken replies (on by default; macOS keeps using
    ``[macos]``).
    """
    enabled: bool = True
    engine: str = "auto"
    language: str = "auto"
    voice: str = ""


@dataclass
class RouterConfig:
    llm_fallback: bool = True
    llm_base_url: str = "http://127.0.0.1:8001/v1"
    llm_model: str = "qwen3-4b"
    # Jev-style constrained decision head: minimum probability to act.
    decide_threshold: float = 0.5


@dataclass
class VisionConfig:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:8000/v1"
    model: str = "uitars"
    target_width: int = 1344
    cuda_visible_devices: str = "1"  # Linux default (ignored on macOS)


@dataclass
class ActionsConfig:
    require_confirm: list[str] = field(
        default_factory=lambda: ["send", "submit", "delete", "purchase", "pay", "confirm order"]
    )
    click_duration_ms: int = 40
    # Browser to use for web actions (profile id or app id, e.g. "firefox").
    # Empty = the browser you're looking at, else any open one, else the
    # desktop default.
    preferred_browser: str = ""


@dataclass
class SleepConfig:
    """Sleep mode: say a trigger phrase to free the GPU; hold a PTT key to wake."""
    enabled: bool = True
    trigger: list[str] = field(default_factory=lambda: ["go to sleep"])
    # Services whose models are unloaded while asleep.
    services: list[str] = field(default_factory=lambda: ["utter-vision", "utter-planner"])
    # Also drop the speech model inside the listener (reloaded on wake).
    unload_speech: bool = True
    # Fall asleep by itself after idle_minutes without Utter activity (a
    # push-to-talk key, a spoken command, or waking). Desktop input elsewhere
    # does not count. Independent of `enabled`, which gates the trigger phrase.
    on_idle: bool = True
    idle_minutes: float = 15
    # How long the OSD may show the additive "loading" state while the model
    # services restart after wake / on cold start. Readiness is polled from
    # each server's ``/v1/models``; this is the bounded fallback used only when
    # no readiness endpoint answers in time.
    model_ready_timeout_s: float = 30.0


@dataclass
class OsdConfig:
    # Optional on-screen-display emitter for assistant mode (Noctalia overlay).
    enabled: bool = True
    position: str = "bottom_center"
    dismiss_ms: int = 1200
    stream: bool = True
    stream_interval_ms: int = 700
    window_s: float = 6.0


@dataclass
class MacosRuntimeConfig:
    """Ready-made Metal runtime backends for macOS (``[macos.runtime]``).

    External inference tools running on Apple Silicon via Metal:
      - LLM: Ollama (primary), LM Studio, llama.cpp, or MLX
      - Vision: local VLM (e.g. llama3.2-vision, qwen2.5-vl) served by Ollama/LM Studio
    """
    llm_provider: str = "ollama"           # ollama | lm_studio | llamacpp | mlx
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen2.5:3b"
    vision_provider: str = "ollama"        # ollama | lm_studio | llamacpp
    vision_base_url: str = "http://127.0.0.1:11434/v1"
    vision_model: str = "llama3.2-vision:11b"


@dataclass
class MacosConfig:
    """macOS-only settings (``[macos]``). Ignored on Linux.

    Nothing here changes Linux behaviour: the section only selects which native
    backend is used when ``sys.platform == "darwin"``.
    """
    # Speech-to-text: "apple_speech" (Speech.framework via PyObjC) first, then
    # the local whisper.cpp fallback. "vocamac" uses an installed VocaMac.app's
    # file-transcription CLI. Any of the Linux [stt] backends is also accepted.
    stt_backend: str = "apple_speech"
    stt_fallback: str = "whisper_cpp"
    speech_locale: str = "en-US"
    # Keep recognition on the device (no Apple servers). Requires a locale with
    # an on-device model; otherwise the request fails and whisper.cpp is used.
    on_device_only: bool = True
    # Text-to-speech: "say" (the system CLI), "avspeech" (AVSpeechSynthesizer
    # via PyObjC) or "none".
    tts_backend: str = "say"
    tts_voice: str = ""
    tts_rate: int = 0          # words per minute; 0 = system default
    # Push-to-talk keys: "quartz" (CGEventTap via PyObjC) or "pynput".
    hotkey_backend: str = "quartz"
    dictation_key: str = "right_option"
    assistant_key: str = "right_command"
    # Keyboard/mouse injection: "quartz" (CGEventPost) with an AppleScript
    # fallback, or "applescript" only.
    injection: str = "quartz"
    notifications: bool = True
    # Ready-made Metal runtime backends (Ollama primary; LM Studio / llama.cpp alternatives).
    runtime: MacosRuntimeConfig = field(default_factory=MacosRuntimeConfig)
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen2.5:3b"
    vision_provider: str = "ollama"
    vision_base_url: str = "http://127.0.0.1:11434/v1"
    vision_model: str = "llama3.2-vision:11b"


@dataclass
class KwinConfig:
    """KDE Plasma (KWin) backend settings (``[kwin]``). Ignored on niri.

    Nothing here changes niri behaviour: the section only tunes how the KWin
    backend talks to Plasma when ``[general] compositor`` resolves to "kwin".
    """
    # Screenshot path: "auto" tries spectacle, then the XDG portal, then grim.
    screenshot: str = "auto"
    # Clipboard read: "auto" tries klipper over D-Bus, then wl-paste.
    clipboard: str = "auto"
    # Use `kdotool` for window queries/actions when it is installed.
    use_kdotool: bool = True
    # Fall back to a tiny KWin script (org.kde.kwin.Scripting) for window queries.
    use_scripts: bool = True
    script_timeout_s: float = 3.0
    # ydotool absolute-pointer multiplier on KWin (niri keeps its measured 0.5).
    pointer_abs_factor: float = 1.0


@dataclass
class GeneralConfig:
    trigger: str = "hotkey"
    # Compositor backend: "auto" (detect niri / KDE Plasma), "niri" or "kwin".
    compositor: str = "auto"


@dataclass
class TargetConfig:
    """App-targeted input injection (``[target]``).

    True background key injection is impossible on Wayland, so a targeted
    ``key``/``type_text`` is a *focus round-trip*: focus the target window,
    inject, then restore. Cross-workspace / fullscreen focus moves are
    disruptive, so they are gated (``cross_workspace``) and confirmed.

    - ``mode``: ``round_trip`` (focus, act, restore), ``leave`` (focus, act,
      stay) or ``off`` (only focus/close/media; refuse targeted input).
    - ``cross_workspace``: ``ask`` (confirm), ``allow`` or ``refuse``.
    - ``restore``: ``if_unchanged`` (only if the user did not move away),
      ``always`` or ``never``.
    - ``focus_timeout_ms``: how long to poll for the focus to land before
      aborting (no injection if it never does).
    """
    mode: str = "round_trip"
    cross_workspace: str = "ask"
    restore: str = "if_unchanged"
    focus_timeout_ms: int = 500


@dataclass
class WaylandConfig:
    """Wayland focus round-trip policy (``[wayland]``).

    Wayland cannot inject into an unfocused window, so a targeted action is a
    focus round-trip. Measured on real niri: a **same-workspace** round-trip is
    ~38 ms and invisible; a **cross-workspace** one is ~41 ms when the
    compositor has animations off, but ~250 ms of visible viewport scroll when
    animations are on (``horizontal-view-movement``).

    ``[wayland].cross_workspace`` supersedes ``[target].cross_workspace`` for
    the workspace decision:

    - ``auto``: allow without asking only when ``assume_animations_off`` is
      true; otherwise fall back to ``[target].cross_workspace`` (ask/allow/
      refuse).
    - ``ask`` / ``allow`` / ``refuse``: explicit, override ``[target]``.

    ``assume_animations_off`` is the operator's assertion that the compositor
    will not visibly scroll the viewport on a workspace switch.
    """
    cross_workspace: str = "auto"
    assume_animations_off: bool = False


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    wayland: WaylandConfig = field(default_factory=WaylandConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    ptt: PTTConfig = field(default_factory=PTTConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    sleep: SleepConfig = field(default_factory=SleepConfig)
    osd: OsdConfig = field(default_factory=OsdConfig)
    macos: MacosConfig = field(default_factory=MacosConfig)
    kwin: KwinConfig = field(default_factory=KwinConfig)
    log_level: str = "INFO"


def _merge(dc, data: dict):
    for key, value in (data or {}).items():
        if hasattr(dc, key) and not isinstance(getattr(dc, key), type):
            attr = getattr(dc, key)
            if hasattr(attr, "__dataclass_fields__") and isinstance(value, dict):
                _merge(attr, value)
            else:
                setattr(dc, key, value)


def load_config(path: str | os.PathLike | None = None) -> Config:
    cfg = Config()
    p = Path(path) if path else _xdg_config_dir() / "config.toml"
    if not p.exists():
        default = Path(__file__).resolve().parent.parent / "config.default.toml"
        if default.exists():
            p = default
    if p.exists():
        with open(p, "rb") as fh:
            raw = tomllib.load(fh)
        _merge(cfg.general, raw.get("general", {}))
        _merge(cfg.target, raw.get("target", {}))
        _merge(cfg.wayland, raw.get("wayland", {}))
        _merge(cfg.hotkey, raw.get("hotkey", {}))
        _merge(cfg.ptt, raw.get("ptt", {}))
        _merge(cfg.audio, raw.get("audio", {}))
        _merge(cfg.stt, raw.get("stt", {}))
        _merge(cfg.tts, raw.get("tts", {}))
        _merge(cfg.router, raw.get("router", {}))
        _merge(cfg.vision, raw.get("vision", {}))
        _merge(cfg.actions, raw.get("actions", {}))
        _merge(cfg.sleep, raw.get("sleep", {}))
        _merge(cfg.osd, raw.get("osd", {}))
        _merge(cfg.macos, raw.get("macos", {}))
        _merge(cfg.kwin, raw.get("kwin", {}))
        # Keep flat [macos] and nested [macos.runtime] fields in sync
        mac_raw = raw.get("macos", {})
        mac_rt_raw = mac_raw.get("runtime", {}) if isinstance(mac_raw, dict) else {}
        for attr in ("llm_provider", "llm_base_url", "llm_model", "vision_provider", "vision_base_url", "vision_model"):
            if attr in mac_rt_raw:
                setattr(cfg.macos, attr, getattr(cfg.macos.runtime, attr))
            elif attr in mac_raw:
                setattr(cfg.macos.runtime, attr, getattr(cfg.macos, attr))
        if "log_level" in raw.get("daemon", {}):
            cfg.log_level = raw["daemon"]["log_level"]
    return cfg
