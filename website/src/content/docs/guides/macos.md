---
title: "macOS (experimental)"
description: "Running Utter on macOS: native Speech.framework and whisper.cpp voice, Quartz push-to-talk and injection, permissions, the [macos] config section, and what is still Linux-only."
---

Utter is a Linux-first project. A macOS port exists behind a small platform switch, using
native Apple frameworks instead of the Wayland tooling. It is **experimental and has not
yet been run on real Apple hardware**: the code was written and unit-tested on Linux with the
Apple frameworks stubbed out. Expect rough edges and please report what breaks.

:::caution[Unsigned app]
The macOS settings app on the release page (`utter-gui_<ver>_aarch64.dmg`) is **not
code-signed or notarised**. On first launch right-click → *Open*, or run
`xattr -dr com.apple.quarantine /Applications/utter.app`. Apple Silicon only.
:::

## What it uses

| Concern | macOS backend |
|---|---|
| Push-to-talk | Quartz `CGEventTap` (PyObjC), `pynput` fallback |
| Speech-to-text | Apple `Speech.framework` on-device, then local **whisper.cpp** |
| Spoken replies | `say` or `AVSpeechSynthesizer` |
| Typing and key chords | Quartz `CGEventPost`, AppleScript fallback |
| Focused app and window | `NSWorkspace` + Accessibility |
| Screenshots, clipboard, sounds | `screencapture`, `pbpaste`, `afplay` |
| Background service | a launchd user agent |

**Why not Voca?** VocaHQ makes [vocalinux](https://github.com/VocaHQ/vocalinux), which Utter
bridges on Linux, and [VocaMac](https://github.com/VocaHQ/vocamac) for macOS. VocaMac is a
compiled Swift menu-bar app with no socket or API for live transcripts, so it cannot be
bridged the way vocalinux is. Utter therefore uses Apple's own speech recognition with a
whisper.cpp fallback. If you prefer VocaMac's models, `stt_backend = "vocamac"` drives its
file-transcription CLI (untested).

## Install

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
macos/setup.sh                 # .venv-macos, pip install -e '.[macos]', launchd agent
.venv-macos/bin/python -m utter.daemon --text "open youtube" --dry-run
```

You need Python 3.12+ and `brew install portaudio`. Then grant the daemon's python binary
these permissions under *System Settings → Privacy & Security*: **Microphone**, **Speech
Recognition**, **Input Monitoring**, **Accessibility** and **Screen Recording**.

The Linux installer (`install.sh`) refuses to run on macOS and points you here.

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

- **Expected to work:** push-to-talk with two keys, native speech recognition with a
  whisper.cpp fallback, dictation typing, app and URL launching, clipboard, spoken replies,
  notifications, screenshots for the vision tier, the plugin runner socket.
- **Linux-only:** the vocalinux bridge, niri compositor actions and workspace-aware
  focusing, AT-SPI accessibility clicks (macOS goes straight to vision), MPRIS media keys,
  the Noctalia widget and OSD, the sandbox wrapper, the installer wizard, and the settings
  app's service controls (they call `systemctl`).
- **Known gaps:** Apple's one-shot recognition stops after about a minute of audio; focusing
  raises the owning app rather than one specific window; no Intel build; no signed app.

The complete matrix, with the per-module status, is in
[`docs/MACOS.md`](https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/MACOS.md).
