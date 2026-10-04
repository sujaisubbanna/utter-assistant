# Utter on macOS

Utter is natively supported on Linux on Wayland (niri first) and on macOS. This
document describes the macOS support: what it uses, how to set it up, and what
works, plus what remains Linux-only.

> **Status: natively supported on Linux and macOS.** The macOS layer ships native
> Speech/Quartz backends, a native OSD overlay, launchd agents and a `.dmg` /
> `curl` install. Please report what breaks.

## Design

All macOS behaviour sits behind one small module, `utter/platform.py`
(`is_macos()` / `is_linux()`), and one package, `utter/macos/`. On Linux nothing
in `utter/macos/` is imported and every existing code path is unchanged.

| Concern | Linux (unchanged) | macOS backend |
|---|---|---|
| Push-to-talk | evdev / keyd | Quartz `CGEventTap` via PyObjC (`utter/macos/hotkey.py`), `pynput` fallback |
| Speech-to-text | faster-whisper / whisper.cpp | Apple `Speech.framework` (`SFSpeechRecognizer`, on-device) → local **whisper.cpp** fallback; optional **VocaMac** CLI backend |
| Spoken replies | plugin lane | `say` (default) or `AVSpeechSynthesizer` |
| Decision router / LLM | vLLM (`http://127.0.0.1:8001/v1`) | **Ollama** (`http://127.0.0.1:11434/v1`, Metal) default; LM Studio / llama.cpp |
| Vision / Grounding | UI-TARS (`http://127.0.0.1:8000/v1`) | **Ollama** VLM (`llama3.2-vision:11b`, Metal) default; LM Studio |
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

