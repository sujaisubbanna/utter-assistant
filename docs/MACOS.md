# Utter on macOS (experimental)

Utter was built for Linux on Wayland (niri first). This document describes the
macOS port: what it uses, how to set it up, and, honestly, what works, what is
Linux-only and what has **not** been tested on real Apple hardware.

> **Status: experimental and untested on a Mac.** The macOS layer was written and
> unit-tested on Linux with the Apple frameworks stubbed out. Every Quartz /
> Speech / AppKit call is the documented API, but nothing here has run against a
> real macOS session yet. Treat it as a scaffold to iterate on and please report
> what breaks.

## Design

All macOS behaviour sits behind one small module, `utter/platform.py`
(`is_macos()` / `is_linux()`), and one package, `utter/macos/`. On Linux nothing
in `utter/macos/` is imported and every existing code path is unchanged.

| Concern | Linux (unchanged) | macOS backend |
|---|---|---|
| Push-to-talk | evdev / keyd / vocalinux bridge | Quartz `CGEventTap` via PyObjC (`utter/macos/hotkey.py`), `pynput` fallback |
| Speech-to-text | faster-whisper / whisper.cpp / vocalinux | Apple `Speech.framework` (`SFSpeechRecognizer`, on-device) → local **whisper.cpp** fallback; optional **VocaMac** CLI backend |
| Spoken replies | plugin lane | `say` (default) or `AVSpeechSynthesizer` |
| Key presses / typing | `wtype` → `ydotool` | Quartz `CGEventPost` → AppleScript (`System Events`) |
| Mouse | `ydotool` | Quartz mouse / scroll events |
| Focused app + window | `niri msg --json` | `NSWorkspace.frontmostApplication` + Accessibility `AXUIElement` title, `CGWindowListCopyWindowInfo` |
| Screenshots | `grim` | `screencapture -x` + `NSScreen` geometry |
| Clipboard | `wl-paste` | `pbpaste` / `pbcopy` |
| UI sounds | `pw-play` / `paplay` | `afplay` |
| Notifications | Noctalia OSD | `osascript display notification` / `terminal-notifier` |
| App launch / URLs | desktop entries, `xdg-open` | `open -a` / `open -b`, `open <url>` |
| Service management | systemd user units | launchd agent (`macos/com.utter.assistant.plist`) |

The shared modules (`utter/actions/keyboard.py`, `mouse.py`, `launch.py`,
`utter/context/clipboard.py`, `utter/vision/screenshot.py`, `utter/sounds.py`)
dispatch at the top of each public function; the daemon, executor and the
`utter_py` plugin read desktop state through `utter/context/desktop.py`, which
re-exports `utter.context.niri` on Linux and `utter.macos.desktop` on macOS.

### Why not "voca" on macOS?

