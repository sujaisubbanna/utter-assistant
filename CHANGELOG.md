# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.9] - 2026-10-05

### Added
- **Production runner config.** `config.runner.toml` replaces the M3 dev config as
  the shipped default and runs with `UTTER_DRY_RUN=0`, so the modular runner
  performs real actions. `config.m3.toml` is kept for the test suites.
- **On-demand vision and planner models.** Vision (UI-TARS) and the decision
  planner (`Qwen3-4B-Instruct-2507-AWQ-4bit`) are sharded and cannot come from the
  single-file store; `scripts/install_inference.sh` provisions them (vLLM plus the
  models) and the installer's perception step offers to run it.
- **Install the engine from the GUI.** AppImage/deb/rpm-only installs get an
  "Install the engine" card with the official one-liner, Copy, and Open-in-terminal.

### Fixed
- The core tarball now ships the inference/serve scripts the perception step needs.

## [0.4.8] - 2026-10-05

### Fixed
- **Fresh installs no longer fail on GitHub's API rate limit.** The installer
  resolved the newest release only through the unauthenticated GitHub API, which
  can return `403` on shared IPs and aborted the install. It now prefers the API
  (authenticating with `GITHUB_TOKEN`/`GH_TOKEN` when present) and falls back to
  the `releases/latest` redirect, which has no API quota.

## [0.4.7] - 2026-10-05

### Added
- **UI sounds can target a specific output device.** Set `[sounds] sink` in
  `config.toml` (or `UTTER_SOUND_SINK`) to a PipeWire sink name so the
  activation/notification sounds play on your speakers or headset instead of the
  system default (which can be a virtual streaming sink).

### Fixed
- **The Homebrew formula installs and runs the voice daemon.** It now installs
  the macOS runtime extra (PyObjC, sounddevice, numpy, pywhispercpp) and starts
  `python -m utter.daemon` instead of the non-existent `utter --daemon`.

## [0.4.6] - 2026-10-05

### Fixed
- **Voice commands no longer crash the daemon.** A free-form command reached the
  LLM planner with a `RouterConfig`, but `resolve_router`/`resolve_vision` only
  recognised that type on macOS and raised `AttributeError` on Linux, which the
  daemon re-raised and died. The resolvers now accept it on every platform, and
  a routing/executor error ends that one utterance instead of the service.

## [0.4.5] - 2026-10-05

### Fixed
- **Accessibility/context detection works on remote installs.** The installer
  built the agent venv from Homebrew Python without system site-packages, so
  `gi`/Atspi were missing and the assistant could not read the focused element.
  It now prefers a gi-capable interpreter (`/usr/bin/python3`), builds the venv
  with `--system-site-packages`, recreates an old isolated venv, and installs
  `python-gobject`/`at-spi2-core`.
- **Push-to-talk no longer wedges.** Releasing the PTT key could deadlock the
  daemon (`stop()` held the capture lock while PortAudio waited on the audio
  callback), leaving it stuck "listening" until a restart. Key-up now completes,
  a missed release is bounded by a watchdog, and a transcription failure is
  non-fatal.
- **The on-screen display no longer runs a second Whisper model.** Live partial
  decoding is off by default (waveform and final text remain); together with a
  thread cap this removes the CPU load that made the desktop and settings UI
  stutter.
- **The settings UI scrolls smoothly** (offscreen rows skipped, rows memoized,
  unchanged polls no longer re-render) and **support bundles** now record a real
  Python interpreter, so `doctor.json`/`status.json` are no longer empty.

## [0.4.4] - 2026-10-05

### Fixed
- **A fresh install now works.** Three defects kept voice inert: the installer
  never installed the voice daemon (`utter.service`) or its runtime
  dependencies, push-to-talk crashed the daemon on audio devices that do not
  accept 16 kHz, and the wizard skipped the speech model entirely on `--yes`.
  The installer now starts the daemon, bundles the Linux voice runtime (numpy,
  evdev, sounddevice, pywhispercpp), pulls the curated speech model
  (`ggml-small.en.bin`) by default, and negotiates a capture rate the device
  supports, resampling to 16 kHz for Whisper.
- **Hugging Face vision links no longer pretend to work.** The UI-TARS repos are
  sharded and cannot be fetched by the single-file model store, so their "Get
  it" pull is gone. Vision is provisioned with `scripts/install_inference.sh`,
  and a failed pull now explains the sharded-repo case.

