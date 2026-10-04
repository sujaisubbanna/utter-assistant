---
title: "macOS"
description: "Running Utter on macOS: native Speech.framework and whisper.cpp voice, Quartz push-to-talk and injection, permissions, the [macos] config section, and what is still Linux-only."
---

Utter runs natively on macOS alongside Linux. A small platform switch selects native Apple
frameworks instead of the Wayland tooling, so push-to-talk, speech, typing and window actions
all work on a Mac. Release bundles are built for both Apple Silicon (`aarch64`) and Intel
(`x86_64`); the settings app is code-signed and notarised when Apple Developer credentials are
configured.

:::caution[Unsigned app]
The macOS settings app on the release page (`utter-gui_<ver>_aarch64.dmg` for Apple Silicon, `utter-gui_<ver>_x86_64.dmg` for Intel) is **not
code-signed or notarised** unless Apple Developer credentials are configured. On first launch right-click → *Open*, or run
`xattr -cr /Applications/utter.app`.
:::

## What it uses

| Concern | macOS backend |
|---|---|
| Push-to-talk | Quartz `CGEventTap` (PyObjC), `pynput` fallback |
| Speech-to-text | Apple `Speech.framework` on-device with pause chunking (> 50s), then local **whisper.cpp** fallback |
| Spoken replies | `say` or `AVSpeechSynthesizer` |
| Decision router / LLM | **Ollama** (`http://127.0.0.1:11434/v1`, Metal) default; LM Studio / llama.cpp |
| Vision / Grounding | **Ollama** VLM (`llama3.2-vision:11b`, Metal) default; LM Studio |
| Typing and key chords | Quartz `CGEventPost`, AppleScript fallback |
| Focused app and window | `NSWorkspace` + Accessibility `kAXRaiseAction` for per-window raise |
| Screenshots, clipboard, sounds | `screencapture`, `pbpaste`, `afplay` |
| Background service | launchd user agents (`com.utter.assistant`, `com.utter.runner`) |
| Homebrew | `Formula/utter.rb` (CLI + service) and `Casks/utter.rb` (app) |

## Metal-native local runtime

On Linux, Utter runs background services assuming NVIDIA GPUs and CUDA. Macs have Apple Silicon with **Metal** and unified memory. Utter integrates with ready-made macOS tools rather than shipping a bespoke inference server:

- **LLM / Decision Router**: **Ollama** (Metal-accelerated out of the box, standard OpenAI-compatible `/v1` endpoint on port 11434). LM Studio and llama.cpp (`llama-server`) are supported drop-ins.
- **Vision / Screen Grounding**: Ollama hosting multimodal models (e.g. `llama3.2-vision:11b`).
- **STT**: Apple `Speech.framework` (zero-model, on-device) or `whisper.cpp` (Metal).
- **TTS**: macOS `say`.

### Installing Ollama & pulling models

```bash
brew install ollama
brew services start ollama

# Pull recommended router and vision models
ollama pull qwen2.5:3b
ollama pull llama3.2-vision:11b
```

Utter probes the local runtime before requests and reports status in `utter doctor` and `utter capabilities`. If Ollama is stopped or a model is missing, Utter returns a clean, structured status rather than hanging or crashing.

