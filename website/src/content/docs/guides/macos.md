---
title: "macOS (experimental)"
description: "Running Utter on macOS: native Speech.framework and whisper.cpp voice, Quartz push-to-talk and injection, permissions, the [macos] config section, and what is still Linux-only."
---

Utter is a Linux-first project. A macOS port exists behind a small platform switch, using
native Apple frameworks instead of the Wayland tooling. It is **experimental and has not
yet been run on real Apple hardware**: the code was written and unit-tested on Linux with the
Apple frameworks stubbed out. Expect rough edges and please report what breaks.

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
| Typing and key chords | Quartz `CGEventPost`, AppleScript fallback |
| Focused app and window | `NSWorkspace` + Accessibility `kAXRaiseAction` for per-window raise |
| Screenshots, clipboard, sounds | `screencapture`, `pbpaste`, `afplay` |
| Background service | launchd user agents (`com.utter.assistant`, `com.utter.runner`) |
| Homebrew | `Formula/utter.rb` (CLI + service) and `Casks/utter.rb` (app) |

**Why not Voca?** VocaHQ makes [vocalinux](https://github.com/VocaHQ/vocalinux), which Utter
bridges on Linux, and [VocaMac](https://github.com/VocaHQ/vocamac) for macOS. VocaMac is a
compiled Swift menu-bar app with no socket or API for live transcripts, so it cannot be
bridged the way vocalinux is. Utter therefore uses Apple's own speech recognition with a
whisper.cpp fallback. If you prefer VocaMac's models, `stt_backend = "vocamac"` drives its
file-transcription CLI (untested).

## Install: drag and drop

1. Download `utter-gui_<ver>_aarch64.dmg` (Apple Silicon) or `utter-gui_<ver>_x86_64.dmg` (Intel)
   from the release page and drag **utter** to Applications. First launch: clear Gatekeeper once
   via `xattr -cr /Applications/utter.app` (or right-click → *Open* on macOS < 15).
2. Open it. The **Set up** page unpacks the Python runtime and the assistant that ship inside
   the app into `~/Library/Application Support/utter/`, starts the two launchd agents and
   then walks you through the permissions. No Homebrew, no Python, no terminal.

Updates work the same way: drop in the new app and Set up offers **Update**.

### Homebrew

- Install CLI + launchd service: `brew install --build-from-source Formula/utter.rb`
- Start background daemon: `brew services start utter`
- Install GUI app: `brew install --cask Casks/utter.rb`

Developers can run from a checkout instead: `macos/setup.sh` creates `.venv-macos`,
installs the `[macos]` extras and the launchd agents. The Linux installer (`install.sh`)
refuses to run on macOS and points you here.

## First run: the Set up page

On a Mac the settings app opens on **Set up** the first time. Like Raycast's onboarding it
lists each permission with a one-line reason, a **Grant access** button that triggers the
macOS prompt, an **Open System Settings** button that jumps to the exact pane, and a status
badge that re-checks live until everything is granted. The two launchd agents (plugin runner
and voice assistant) are shown underneath with a Start button.

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
stt_backend = "apple_speech"     # apple_speech | whisper_cpp | faster_whisper | vocamac
stt_fallback = "whisper_cpp"
speech_locale = "en-US"
on_device_only = true            # never send audio to Apple's servers
tts_backend = "say"              # say | avspeech | none
tts_voice = ""                   # `say -v ?` lists voices
tts_rate = 0
hotkey_backend = "quartz"        # quartz | pynput
dictation_key = "right_option"   # transcript is typed
assistant_key = "right_command"  # transcript is run as an action
injection = "quartz"             # quartz | applescript
notifications = true
```

Linux ignores this section entirely; the Linux sections are unchanged on macOS but the
`[macos]` keys win for voice and hotkeys.

## What works, what is Linux-only

- **Verified by CI:** automated matrix packaging of both Apple Silicon (`aarch64`) and
  Intel (`x86_64`) .dmg/.app bundles, fail-safe codesigning/notarization, platform detection tests.
- **Implemented against documented APIs (untested on real hardware):** push-to-talk with two keys,
  native speech recognition with pause-aware audio chunking (> 50s) and whisper.cpp runtime fallback,
  dictation typing, app and URL launching, window focus with AX window raising (`kAXRaiseAction`),
  clipboard, spoken replies, notifications, screenshots for the vision tier with Retina geometry handling,
  the plugin runner socket with peer credentials (`LOCAL_PEERCRED` / `LOCAL_PEERPID` and `proc_pidpath`),
  Homebrew formulas (`Formula/utter.rb` and `Casks/utter.rb`).
- **Linux-only:** the vocalinux bridge, niri compositor actions and workspace-aware
  focusing, AT-SPI accessibility clicks (macOS goes straight to vision), MPRIS media keys,
  the Noctalia widget and OSD, the sandbox wrapper, the Linux installer wizard, and the settings
  app's service controls (they call `systemctl`).
- **Needs real Mac hardware to confirm:** physical audio input, hardware key-tap edge detection,
  actual AX synthetic keystrokes, and real Screen Recording permission capture.

The complete matrix, with the per-module status, is in
[`docs/MACOS.md`](https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/MACOS.md).