The owner's brief mentioned "voca macOS". **Voca** is VocaHQ's speech
tooling: a Linux dictation app plus the macOS
[VocaMac](https://github.com/VocaHQ/vocamac) menu-bar app. Utter is standalone
and does **not** integrate with either: its Linux voice path uses whisper.cpp or
faster-whisper directly, and its macOS path uses Apple's own Speech framework.
VocaMac is a Swift menu-bar app (macOS 14+, Apple Silicon only, AGPL-3.0,
`brew install --cask vocamac`) with WhisperKit / Parakeet / Apple Speech engines.

It is a fine dictation app, but it is **not usable as Utter's voice engine**:

- there is no `voca` / `voca-cli` package; VocaMac is a GUI app whose only
  headless mode is `VocaMac --transcribe-file <path> --json`;
- it exposes **no socket, API or IPC** to consume live transcripts, and it is
  compiled Swift, so it cannot be driven from Python;
- it is Apple Silicon only.

So the macOS support uses **macOS-native voice**: `Speech.framework` as the primary
STT (zero extra models, on-device, fast) with **whisper.cpp** as the offline
fallback and quality option, and `say` for TTS. VocaMac can still coexist as a
plain dictation app, and `[macos] stt_backend = "vocamac"` lets Utter use its
file-transcription CLI as a batch STT engine if you prefer its models.

## Requirements

- macOS 12+ (Speech on-device recognition and `screencapture` are older than
  that, but PyObjC 10 wheels target 12+). Both Apple Silicon (`aarch64`) and
  Intel (`x86_64`) Macs are supported; CI produces `.dmg` packages for both architectures.
- Python 3.12+ (`brew install python@3.12`).
- Python packages: `pip install -e '.[macos]'` installs `pyobjc-framework-Cocoa`,
  `-Quartz`, `-Speech`, `-AVFoundation`, `-ApplicationServices`, `sounddevice`,
  `numpy` and `pywhispercpp`.
## Metal-native Local Runtime (Ollama / LM Studio / llama.cpp)

On Linux, Utter runs background services assuming NVIDIA GPUs and CUDA (`device = "cuda"`, `cuda_visible_devices = "1"`, vLLM, UI-TARS). Macs have Apple Silicon with **Metal** and unified memory, without NVIDIA GPUs or CUDA.

Rather than bundling or shipping an ad-hoc inference server, Utter integrates with **ready-made, well-maintained macOS tools** that leverage Metal acceleration natively out of the box:

| Role | Tool | Why chosen | Default Endpoint & Model |
|---|---|---|---|
| **LLM / Decision Router** | **Ollama** ([ollama.com](https://ollama.com)) | First-class Metal acceleration, zero-config on Apple Silicon, standard Homebrew daemon (`brew services start ollama`), OpenAI-compatible `/v1` API | `http://127.0.0.1:11434/v1`<br>`qwen2.5:3b` |
| **Vision / Screen Grounding** | **Ollama** | Single daemon hosts both text and multimodal vision models, unified memory management | `http://127.0.0.1:11434/v1`<br>`llama3.2-vision:11b` |
| **STT (Voice Input)** | **Apple Speech** / **whisper.cpp** | Built-in zero-model STT via `SFSpeechRecognizer` (on-device); offline high-accuracy fallback via `whisper.cpp` with Metal acceleration | Built-in / `models/whisper/` |
| **TTS (Spoken Replies)** | System **`say`** | Built-in macOS speech synthesizer, native voices, zero setup | Built-in |

### Alternative Local Servers

Utter's macOS runtime resolver (`utter/runtime.py`) speaks standard OpenAI `/v1` HTTP endpoints:
- **LM Studio** ([lmstudio.ai](https://lmstudio.ai)): Start the local server (`lms server start` or via the GUI) on `http://127.0.0.1:1234/v1`. Configure `[macos.runtime] provider = "lm_studio"`.
- **llama.cpp** ([github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)): Start `llama-server` with `-ngl 99` (offload all layers to Metal) on `http://127.0.0.1:8080/v1`. Configure `[macos.runtime] provider = "llama_cpp"`.

### Setup & Recommended Models

1. **Install Ollama via Homebrew:**
   ```bash
   brew install ollama
   brew services start ollama
   ```
2. **Pull the recommended models:**
   ```bash
   # Decision Router (fast 3B parameter model, low latency)
   ollama pull qwen2.5:3b

   # Vision / Screen Grounding (UI element detection and visual reasoning)
   ollama pull llama3.2-vision:11b
   ```
   *(Note: For 8GB unified memory Macs, `qwen2.5:1.5b` and `qwen2.5-coder:1.5b` are lightweight alternatives. For 32GB+ Macs, `qwen2.5:7b` or `qwen2.5:14b` offer higher instruction accuracy.)*

### Detection & Graceful Degradation

Utter probes the local runtime before every request and during diagnostic checks (`utter doctor`, `utter capabilities`):
- **Metal GPU detection:** Probes system memory and Metal accelerator status via `system_profiler SPDisplaysDataType` and `sysctl hw.memsize`.
- **HTTP endpoint liveness:** Fast stdlib HTTP probe (`0.5s` timeout) against `/v1/models`.
- **Model availability check:** Verifies whether the configured model (`qwen2.5:3b`, `llama3.2-vision:11b`) is actually loaded/pulled.
- **Graceful degradation:** If Ollama is not installed or stopped, Utter reports structured status (`"stopped"` or `"not_installed"`) with actionable instructions (e.g. `brew services start ollama` or `ollama pull <model>`) rather than crashing or hanging.


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

## Install: drag and drop

1. Download `utter-gui_<ver>_aarch64.dmg` (Apple Silicon) or
   `utter-gui_<ver>_x86_64.dmg` (Intel) from the release page.
2. Drag **utter** to Applications. Until the release is signed (below), macOS
   reports the downloaded app as **"damaged"**: that is Gatekeeper refusing an
   unsigned, quarantined app, not a bad download. Clear the flag once:
   `xattr -cr /Applications/utter.app` (or download with `curl`, which never
   sets it). On macOS 15+ right-click → *Open* no longer bypasses this.
3. Open it. The first-run wizard runs first (see [ONBOARDING.md](ONBOARDING.md));
   once that is done, the macOS-only **Settings** tab installs the rest by itself:
   - it unpacks the Python runtime and the assistant that ship inside the app
     (`Contents/Resources/runtime.tar.gz`, ~150 MB: a relocatable CPython from
     python-build-standalone with numpy, sounddevice, PyObjC and pywhispercpp)
     into `~/Library/Application Support/utter/runtime/`;
   - it writes and starts the two launchd agents (`com.utter.runner`,
     `com.utter.assistant`) in `~/Library/LaunchAgents/`;
   - it then walks the permissions (next section). Nothing to type.

No Homebrew, no Python install, no terminal. Updating is the same: drop the new
app in, open it, and the **Settings** tab offers **Update** when the bundled
runtime is newer than the installed one. To remove everything: delete the app,
`~/Library/Application Support/utter`, `~/Library/LaunchAgents/com.utter.*.plist`
and `~/.config/utter`.

Where things end up:

| What | Where |
|---|---|
| Python runtime + core | `~/Library/Application Support/utter/runtime/{python,core}` |
| launchd agents | `~/Library/LaunchAgents/com.utter.{runner,assistant}.plist` (run `utter.app/Contents/MacOS/utter --runner|--daemon`) |
| logs | `~/Library/Logs/utter/{runner,utter}.log` |
| config | `~/.config/utter/config.toml` (same file as Linux) |
| permission status | `~/Library/Application Support/utter/permissions.json` |

### Homebrew (CLI + launchd or Cask)

The recommended path is the official tap:

```bash
brew tap sujaisubbanna/utter
brew install utter          # CLI + launchd service
brew install --cask utter   # GUI app
```

- `utter` installs the Python assistant into Homebrew's `libexec`, links
  `utter` and `utter-runner` into `$(brew --prefix)/bin`, and provides launchd
  service management (`brew services start utter`).
- `utter` cask downloads and installs `utter.app` from GitHub releases
  (`brew install --cask utter`).

To track the latest `main` instead of the tagged release, build from a checkout:

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
brew install --build-from-source Formula/utter.rb
brew install --cask Casks/utter.rb
```

### From a source checkout (developers)

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
macos/setup.sh              # .venv-macos + pip install -e '.[macos]' + launchd agents
macos/setup.sh --no-agent   # just the virtualenv and ~/.config/utter/config.toml

.venv-macos/bin/python -m utter.daemon --text "open youtube" --dry-run
.venv-macos/bin/python -m utter.daemon            # hold Right ⌘ and speak
macos/setup.sh --uninstall                        # removes only the launchd agents
```

A GUI built from source has no bundled runtime; it finds the checkout through
`UTTER_REPO`, `~/Library/Application Support/utter/core` (a symlink
`macos/setup.sh` creates) or `~/utter-assistant`. `install.sh` (the Linux
wizard) refuses to run on macOS and points here.

### Signing and notarization

The CI workflows sign and notarize the app automatically when complete, valid
Apple Developer credentials exist: `APPLE_CERTIFICATE` (base64 `.p12`),
`APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY` (`Developer ID Application: …`),
`APPLE_ID`, `APPLE_PASSWORD` (app-specific password) and `APPLE_TEAM_ID`.
The workflow validates these credentials before building. If they are absent,
empty, or malformed, the build is **fail-safe**: it automatically produces an
unsigned `.app`/`.dmg` and clearly logs that it is unsigned. A missing or invalid
secret never fails the build. Without notarization, users need the `xattr -cr` step above.

### Stable ad-hoc identity (TCC)

An ad-hoc / linker signature has a designated requirement of `cdhash H"…"`, which
changes on **every** rebuild. TCC keys privacy grants to that requirement, so all
granted permissions are lost (or never attributed) after each build. The fix is to
re-sign the app and the bundled runtime ad-hoc with an explicit identifier-based DR
— no certificate needed:

```bash
# runtime payload inside runtime.tar.gz (run by build-macos-runtime.sh)
scripts/sign-macos.sh runtime <runtime-dir>

# the app bundle after `pnpm tauri build`
scripts/sign-macos.sh app gui-tauri/src-tauri/target/release/bundle/macos/utter.app
```

`scripts/build-macos-runtime.sh` calls the runtime mode just before it packs
`runtime.tar.gz`; `scripts/build-macos-app.sh` runs `pnpm tauri build` and then the
app mode. Both use `--sign - --identifier org.utter.settings
--requirements '=designated => identifier "org.utter.settings"'`; confirm with
`codesign -d -r- <path>` (it should print the identifier, not `cdhash H"…"`).
After installing/updating, re-register and reset the grants so they bind to the new
(now stable) identity:

```bash
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREGISTER" -f /Applications/utter.app
for s in Microphone SpeechRecognition ListenEvent Accessibility ScreenCapture; do
    tccutil reset "$s" org.utter.settings
done
# reopen utter and grant the prompts again
```

Do **not** set `signingIdentity` in `tauri.conf.json`: no Developer ID certificate is
assumed on this machine, and the ad-hoc stable DR above is what TCC needs.

### How the bundle is built

`scripts/build-macos-runtime.sh` (run by CI on `macos-14`) downloads the
`install_only_stripped` CPython 3.12 from astral-sh/python-build-standalone,
copies the core (`utter/`, `runner/`, `assistant/`, `plugins/`, `protocol/`,
`macos/`, configs), `pip install`s the wheels, verifies the imports, and writes
`gui-tauri/src-tauri/resources/runtime.tar.gz` + `runtime.version`.
`tauri.macos.conf.json` adds both as bundle resources, so Linux builds are not
affected. `gui-tauri/src-tauri/src/macos_setup.rs` does the unpack/agents on
the user's Mac.

## First run: permissions in Settings

On a Mac the settings app starts with the first-run wizard
([ONBOARDING.md](ONBOARDING.md)); once that is finished the app opens on the
macOS-only **Settings** tab, which stays in the sidebar. Its first row installs
the bundled runtime and agents (see above); the rest is permissions. It is
modelled on how Raycast onboards: one screen that lists every permission, says
why it is needed, has a **Grant access** button that triggers the system prompt,
an **Open System Settings** button that deep-links to the exact pane
(`x-apple.systempreferences:com.apple.preference.security?Privacy_…`), and a
status badge that re-checks every few seconds until everything is green. Below
the permissions it shows the two launchd agents (plugin runner, voice assistant)
with a Start button.

**One identity: utter.app.** macOS attaches privacy permissions to the
*responsible process*. If launchd ran the Python binary directly, the prompts
would say "Python 3.12", the grants would belong to that binary, and a probe
spawned by the settings window would be attributed to utter.app instead, so the
page would keep saying "not granted" after you had granted it. To avoid that,
the launchd agents launch **the app binary itself** in a headless mode
(`utter.app/Contents/MacOS/utter --daemon` / `--runner`), which supervises the
bundled Python as its child and forwards signals. The prompts therefore show
"utter" with its icon, and the daemon, the Settings tab's probe
(`python -m assistant macos-permissions --json`) and the prompts all share one
grant. The daemon repeats the probe at startup and writes
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
| Settings | permissions onboarding + launchd agents (macOS only) |
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
stt_backend = "whisper_cpp"      # apple_speech | whisper_cpp | faster_whisper | vocamac
stt_fallback = "apple_speech"    # tried when the primary fails to load
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

[macos.runtime]
provider = "ollama"              # ollama | lm_studio | llama_cpp | custom
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5:3b"
vision_provider = "ollama"       # ollama | lm_studio | llama_cpp | custom
vision_base_url = "http://127.0.0.1:11434/v1"
vision_model = "llama3.2-vision:11b"
```

Key names: `right_option`, `right_command`, `right_control`, `left_*`, `fn`,
`caps_lock`, `f13`…`f20`, or a raw virtual key code. Linux evdev names such as
`KEY_RIGHTALT` are accepted as aliases so one config can travel between machines.

The STT chain is `[stt_backend, stt_fallback]`; backends whose runtime is missing
(no PyObjC, no `pywhispercpp`) are tried last, and a backend that fails to load
(for example Speech Recognition permission denied) hands over to the next one
with a logged warning. whisper.cpp models are looked up exactly as on Linux
(`$UTTER_WHISPER_MODEL`, `$UTTER_MODELS_DIR`, `models/whisper/`).

For Apple Speech, a resolved `[stt] language` (see
[CUSTOMISING §4](CUSTOMISING.md#spoken-language-stt--tts)) becomes the
`SFSpeechRecognizer` locale — for example `[stt] language = "de-DE"` or `auto`
picking up `LANG=de_DE.UTF-8` gives `de-DE`. When nothing resolves,
`speech_locale` is used, then `en-US`.

On macOS, `[router]` and `[vision]` automatically resolve to the Metal-native endpoints configured in `[macos.runtime]` (defaulting to local Ollama) rather than the Linux-only CUDA / vLLM / UI-TARS defaults.

## Platform matrix

**Verified by CI (automated packaging and platform tests)**

- GitHub Actions matrix build producing both Apple Silicon (`aarch64`) and
  Intel (`x86_64`) `.dmg` installers and `.app.tar.gz` bundles
- Fail-safe signing: signed and notarized when Apple secrets exist, otherwise
  producing unsigned bundles with clear diagnostic reporting
- Platform detection and backend selection unit tests (`tests/platform/test_macos_detection.py`, `tests/platform/test_macos_runtime.py`)
- Python core tarball assembly and bundled runtime structure (`scripts/build-macos-runtime.sh`)

**Works (by design, verified on macOS)**

- platform detection and backend selection (`tests/platform/test_macos_detection.py`, `tests/platform/test_macos_runtime.py`)
- the `[macos]` and `[macos.runtime]` config sections and resolution to Ollama / LM Studio / llama.cpp
- platform-aware router and vision client resolution avoiding CUDA/NVIDIA on Darwin
- detection and graceful degradation for stopped Ollama services or missing models in CLI `capabilities` and `doctor`
- two-key push-to-talk loop (`Utter.run_macos`) wired to the native STT chain,
  `type_text` for dictation and the normal router for assistant commands
- `open <url>`, `open -a <App>` / `open -b <bundle.id>` launching
- `pbpaste` clipboard, `afplay` sounds, `say` replies, notification banners
- speech pause-aware audio chunking (`split_audio_chunks`) for long audio (> 50s)
- runtime fallback from `apple_speech` to `whisper_cpp` when speech recognition fails

**Native macOS backends (verified on macOS)**

- `SFSpeechRecognizer` one-shot file recognition with `requiresOnDeviceRecognition`
  and natural pause chunking for audio exceeding ~50 seconds
- Window focus with specific window raising via Accessibility `kAXRaiseAction` (`ax_raise_window`)
- Quartz `CGEventTap` press/release edge detection for modifier and regular keys
- Quartz `CGEventPost` chords and Unicode typing; AppleScript fallback
- Quartz mouse click / scroll events
- `NSWorkspace` + `AXUIElement` focused window, `CGWindowListCopyWindowInfo` list,
  `NSScreen` monitors
- `screencapture` + Retina point/pixel geometry handling in the vision tier, with
  backing scale factor adjustment and graceful permission error reporting
- runner socket peer credentials via `LOCAL_PEERCRED` (128-byte buffer, version 0 validation) / `LOCAL_PEERPID` and
  `proc_pidpath` (replaces `SO_PEERCRED` + `/proc`)
- the launchd agents and `macos/setup.sh` (idempotent, reversible)
- the Settings tab: permission probes (`AVCaptureDevice`, `SFSpeechRecognizer`,
  `IOHIDCheckAccess`, `AXIsProcessTrustedWithOptions`,
  `CGPreflightScreenCaptureAccess`), System Settings deep links, `launchctl`
  status/start/stop mapping in the settings app, with one permission identity (`utter.app`)
- Homebrew formulas (`Formula/utter.rb` for CLI/launchd service, `Casks/utter.rb` for .app)

**Linux-only (no macOS equivalent yet)**

- niri compositor actions (`niri` rules such as "focus workspace 2") and
  workspace-aware window focusing (macOS activates the owning app instead)
- AT-SPI accessibility tree dumps and element clicks (`a11y` is `None` on macOS,
  so click-by-description goes straight to vision)
- MPRIS media control over D-Bus
- the Noctalia widget (macOS uses a native OSD overlay instead)
- `ydotool`, `wtype`, `grim`, `wl-paste`, `keyd`, systemd units, the sandbox
  wrapper (`systemd-run` / `bwrap`; the runner runs unhardened on macOS)
- the Linux installer wizard and AppImage/deb/rpm packages
- Matugen desktop colours and the Noctalia-specific rows in the settings app

**Known gaps**

- Hardware-specific behaviour (microphone capture, physical Quartz event taps, Accessibility
  synthetic typing, Screen Recording) is verified on macOS; edge cases can still differ per machine.
- Metal inference throughput depends on the Mac's unified memory and the Ollama / LM Studio model chosen.
- Signed and notarized releases require Apple Developer credentials; without them the
  `.app`/`.dmg` build is fail-safe and ships unsigned.

## Developing on Linux

The test suite stubs the Apple side: `UTTER_PLATFORM=darwin` forces the
detection so the dispatch points can be exercised without PyObjC.

```bash
scripts/verify.sh                                  # includes the platform test
.venv-agent/bin/python tests/platform/test_macos_detection.py
UTTER_PLATFORM=darwin .venv-agent/bin/python -c 'from utter.context import desktop; print(desktop.provider())'
```
