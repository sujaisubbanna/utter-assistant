# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-02

### Added
- **Multilingual speech.** The spoken language for speech-to-text and spoken
  replies is now a setting, independent of the settings-app UI language. It
  resolves `auto` from the system locale (`LC_ALL`/`LC_MESSAGES`/`LANG`) and is
  threaded through both Whisper backends and the macOS `SFSpeechRecognizer`
  locale. Configuring a non-English language with an English-only (`.en`) model
  logs a clear warning instead of silently transcribing the wrong language.
- **Linux text-to-speech.** Spoken replies now work off macOS: espeak-ng,
  espeak or speech-dispatcher (`spd-say`) are used when present, honouring
  `[tts] enabled`, `engine`, `language` and `voice`. No new dependency, and no
  engine means a silent no-op, never a crash.
- **Localization.** The settings app ships 10 locales (en, es, de, fr, it, pt,
  zh, ja, ko, ru) and the installer gained a locale-file layer with the same
  set. English is the only inline locale; every other language is an opt-in
  download chosen during install or from settings — nothing is auto-downloaded.
  Translations are machine-drafted and unreviewed for now.
- **Crowdin integration (build-time only).** Sources are exported to JSON,
  translators work in Crowdin, and `scripts/i18n_crowdin.py` turns the results
  back into the shipped locale files. Crowdin is never a runtime dependency and
  the app never contacts it.
- **Installer language step** and a set of **installer UI upgrades**: an amber
  gradient wordmark, a short animated reveal, and a live per-component task
  list. Everything degrades to plain ASCII with no escape codes when piped,
  under `NO_COLOR`/`TERM=dumb`, or with `--yes`/`--dry-run`.
- **Target any app by name**: `<app> type …`, `<app> press …`, `<app> pause`
  and `close <app>` act on a named app instead of the focused window. On
  Wayland this is a brief focus round-trip (measured ~38 ms same-workspace);
  macOS posts keys to the target process directly. Displayed on the Safety page
  with platform-appropriate options.

### Changed
- **The Vocalinux bridge was removed.** Utter is self-sufficient: its own evdev
  push-to-talk, local microphone capture and Whisper. The optional waveform
  (OSD) is now driven directly by the native voice loop.
- Docs, README and the docs site updated throughout (multilingual, what Utter
  stores, app targeting, VRAM/latency).

### Fixed
- The settings app no longer renders a black window when built with a bare
  `cargo build`; the launcher and docs use `pnpm tauri build`, which embeds the
  frontend.
- `assistant doctor`/`status` explain a missing runner socket and how to start
  it instead of leaking `[Errno 2] No such file or directory`.
- Several already-merged features verified and hardened: runner op registration,
  macOS `CGEventPostToPid` background input, and installer dependency fixes.

## [0.1.11] - 2026-10-01

### Internal
- Split `utter/router/rules.py` `plan()` into an ordered matcher chain (with a new
  golden-order test) and `utter/router/decide.py` into `decide_llm.py` and
  `decide_candidates.py`. Routing output is unchanged.

## [0.1.10] - 2026-10-01

### Internal
- Consolidated GPU/CPU/RAM probing into `utter/hardware.py`, shared by `utter.runtime`,
  `assistant recommend` and the `utter` CLI, and split `probe_runtime()` per platform.
  Output shapes and `--json` fields are unchanged.

## [0.1.9] - 2026-10-01

### Changed
- **Removed the legacy GTK4 settings app** (`gui/`). The Tauri v2 app (`gui-tauri/`) is the
  only settings UI; the matugen palette template moved to `gui-tauri/theme/`.
- **Installer installs the right GUI runtime.** The dead `gtk4`/`libadwaita` packages are
  replaced by `webkit2gtk-4.1` and `libsoup-3.0` (what Tauri v2 needs); AT-SPI accessibility
  is documented as an optional extra.

### Internal
- Split the KWin and D-Bus compositor backends into focused modules behind the same facade.
- Consolidated the test harness into `tests/_harness/`, wired `tests/m5` into the suite,
  added a CI workflow that runs `scripts/verify.sh`, and added guard tests for the runner
  stdlib-only rule, the provenance invariant and the installer unit.

## [0.1.8] - 2026-10-01

### Internal
- Replaced the `utter` CLI dispatch chain with a command-handler table, and split the
  `assistant` model pull into plan/transfer/materialize with one download loop. The CLI
  envelope, `--json` shape and exit codes are unchanged.

## [0.1.7] - 2026-10-01

### Internal
- Split `runner/host.py` into `runner/config.py` and `runner/handles_api.py`. The RPC
  surface, wire format and error codes are unchanged; `runner/**` stays stdlib-only.

## [0.1.6] - 2026-10-01