**Why not Voca?** VocaHQ's macOS app is
[VocaMac](https://github.com/VocaHQ/vocamac): a compiled Swift menu-bar app with no socket or
API for live transcripts, so it cannot be driven from Python. Utter is standalone and therefore
uses Apple's own speech recognition with a whisper.cpp fallback. If you prefer VocaMac's models,
`stt_backend = "vocamac"` drives its file-transcription CLI.

## Install: drag and drop

1. Download `utter-gui_<ver>_aarch64.dmg` (Apple Silicon) or `utter-gui_<ver>_x86_64.dmg` (Intel)
   from the release page and drag **utter** to Applications. First launch: clear Gatekeeper once
   via `xattr -cr /Applications/utter.app` (or right-click → *Open* on macOS < 15).
2. Open it. A mandatory first-run **onboarding wizard** (language, permissions, keys, apps,
   model) runs before the settings shell. The **Settings** tab unpacks the Python runtime and
   the assistant that ship inside the app into `~/Library/Application Support/utter/`, starts
   the two launchd agents and shows the permissions. No Homebrew, no Python, no terminal.

Updates work the same way: drop in the new app and Settings offers **Update**.

### Homebrew

The recommended path is the official tap:

```bash
brew tap sujaisubbanna/utter
brew install utter          # CLI + launchd service
brew services start utter   # start the background daemon
brew install --cask utter   # GUI app
```

To track the latest `main` instead of the tagged release, build from a checkout:
`brew install --build-from-source Formula/utter.rb` and `brew install --cask Casks/utter.rb`.

Developers can run from a checkout instead: `macos/setup.sh` creates `.venv-macos`,
installs the `[macos]` extras and the launchd agents.

## First run: the onboarding wizard and Settings

On a Mac the settings app runs a mandatory first-run **onboarding wizard** before the settings
shell appears. It walks through your **language**, the required **permissions**, your
push-to-talk **keys**, which **apps** Utter may act on, and a first **model**. Every step can be
skipped, progress is remembered across launches, and you can re-run the wizard later from
Settings.

The **Settings** tab itself lists each permission with a one-line reason, a **Grant access**
button that triggers the macOS prompt, an **Open System Settings** button that jumps to the
exact pane, and a status badge that re-checks live until everything is granted. The two launchd
agents (plugin runner and voice assistant) are shown underneath with a Start button.

The prompts come from the assistant's own Python, not from the app window, because macOS
grants permissions to the process that asks. That is the name you will see in System
Settings. The same check works from a terminal:

```bash
.venv-macos/bin/python -m assistant macos-permissions --request all
```

The rest of the app adapts too: **Voice** edits the `[macos]` keys and engines, **Spoken
replies** offers the system voices, **General** controls the launchd agents, and
**Troubleshooting** tails `~/Library/Logs/utter/`.

## Configuration

```toml
[macos]
stt_backend = "whisper_cpp"      # apple_speech | whisper_cpp | faster_whisper | vocamac
stt_fallback = "apple_speech"
speech_locale = "en-US"          # fallback when [stt] language does not resolve
on_device_only = true            # never send audio to Apple's servers
tts_backend = "say"              # say | avspeech | none
tts_voice = ""                   # `say -v ?` lists voices
tts_rate = 0
hotkey_backend = "quartz"        # quartz | pynput
dictation_key = "right_option"   # transcript is typed
assistant_key = "right_command"  # transcript is run as an action
injection = "quartz"             # quartz | applescript
notifications = true

[macos.runtime]
llm_provider = "ollama"          # ollama | lm_studio | llamacpp | mlx
llm_base_url = "http://127.0.0.1:11434/v1"
llm_model = "qwen2.5:3b"
vision_provider = "ollama"       # ollama | lm_studio | llamacpp
vision_base_url = "http://127.0.0.1:11434/v1"
vision_model = "llama3.2-vision:11b"
```

Linux ignores this section entirely. On macOS, `[router]` and `[vision]` automatically resolve to the Metal-native endpoints configured in `[macos.runtime]` (defaulting to local Ollama) rather than the Linux CUDA/vLLM endpoints.

## What works, what is Linux-only

- **Verified by CI:** automated matrix packaging of both Apple Silicon (`aarch64`) and
  Intel (`x86_64`) .dmg/.app bundles, fail-safe codesigning/notarization, platform detection tests.
- **Implemented:** push-to-talk with two keys,
  Metal runtime resolution and graceful degradation, native speech recognition with pause-aware audio chunking (> 50s) and whisper.cpp runtime fallback,
  dictation typing, app and URL launching, window focus with AX window raising (`kAXRaiseAction`),
  clipboard, spoken replies, notifications, screenshots for the vision tier with Retina geometry handling,
  the plugin runner socket with peer credentials (`LOCAL_PEERCRED` / `LOCAL_PEERPID` and `proc_pidpath`),
  the Homebrew tap (`sujaisubbanna/utter`): `Formula/utter.rb` for the CLI/launchd service and `Casks/utter.rb` for the .app.
- **Linux-only:** niri compositor actions and workspace-aware
  focusing, AT-SPI accessibility clicks (macOS goes straight to vision), MPRIS media keys,
  the Noctalia widget and OSD, the sandbox wrapper, the Linux installer wizard, and the settings
  app's service controls (they call `systemctl`).
- **Hardware- and permission-dependent:** physical audio input, hardware key-tap edge detection,
  actual AX synthetic keystrokes, real Screen Recording permission capture, and physical Metal GPU inference under load with Ollama.

The complete matrix, with the per-module status, is in
[`docs/MACOS.md`](https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/MACOS.md).

