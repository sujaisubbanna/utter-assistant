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
    # Both keys are evdev key names, handled by utter (not vocalinux's parser).
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
    device: str = "cuda"
    compute_type: str = "float16"


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
    cuda_visible_devices: str = "1"


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
    trigger: str = "bridge"
    # Compositor backend: "auto" (detect niri / KDE Plasma), "niri" or "kwin".
    compositor: str = "auto"


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    ptt: PTTConfig = field(default_factory=PTTConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
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
        _merge(cfg.hotkey, raw.get("hotkey", {}))
        _merge(cfg.ptt, raw.get("ptt", {}))
        _merge(cfg.audio, raw.get("audio", {}))
        _merge(cfg.stt, raw.get("stt", {}))
        _merge(cfg.router, raw.get("router", {}))
        _merge(cfg.vision, raw.get("vision", {}))
        _merge(cfg.actions, raw.get("actions", {}))
        _merge(cfg.sleep, raw.get("sleep", {}))
        _merge(cfg.osd, raw.get("osd", {}))
        _merge(cfg.macos, raw.get("macos", {}))
        _merge(cfg.kwin, raw.get("kwin", {}))
        if "log_level" in raw.get("daemon", {}):
            cfg.log_level = raw["daemon"]["log_level"]
    return cfg