### Changed
- **Installer rebuilt around a proper terminal UI.** `install.sh` gained one UI layer
  (aligned fields, section banners, a step indicator, spinners and download progress) with
  a plain fallback: it is styled only on a real terminal and honours `NO_COLOR`,
  `TERM=dumb` and `UTTER_UI=auto|gum|plain` (uses `gum` if already installed, never
  downloads it). The script is reorganised into labelled sections.

### Fixed
- **`--uninstall` no longer deletes without confirmation.** It used to remove installed
  components even when piped or run without `--yes`; it now lists what it would remove and
  refuses unless `--yes` (or `--dry-run`).
- **The installed systemd unit actually starts.** `install.sh` now substitutes `@REPO@`
  instead of copying the unit verbatim, which left a literal `@REPO@` that systemd could
  not resolve.
- **The assistant plugin runs on a clean system.** The installer provisions an interpreter
  venv with PyYAML and requests and repoints the plugin and `config.m3.toml` entrypoints at
  it, so it no longer depends on a bare `python`.
- **arm64 installs no longer fail on the GUI step.** With no arm64 GUI asset published, the
  GUI is skipped with a clear note instead of aborting.
- **Secondary installer scripts' `--help` no longer leaks `set -euo pipefail`.**

### Removed
- Machine-specific defaults and comments: a hardcoded GPU index and author GPU model, and
  literal `/run/user/<uid>` paths, are now generic.

## [0.1.5] - 2026-10-01

### Fixed
- **The M3 verification no longer drives the live desktop.** `scripts/verify.sh` used to open
  YouTube in the real browser on every run (via `tests/m3/verify_m3.py`). The real action is
  now opt-in (`--real-action` or `UTTER_M3_REAL_ACTION=1`); the default run is fully dry-run.
- **`utter version` reports the real version.** It returned a hardcoded `0.1.0`; it now
  resolves from `pyproject.toml` (or the installed metadata).
- **macOS drives the real assistant and honours sleep/idle.** The launchd agent and the
  settings app point at `config.m3.toml` instead of the fake echo config, and the
  push-to-talk path now starts idle-sleep and wakes the assistant, like Linux.

### Documentation
- README restructured with a new **"Use it without voice"** section that presents the full
  headless CLI (`utter`, `python -m assistant`), and `docs/CLI.md` now states it needs no
  microphone.

## [0.1.4] - 2026-10-01

### Fixed
- **`assistant` and `runner` are importable outside the repo root.** The distribution now
  ships the `assistant`, `runner` and `plugins` packages (previously only `utter*`), so
  `python -m assistant` and `python -m runner` work from any directory.
- **Linux runner entrypoint uses `python3`.** `config.m3.toml` no longer depends on a bare
  `python`, which a clean Ubuntu 24.04 does not provide.

## [0.1.3] - 2026-10-01

### Added
- **macOS Metal-native local runtime.** A platform-aware resolution layer (`utter/runtime.py`)
  selects the local inference runtime for LLM, vision, STT and TTS: on Apple Silicon it
  prefers Ollama, LM Studio or llama.cpp with Metal acceleration and avoids CUDA/NVIDIA
  assumptions, while Linux defaults are unchanged. `assistant doctor` reports detected
  hardware and suggested profiles, and the settings Diagnostics page shows the detected
  runtime. Docs: `docs/MACOS.md`. Tests: `tests/platform/test_macos_runtime.py`.

## [0.1.2] - 2026-10-01

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
- **macOS support.** A platform layer (`utter/platform.py`) selects native
  backends on Darwin while leaving every Linux path untouched: Apple `Speech.framework`
  speech-to-text with a whisper.cpp fallback (and an optional VocaMac file-transcription
  backend), `say`/`AVSpeechSynthesizer` replies, Quartz event-tap push-to-talk keys,
  Quartz/AppleScript key and text injection, `NSWorkspace` + Accessibility window context,
  `screencapture` screenshots, `pbpaste` clipboard, `afplay` sounds and notification banners.
  New `[macos]` config section, `macos/setup.sh` with launchd agents, and a Raycast-style
  **Set up** onboarding page that lists the Microphone, Speech Recognition, Input Monitoring,
  Accessibility and Screen Recording permissions with live status and deep links. A
  `build-macos` CI job produces `.app`/`.dmg` bundles (arm64 and x86_64) plus a macOS
  core tarball, and a Homebrew formula/cask is included. Docs: `docs/MACOS.md`.
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
  actions), and macOS is natively supported.
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

[0.1.11]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.11
[0.1.10]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.10
[0.1.9]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.9
[0.1.8]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.8
[0.1.7]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.7
[0.1.6]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.6
[0.1.5]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.5
[0.1.4]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.4
[0.1.3]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.3
[0.1.2]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.2
[0.1.1]: https://github.com/sujaisubbanna/utter-assistant/releases/tag/v0.1.1
