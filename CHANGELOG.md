# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Sleep when idle.** Utter now falls asleep by itself after `[sleep] idle_minutes`
  (default 15) without Utter activity: a push-to-talk key, a spoken command or a wake.
  Desktop input elsewhere does not count, and the timer waits while Utter is listening
  or running a command. Automatic sleep uses the same path as the spoken trigger, so
  holding a push-to-talk key wakes it the same way. New `[sleep]` keys `on_idle` and
  `idle_minutes`, with a switch and a minutes field on the General page (en + es).

## [0.1.1] - 2026-10-01
- **Experimental macOS support.** A small platform module (`utter/platform.py`) selects
  native backends on Darwin while leaving every Linux code path untouched: Apple
  `Speech.framework` speech-to-text with a local whisper.cpp fallback (and an optional
  VocaMac file-transcription backend), `say`/`AVSpeechSynthesizer` spoken replies, Quartz
  event-tap push-to-talk keys, Quartz/AppleScript key and text injection, `NSWorkspace` +
  Accessibility focused-window context, `screencapture` screenshots, `pbpaste` clipboard,
  `afplay` sounds and notification banners. New `[macos]` config section, `macos/setup.sh`
  with a launchd agent, `docs/MACOS.md` and a docs-site page with the platform matrix.
- Release workflow: a `build-macos` job on `macos-14` that builds the macOS core tarball and
  an **unsigned** `.app`/`.dmg` of the settings app and attaches them to the release
  (`sha256sums-macos.txt`). The Linux job is unchanged.
- macOS drag-and-drop install: `utter.app` ships a relocatable Python 3.12 runtime plus the
  assistant core (`scripts/build-macos-runtime.sh`, `tauri.macos.conf.json`), and the Set up
  page unpacks it into `~/Library/Application Support/utter/runtime`, installs and starts the
  launchd agents, and offers Update when a newer app is opened. No terminal needed.
- Settings app on macOS: a **Set up** onboarding page (Raycast-style) that lists the
  Microphone, Speech Recognition, Input Monitoring, Accessibility and Screen Recording
  permissions with live status, a Grant button that triggers the system prompt from the
  daemon's own Python, and deep links into System Settings; launchd-backed service rows and
  log tail; macOS variants of the Voice and Spoken replies pages that edit `[macos]`.
  New `assistant macos-permissions` CLI. Linux builds are unchanged (`platform_info`).
- `tests/platform/test_macos_detection.py` (run by `scripts/verify.sh` on Linux) covers the
  detection, config defaults, STT chain selection, key tables, chord parsing, dispatch and
  the permissions table/CLI.

## [0.2.0] - 2026-10-01

## [0.1.1] - 2026-10-01

### Added
- **Documentation site** built with Astro Starlight and published to GitHub Pages —
  introduction, install, configuration, apps, models, plugins, trust & safety,
  troubleshooting, FAQ, plus CLI and architecture reference — with full-text search.
  The hosted installer stays at `/install.sh`, so the one-line install is unchanged.
- The app icons ship in the core tarball, install into the hicolor icon theme, and are
  used by the desktop entry.
- A desktop shortcut for the settings app (`utter-gui.desktop`) with its icon, so it
  appears in the application launcher.

### Changed
- The README installation instructions are split into three clear paths:
  clone-and-install, remote (`curl | bash`) and build-from-source.
- Settings app: the status and General polls run every 15 s instead of 4–5 s, never
  overlap a run that is still in flight, and pause entirely while the window is in the
  background — the status probe spawns the `assistant` CLI on every tick.
- Settings app: scrolling no longer repaints the entire panel on every frame. The panel
  shadow and rounding moved off the scroll container onto a static wrapper, the status
  pulse animates opacity instead of `box-shadow`, and long lists skip layout and paint
  for off-screen rows.
- The demo video is re-encoded from 1080p / 5.0 MB to 720p / 1.5 MB for smoother
  playback.

### Fixed
- The launcher (`utter-gui`) resolves symlinks, so the copy installed on `PATH` — and the
  optional Noctalia widget's left-click — actually starts the app instead of trying to
  build inside `~/.local/bin`.
- `install.sh` no longer produces a desktop entry with a generic system icon.

### Infrastructure
- The release workflow builds AppImage, deb and rpm bundles plus the core tarball from a
  `v*` tag and attaches them to the GitHub Release.
- GitHub Pages serves the documentation site and the installer (`/install.sh`) together.

[0.1.1]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.1
