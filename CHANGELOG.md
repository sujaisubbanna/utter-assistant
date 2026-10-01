# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] - 2026-10-01

### Fixed
- **`assistant` and `runner` are importable outside the repo root.** The distribution now
  ships the `assistant`, `runner` and `plugins` packages (previously only `utter*`), so
  `python -m assistant` and `python -m runner` work from any directory.
- **Linux runner entrypoint uses `python3`.** `config.m3.toml` no longer depends on a bare
  `python`, which a clean Ubuntu 24.04 does not provide.

[0.1.3]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.3

### Added
- **macOS Metal-native local runtime.** A platform-aware resolution layer (`utter/runtime.py`)
  selects the local inference runtime for LLM, vision, STT and TTS: on Apple Silicon it
  prefers Ollama, LM Studio or llama.cpp with Metal acceleration and avoids CUDA/NVIDIA
  assumptions, while Linux defaults are unchanged. `assistant doctor` reports detected
  hardware and suggested profiles, and the settings Diagnostics page shows the detected
  runtime. Docs: `docs/MACOS.md`. Tests: `tests/platform/test_macos_runtime.py`.

[0.1.2]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.2

### Added
- **KDE Plasma (KWin) support.** A compositor abstraction (`utter/context/compositor.py`,
  `utter/context/backends/{niri,kwin,fallback}.py`) detects the session (`XDG_CURRENT_DESKTOP`,
  `KDE_FULL_SESSION`, `DESKTOP_SESSION`, `XDG_SESSION_DESKTOP`, `NIRI_SOCKET`) and picks a
  backend; niri keeps its original code path. The KWin backend talks to Plasma over D-Bus with
  argv lists (`org.kde.KWin`, `org.kde.KWin.VirtualDesktopManager`, `org.kde.kwin.Scripting`,
  `org.kde.kglobalaccel`, `org.kde.klipper`), uses `kdotool` when present, Spectacle or the XDG
  portal for screenshots and `ydotool` for typing. Missing capabilities return a structured
  "unsupported" result instead of failing. New config: `[general] compositor = "auto"` and a
  `[kwin]` section. The Troubleshooting page shows the detected compositor, the active backend
  and which capabilities are available (en + es). Docs: `docs/PLASMA.md` and the "KDE Plasma"
  guide on the site. Probe: `python -m utter.context.compositor`.
- **Sleep when idle.** Utter now falls asleep by itself after `[sleep] idle_minutes`
  (default 15) without Utter activity: a push-to-talk key, a spoken command or a wake.
  Desktop input elsewhere does not count, and the timer waits while Utter is listening
  or running a command. Automatic sleep uses the same path as the spoken trigger, so
  holding a push-to-talk key wakes it the same way. New `[sleep]` keys `on_idle` and
  `idle_minutes`, with a switch and a minutes field on the General page (en + es).
- **An agent-facing CLI.** `utter` now drives desktop actions directly — `assistant`,
  `dictation`, `listen`, `speak`, `transcribe` — with discovery (`capabilities`, `schema`,
  `apps`, `actions`, `profiles`, `status`, `doctor`, `version`) and settings/custom-command
  editing. Every command takes `--json` with a stable `utter.cli/v1` envelope, machine output
  on stdout and diagnostics on stderr, a documented exit-code and error-code contract, and a
  packaged Draft 2020-12 JSON Schema (`utter/data/cli.schema.json`). `--dry-run` previews a
  route without executing; acting requires `--confirm`. See `docs/CLI.md`.
- **macOS support (experimental).** A platform layer (`utter/platform.py`) selects native
  backends on Darwin while leaving every Linux path untouched: Apple `Speech.framework`
  speech-to-text with a whisper.cpp fallback (and an optional VocaMac file-transcription
  backend), `say`/`AVSpeechSynthesizer` replies, Quartz event-tap push-to-talk keys,
  Quartz/AppleScript key and text injection, `NSWorkspace` + Accessibility window context,
  `screencapture` screenshots, `pbpaste` clipboard, `afplay` sounds and notification banners.
  New `[macos]` config section, `macos/setup.sh` with launchd agents, and a Raycast-style
  **Set up** onboarding page that lists the Microphone, Speech Recognition, Input Monitoring,
  Accessibility and Screen Recording permissions with live status and deep links. A
  `build-macos` CI job produces an **unsigned** `.app`/`.dmg` (arm64 and x86_64) plus a macOS
  core tarball, and a Homebrew formula/cask is included. Docs: `docs/MACOS.md`.
  **Untested on real Apple hardware.**
- **A documentation site** (Astro Starlight) published to GitHub Pages — introduction, install,
  configuration, apps, models, plugins, trust & safety, KDE Plasma, macOS, troubleshooting, FAQ,
  CLI and architecture reference — with full-text search. The hosted installer stays at
  `/install.sh`, so the one-line install is unchanged.
- **A demo page** with a real video player.

### Changed
- The README installation instructions are split into three clear paths: clone-and-install,
  remote (`curl | bash`) and build-from-source.
- Platform documentation now reflects reality: **niri and KDE Plasma (KWin) are first-class**,
  other Wayland compositors get partial support (dictation, typing, launching; no window
  actions), and macOS is experimental.
- Settings app: the status and General polls run every 15 s instead of 4–5 s, never overlap a
  run that is still in flight, and pause entirely while the window is in the background.
- Settings app: scrolling no longer repaints the entire panel on every frame (the panel shadow
  moved off the scroll container, the status pulse animates opacity, and long lists skip
  off-screen layout/paint).
- The demo video is re-encoded from 1080p / 5.0 MB to 720p / 1.5 MB, and its thumbnail is the
  settled splash screen.

### Fixed
- The launcher (`utter-gui`) resolves symlinks, so the copy installed on `PATH` — and the
  optional Noctalia widget's left-click — actually starts the app.
- `install.sh` ships and installs the app icons and writes a desktop entry that uses them.
- macOS packaging no longer fails when the Apple signing secrets are absent: signing and
  notarization are skipped and an unsigned artifact is produced instead.
- The CLI's `--dry-run` no longer hangs: a dry-run bypasses the idle/sleep machinery entirely.
- `.gitignore` matches `.venv`/`.venv-agent` as symlinks, not only directories.

### Infrastructure
- The release workflow builds AppImage, deb and rpm bundles plus the core tarball from a `v*`
  tag and attaches them to the GitHub Release; a separate macOS job adds the `.dmg` and macOS
  core tarball.
- GitHub Pages serves the documentation site and the installer (`/install.sh`) together.

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