The owner's brief mentioned "voca macOS". **Voca** is VocaHQ, the organisation
behind [vocalinux](https://github.com/VocaHQ/vocalinux), the Linux dictation
tool Utter already piggybacks on through `utter/voice/vocalinux_bridge.py`. Its
macOS sibling is [VocaMac](https://github.com/VocaHQ/vocamac): a Swift menu-bar
app (macOS 14+, Apple Silicon only, AGPL-3.0, `brew install --cask vocamac`)
with WhisperKit / Parakeet / Apple Speech engines.

It is a fine dictation app, but it is **not usable as Utter's voice engine**:

- there is no `voca` / `voca-cli` package; VocaMac is a GUI app whose only
  headless mode is `VocaMac --transcribe-file <path> --json`;
- it exposes **no socket, API or IPC** to consume live transcripts, and it is
  compiled Swift, so the monkeypatch trick the Linux bridge uses on vocalinux's
  Python `inject_text` is impossible;
- it is Apple Silicon only.

So the macOS port uses **macOS-native voice**: `Speech.framework` as the primary
STT (zero extra models, on-device, fast) with **whisper.cpp** as the offline
fallback and quality option, and `say` for TTS. VocaMac can still coexist as a
plain dictation app, and `[macos] stt_backend = "vocamac"` lets Utter use its
file-transcription CLI as a batch STT engine if you prefer its models (untested).

## Requirements

- macOS 12+ (Speech on-device recognition and `screencapture` are older than
  that, but PyObjC 10 wheels target 12+). Apple Silicon or Intel: the Python
  side is architecture-neutral; the **release `.dmg` is arm64 only**.
- Python 3.12+ (`brew install python@3.12`).
- Python packages: `pip install -e '.[macos]'` installs `pyobjc-framework-Cocoa`,
  `-Quartz`, `-Speech`, `-AVFoundation`, `-ApplicationServices`, `sounddevice`,
  `numpy` and `pywhispercpp`.
- `brew install portaudio` (for `sounddevice`) and, optionally, `terminal-notifier`.
- The decision head / planner / vision servers are the same OpenAI-compatible
  HTTP endpoints as on Linux (`[router]`, `[vision]`); run them wherever you like.

### Permissions

macOS gates everything Utter does. Grant these to the **python binary that runs
the daemon** (`.venv-macos/bin/python`, or your terminal app when testing) under
*System Settings → Privacy & Security*:

| Permission | Needed for |
|---|---|
| Microphone | recording while a push-to-talk key is held |
| Speech Recognition | the `apple_speech` backend (prompted on first use) |
| Input Monitoring | the Quartz event tap that watches the push-to-talk keys |
| Accessibility | typing text / key chords, reading the focused window title |
| Screen Recording | `screencapture` for the vision tier |

Without Input Monitoring `CGEventTapCreate` returns `NULL` and the daemon logs a
clear error; without Accessibility typed text silently goes nowhere.

## Setup

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
macos/setup.sh              # .venv-macos + pip install -e '.[macos]' + launchd agent
macos/setup.sh --no-agent   # just the virtualenv and ~/.config/utter/config.toml

# try it
.venv-macos/bin/python -m utter.daemon --text "open youtube" --dry-run
.venv-macos/bin/python -m utter.daemon            # hold Right ⌘ and speak
macos/setup.sh --uninstall                        # removes only the launchd agent
```

`install.sh` (the Linux wizard) refuses to run on macOS and points here.

The settings app ships as `utter-gui_<ver>_aarch64.dmg` on the release page. It
is **not code-signed or notarised**: on first launch right-click → *Open*, or
run `xattr -dr com.apple.quarantine /Applications/utter.app`. Its service page
still talks to `systemctl` and will show the services as unavailable on macOS;
use `launchctl` (see the plist header) until that page grows a launchd backend.

## First run: the Set up page

On a Mac the settings app opens on **Set up** the first time (and keeps it in the
sidebar). It is modelled on how Raycast onboards: one screen that lists every
permission, says why it is needed, has a **Grant access** button that triggers
the system prompt, an **Open System Settings** button that deep-links to the
exact pane (`x-apple.systempreferences:com.apple.preference.security?Privacy_…`),
and a status badge that re-checks every few seconds until everything is green.
Below the permissions it shows the two launchd agents (plugin runner, voice
assistant) with a Start button.

The checks and prompts run in the **daemon's python**, not in the settings app:
macOS attaches privacy permissions to the process that asks, and the process
that needs them is the interpreter launchd starts. The app just runs
`python -m assistant macos-permissions --json` (and `--request <name>`), and the
daemon repeats the probe at startup and writes
`~/Library/Application Support/utter/permissions.json`. From a terminal:

```bash
.venv-macos/bin/python -m assistant macos-permissions            # table
.venv-macos/bin/python -m assistant macos-permissions --request all
```

macOS only shows each prompt once; after a refusal the row's button opens the
pane so you can flip the switch by hand. Accessibility and Input Monitoring have
no prompt-then-allow flow at all: the prompt only opens System Settings.

### What the settings app looks like on a Mac

The same Tauri app, built as `utter.app`, with platform-aware pages:

| Page | macOS behaviour |
|---|---|
| Set up | permissions onboarding + launchd agents (macOS only) |
| General | the service rows are backed by `launchctl` (`com.utter.runner`, `com.utter.assistant`); vision/planner/audio units show as not installed |
| Voice | writes `[macos]`: push-to-talk keys by name (Right ⌘ / Right ⌥ …), Apple Speech / whisper.cpp / VocaMac engine + fallback, locale, on-device switch |
| Spoken replies | `say` / AVSpeechSynthesizer, voice name, rate, with a test button |
| Troubleshooting | log tail reads `~/Library/Logs/utter/*.log` instead of `journalctl` |
| Models, App actions, AI model, Screen, Plugins, Safety | unchanged |

Linux builds never show the macOS pages: the switch is `std::env::consts::OS` in
the Rust backend, exposed as `platform_info`.

## Configuration

Everything macOS-specific lives in one section. Linux ignores it entirely.

```toml
[macos]
stt_backend = "apple_speech"     # apple_speech | whisper_cpp | faster_whisper | vocamac
stt_fallback = "whisper_cpp"     # tried when the primary fails to load
speech_locale = "en-US"
on_device_only = true            # never send audio to Apple's servers
tts_backend = "say"              # say | avspeech | none
tts_voice = ""                   # e.g. "Samantha"; `say -v ?` lists voices
tts_rate = 0                     # words per minute, 0 = default
hotkey_backend = "quartz"        # quartz | pynput
dictation_key = "right_option"   # transcript is typed into the focused field
assistant_key = "right_command"  # transcript is run as a desktop action
injection = "quartz"             # quartz | applescript
notifications = true
```

Key names: `right_option`, `right_command`, `right_control`, `left_*`, `fn`,
`caps_lock`, `f13`…`f20`, or a raw virtual key code. Linux evdev names such as
`KEY_RIGHTALT` are accepted as aliases so one config can travel between machines.

The STT chain is `[stt_backend, stt_fallback]`; backends whose runtime is missing
(no PyObjC, no `pywhispercpp`) are tried last, and a backend that fails to load
(for example Speech Recognition permission denied) hands over to the next one
with a logged warning. whisper.cpp models are looked up exactly as on Linux
(`$UTTER_WHISPER_MODEL`, `$UTTER_MODELS_DIR`, `models/whisper/`).

## Platform matrix

**Works (by design, unit-tested on Linux, not yet run on a Mac)**

- platform detection and backend selection (`tests/platform/test_macos_detection.py`)
- the `[macos]` config section and its defaults
- two-key push-to-talk loop (`Utter.run_macos`) wired to the native STT chain,
  `type_text` for dictation and the normal router for assistant commands
- `open <url>`, `open -a <App>` / `open -b <bundle.id>` launching
- `pbpaste` clipboard, `afplay` sounds, `say` replies, notification banners

**Implemented against the documented APIs, untested on hardware**

- `SFSpeechRecognizer` one-shot file recognition with `requiresOnDeviceRecognition`
- Quartz `CGEventTap` press/release edge detection for modifier and regular keys
- Quartz `CGEventPost` chords and Unicode typing; AppleScript fallback
- Quartz mouse click / scroll events
- `NSWorkspace` + `AXUIElement` focused window, `CGWindowListCopyWindowInfo` list,
  `NSScreen` monitors
- `screencapture` + Retina point/pixel geometry handling in the vision tier
- runner socket peer credentials via `LOCAL_PEERCRED` / `LOCAL_PEERPID` and
  `proc_pidpath` (replaces `SO_PEERCRED` + `/proc`)
- the launchd agents and `macos/setup.sh`
- the Set up page: permission probes (`AVCaptureDevice`, `SFSpeechRecognizer`,
  `IOHIDCheckAccess`, `AXIsProcessTrustedWithOptions`,
  `CGPreflightScreenCaptureAccess`), System Settings deep links, `launchctl`
  status/start/stop mapping in the settings app
- the unsigned `.app` / `.dmg` produced by the `build-macos` CI job (a tester build
  without a release: `gh workflow run macos-dev-build.yml --ref <branch>`, then
  download the run artifact)

**Linux-only (no macOS equivalent yet)**

- the vocalinux bridge (`general.trigger = "bridge"` falls back to the native loop)
- niri compositor actions (`niri` rules such as "focus workspace 2") and
  workspace-aware window focusing (macOS activates the owning app instead)
- AT-SPI accessibility tree dumps and element clicks (`a11y` is `None` on macOS,
  so click-by-description goes straight to vision)
- MPRIS media control over D-Bus
- the Noctalia widget and on-screen display
- `ydotool`, `wtype`, `grim`, `wl-paste`, `keyd`, systemd units, the sandbox
  wrapper (`systemd-run` / `bwrap`; the runner runs unhardened on macOS)
- the Linux installer wizard and AppImage/deb/rpm packages
- Matugen desktop colours and the Noctalia-specific rows in the settings app

**Known gaps**

- Apple's one-shot recognition is capped at about one minute of audio.
- Window focus by id activates the app; raising one specific window of a
  multi-window app needs an AX `kAXRaiseAction` that is not wired yet.
- Intel Macs: the Python side should work, but no x86_64 `.dmg` is built.
- No Homebrew formula or signed app yet.

## Developing on Linux

The test suite stubs the Apple side: `UTTER_PLATFORM=darwin` forces the
detection so the dispatch points can be exercised without PyObjC.

```bash
scripts/verify.sh                                  # includes the platform test
.venv-agent/bin/python tests/platform/test_macos_detection.py
UTTER_PLATFORM=darwin .venv-agent/bin/python -c 'from utter.context import desktop; print(desktop.provider())'
```