## [0.4.3] - 2026-10-05

### Fixed
- **Hugging Face model pulls now verify and succeed.** Every `hf:` download
  failed with a "sha256 mismatch" after fetching the whole file, because the
  model store compared it against Hugging Face's Xet dedup hash instead of the
  file's real content hash. A fresh install could never obtain a speech or
  vision model, so both were inert. Pulls now read the true content hash
  (`X-Linked-ETag`) and verify.

## [0.4.2] - 2026-10-05

### Added
- **"You need a model" dialog.** If you try to use speech or screen vision with no
  model installed, the settings app now explains what's needed, recommends one for
  your hardware, and offers to download it — instead of silently doing nothing.

### Fixed
- **A fresh install now works out of the box.** The model store was not connected
  to anything: `assistant models pull` downloaded to a store nothing read, so an
  installed Utter did nothing. Speech recognition now loads from the store, the
  inference serve scripts resolve models from it, `assistant recommend` prints the
  exact pullable source, and the installer pulls curated defaults (English speech
  ~466 MB; vision ~4.5 GB, sized for a 24 GB card).
- **`assistant doctor` no longer reports a false version drift** on a fresh install
  (the runner version is now single-sourced rather than hardcoded).
- **Installer polish:** the banner now reads **UTTER** (the wordmark glyphs were
  malformed), and a proper **Utter** entry is added to your application menu, so it
  can be launched without the command line.

## [0.4.1] - 2026-10-05

### Fixed
- **The installer now works against a published release.** Two bugs blocked a
  fresh install and are fixed: checksum verification rejected every asset because
  the release checksums carry a `./` prefix, and the config step never wrote
  `~/.config/utter/config.toml` (an argument-shift bug in the installer's command
  runner, which affected 21 call sites) while still reporting success. A failed
  step now reports failure instead of `ok`, and a regression test covers both.

## [0.4.0] - 2026-10-05

### Added
- **Optional local dictation formatting.** Clean up dictated text (punctuation,
  capitalisation, filler removal) with the local model before it is typed. Off by
  default (`[dictation] format = "local"` to enable); reuses the existing local
  LLM; never loses your words — the raw transcript is typed if formatting fails.
- **Push-to-talk dictation now works on Linux.** The `[ptt]` dictation and
  assistant keys are bound on Linux (previously macOS only), with the same
  key-down cue as macOS and the clipboard fallback when the input can't be found.
- **Text-field detection (foundation).** A platform-neutral probe that finds the
  focused text field and enumerates candidates, with an explicit status for why
  nothing was found. Groundwork for choosing where dictation goes.

### Changed
- **Model store moved** to `$XDG_DATA_HOME/utter-models`, outside the install tree,
  with a one-time migration. Fixes an uninstall that could delete downloaded models;
  uninstall now keeps models unless `--purge`.

### Fixed
- **Plugin sandbox hardening is now actually applied** (`[security] enforce`):
  a private `/tmp`, a default-deny device cgroup, read-only system paths, and
  declared read/write paths. `seccomp`/`landlock` are not applied and are no
  longer claimed.
- **Settings-app controls now do what they say** — safety toggles, confirmation,
  accessibility, decision-head and plugin enablement were writing config keys
  nothing read; they are wired (or removed where they had no effect). TTS "Play",
  the speech-backend list and the onboarding app step work on a fresh install.
- **Documentation corrected against the code** across the repo and the docs site
  (compatibility, installer, security, model paths, and more).

## [0.3.0] - 2026-10-03

### Added
- **First-run onboarding wizard.** A mandatory, guided setup shows on first launch
  and walks through language, permissions, app actions, models and a first action.
  Steps are resumable and skippable, the settings shell can re-run it, and all 10
  shipped locales are covered.
- **Per-app opt-in.** No app-specific capability is enabled by default any more.
  A curated set (Spotify, Firefox, Chrome, VS Code, Files) is preselected during
  onboarding; everything else is off until you turn it on per app. A disabled app
  is ignored entirely — no launch, focus, close, shortcut, media or typed target.
  Sites and URLs, push-to-talk dictation and generic media keys keep working, and
  CLI agents are never gated.

### Changed
- The settings sidebar **"Set up" tab is renamed to "Settings"** (the page stays
  as it was).
- Onboarding step content is **vertically centred** and uses a slightly wider
  column, so tall windows no longer look mostly empty.

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
