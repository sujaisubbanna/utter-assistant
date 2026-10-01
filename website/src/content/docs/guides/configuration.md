---
title: "Configuration"
description: "Every knob in ~/.config/utter/config.toml, hotkeys and push-to-talk, speech backends, the decision head and vision models, audio, sounds, services and profiles."
---

Utter is configured by a single TOML file. The settings app edits the same file (it preserves
your comments), so you can use whichever you prefer.

:::note[macOS]
On a Mac the voice, hotkey and spoken-reply settings live in a separate `[macos]` section and
the settings app edits that instead. See [macOS (experimental)](/guides/macos/).
:::

## Config files and precedence

1. `~/.config/utter/config.toml` (honours `XDG_CONFIG_HOME`) is your override.
2. When that file does not exist, the shipped `config.default.toml` from the repository is used.

Start from the shipped default:

```bash
mkdir -p ~/.config/utter
cp config.default.toml ~/.config/utter/config.toml
```

Unknown keys are ignored, so a typo silently does nothing. Check the key names against the
tables below.

Separately, the **modular runner** has its own TOML (`runner/config.example.toml` in the repo)
with `[[plugin]]` entries and `[runner]`, `[socket]`, `[security]` and `[policy]` sections. That
file decides which plugins run and what they may do; see [Plugin protocol](/plugins/) and
[Trust and safety](/guides/trust-and-safety/).

## Config sections

Defaults are those shipped in `config.default.toml`.

### `[general]`

| Key | Default | Meaning |
|---|---|---|
| `trigger` | `hotkey` | `hotkey` runs Utter's own evdev push-to-talk listener; `bridge` reuses vocalinux's recognition |

### `[hotkey]`

| Key | Default | Meaning |
|---|---|---|
| `key` | `KEY_RIGHTCTRL` | evdev key held for the standalone push-to-talk path |

### `[ptt]`

| Key | Default | Meaning |
|---|---|---|
| `dictation_key` | `KEY_F13` | held: the transcript is **typed** into the focused field |
| `assistant_key` | `KEY_INSERT` | held: the transcript is **executed** as a command |

### `[audio]`

| Key | Default | Meaning |
|---|---|---|
| `sample_rate` | `16000` | speech-to-text input rate |
| `channels` | `1` | mono |
| `device` | `""` | empty = default input |

### `[stt]`

| Key | Default | Meaning |
|---|---|---|
| `backend` | `faster_whisper` | `faster_whisper`, `whisper_cpp` or `none` |
| `model` | `distil-small.en` | backend-specific model name or path |
| `device` | `cuda` | faster-whisper device |
| `compute_type` | `float16` | faster-whisper compute type |

### `[router]`

| Key | Default | Meaning |
|---|---|---|
| `llm_fallback` | `true` | allow the free-form fallback planner |
| `llm_base_url` | `http://127.0.0.1:8001/v1` | OpenAI-compatible endpoint for the decision head and planner |
| `llm_model` | `qwen3-4b` | served model name |
| `decide_threshold` | `0.5` | minimum probability for the decision head to act |

### `[vision]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | enable the vision tier (T3) |
| `base_url` | `http://127.0.0.1:8000/v1` | UI-TARS vLLM endpoint |
| `model` | `uitars` | served model name |
| `target_width` | `1344` | screenshot resize width; the biggest latency lever |
| `cuda_visible_devices` | `"1"` | GPU pin for the vision server |

### `[actions]`

| Key | Default | Meaning |
|---|---|---|
| `require_confirm` | `["send","submit","delete","purchase","pay","confirm order"]` | substrings in a step's args that force confirmation |
| `click_duration_ms` | `40` | how long a simulated click is held |
| `preferred_browser` | `""` | profile or app id for web actions; empty = the browser you are looking at, else any open one, else the desktop default |

### `[sleep]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | allow the sleep phrase |
| `trigger` | `["go to sleep"]` | phrases that put Utter to sleep (assistant mode only) |
| `services` | `["utter-vision", "utter-planner"]` | user units stopped on sleep |
| `unload_speech` | `true` | also unload the speech model |

### `[osd]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | the optional Noctalia on-screen display; `UTTER_OSD=0` disables it at runtime |
| `position` | `bottom_center` | where the panel appears |
| `dismiss_ms` | `1200` | how long the result stays visible |
| `stream` | `true` | best-effort live transcript while you speak |
| `stream_interval_ms` | `700` | how often the live transcript updates |
| `window_s` | `6` | audio window for live decoding |

See [Noctalia widget and OSD](/guides/noctalia/).

### `[daemon]`

| Key | Default | Meaning |
|---|---|---|
| `log_level` | `INFO` | daemon log level |

## Hotkeys and push-to-talk

There are **two trigger models**:

- **Standalone evdev push-to-talk** (`trigger = "hotkey"`). The daemon runs its own key
  listener and transcribes with the configured speech backend.
- **vocalinux bridge** (`trigger = "bridge"` or `--bridge`). The daemon hooks vocalinux's single
  text-injection point and drives vocalinux's own recognition from **two** dedicated keys:
  the **dictation key** types text normally, the **assistant key** routes the text to Utter and
  **never** types it.

Keys are evdev names (`KEY_F13`, `KEY_INSERT`, `KEY_RIGHTCTRL`, ...). The listener only needs
your user to be in the `input` group. It does **not** grab the device, so the key keeps working
for everything else.

### keyd remap

The shipped defaults (`KEY_F13` and `KEY_INSERT`) assume a kernel-level remap with
[keyd](https://github.com/rvaiya/keyd) that turns two awkward physical keys into those codes.
This is one way to do it, in `/etc/keyd/default.conf`:

```ini
[ids]
*

[main]
rightalt = insert
capslock = f13

[shift]
capslock = capslock
```

- Physical **Caps Lock** becomes **F13** (dictation key).
- **Shift + Caps Lock** is the real Caps Lock, thanks to the `[shift]` layer.
- Physical **Right Alt** becomes **Insert** (assistant key). Hold Right Alt to issue a command
  without typing it.

Reload keyd after editing (needs root):

```bash
sudo keyd reload
# or: sudo systemctl restart keyd
```

Then make sure `[ptt]` matches the remapped names. If you do not want a remap, pick any key your
keyboard already has and change `[ptt]` on the Voice page instead.

## Speech-to-text backends

Three backends are supported:

- **`whisper_cpp`**, via `pywhispercpp`. No GPU required; the model stays resident.
- **`faster_whisper`**, an optional dependency with GPU support through `device` and
  `compute_type`. Falls back to CPU / int8 if the requested device fails.
- **`none`**, transcription disabled (for example when the vocalinux bridge supplies the text).

Model lookup for whisper.cpp checks, in order: an explicit path or `$UTTER_WHISPER_MODEL`,
`$UTTER_MODELS_DIR`, `<repo>/models/whisper`, `~/.local/share/vocalinux/models/whispercpp`,
then `~/.cache/whisper`. The default whisper.cpp filename is `ggml-small.en.bin`. If no local
file exists and the configured name is a valid whisper.cpp model, `pywhispercpp` downloads it.

### vocalinux bridge

Enable with `trigger = "bridge"` in `[general]`, or run `python -m utter.daemon --bridge`. The
bridge never types assistant utterances; it routes them to Utter. The launcher script
`scripts/utter-vocalinux.sh` is meant to replace vocalinux's own autostart entry and contains
hard-coded reference paths you should edit for your checkout.

## The decision head and the planner

Two things use the local language-model endpoint on port `8001`:

- **The constrained decision head** asks the model to pick one letter from a list of fully
  resolved candidates. `[router] decide_threshold` gates the choice. It tries vLLM's
  `structured_outputs.choice`, then the legacy `guided_choice`, then a plain call, and **fails
  open to rules** on any error.
- **The free-form planner** is the JSON fallback used only when rules and the decision head both
  fail. Disable it with `[router] llm_fallback = false`.

Serve the planner with vLLM (GPU 1, port 8001, served name `qwen3-4b`):

```bash
scripts/serve_planner.sh
# backgrounded with logs:
setsid bash -c 'scripts/serve_planner.sh > /tmp/vllm-planner.log 2>&1 &'
```

Override model, port and GPU with `UTTER_PLANNER_MODEL_PATH`, `UTTER_PLANNER_PORT`,
`UTTER_PLANNER_SERVED_NAME`, `UTTER_PLANNER_GPU_MEM_UTIL` and `UTTER_CUDA_VISIBLE_DEVICES`. The
default checkpoint is a 4-bit AWQ build of Qwen3-4B-Instruct. Any OpenAI-compatible server
(Ollama, llama.cpp) works too; point `llm_base_url` and `llm_model` at it from the **LLM** page.

## Vision

The vision tier grounds a description to a click point using **UI-TARS** served by vLLM:

```bash
scripts/serve_vision.sh
# backgrounded with logs:
setsid bash -c 'scripts/serve_vision.sh > /tmp/vllm-serve.log 2>&1 &'
```

- Endpoint `http://127.0.0.1:8000/v1`, model name `uitars`.
- Overrides: `UTTER_VISION_MODEL_PATH`, `UTTER_VISION_PORT`, `UTTER_VISION_GPU_MEM_UTIL`,
  `UTTER_CUDA_VISIBLE_DEVICES`.
- The planner and vision servers can share one GPU through vLLM's memory utilisation flags
  (vision 0.55, planner 0.30 by default).

On the client side, Utter captures with `grim`, resizes the screenshot to `target_width`
(rounded to a multiple of 28 for the model) and converts the model's 0 to 1000 normalised
coordinates back to screen pixels. Client-side environment overrides: `UTTER_VISION_URL`,
`UTTER_VISION_MODEL`, `UTTER_VISION_TARGET_WIDTH`, `UTTER_VISION_TIMEOUT`.

Disable vision entirely with `[vision] enabled = false`. "Click ..." steps then stop after the
accessibility attempt and report that vision is disabled.

## Audio

Utter uses PipeWire: `sounddevice` for capture, `pactl` and `pw-play` for routing and sounds.
It does **not** ship a PipeWire configuration.

- **Capture** opens an input stream at `[audio] sample_rate` and `channels`. Keep a denoised
  source (for example an RNNoise filter chain) as the default input for clean dictation.
- **Defaults keeper**: `scripts/utter-audio-defaults.sh` loops every 10 seconds and re-asserts
  the default sink and source after PipeWire restarts. It is idempotent, never forces volume, and
  only unmutes when it (re)sets the sink. Edit the `SINK` and `SRC` names at the top of the
  script for your hardware.

```bash
pactl list short sinks
pactl list short sources
pactl get-default-sink
pactl get-default-source
```

## Sounds

Three UI sounds are synthesised on first use (standard library only) and played without blocking
with `pw-play` (fallback `paplay`):

| Name | When |
|---|---|
| `start` | listening started (one tone per mode) |
| `detected` | a command was understood |
| `not_detected` | nothing matched |

Disable them with `UTTER_SOUNDS=0`.

## Services

The repository ships these unit files:

| Unit | File | Role |
|---|---|---|
| `utter-runner.service` | `install/utter-runner.service` | the modular runner (plugin supervisor) |
| `utter.service` | `systemd/utter.service` | the legacy daemon (`python -m utter.daemon`) |
| `ydotoold.service` | `systemd/ydotoold.service` | input-injection daemon used by `ydotool` |

All are user units bound to `graphical-session.target`. The legacy daemon unit has placeholder
paths you substitute for your checkout:

```bash
mkdir -p ~/.config/systemd/user
sed "s|@REPO@|$PWD|g" systemd/utter.service > ~/.config/systemd/user/utter.service
cp systemd/ydotoold.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service utter.service

systemctl --user status utter.service
journalctl --user -u utter.service -f
```

`ydotoold.service` runs `ydotoold` with a per-user socket; Utter sets `YDOTOOL_SOCKET` for its
clients automatically.

## Profiles and apps

Adding or editing applications (profiles, aliases, compositor app ids, catalogs, niri phrases) is
covered in [Apps and actions](/guides/apps-and-actions/). The short version: create
`~/.config/utter/profiles/<kind>_<id>.yaml` or edit the app on the **App actions** page, then
regenerate the catalog with `scripts/gen_app_catalog.py`.

## Safety knobs

Read [Trust and safety](/guides/trust-and-safety/) in full. The configuration points are:

- **Confirmation list.** `[actions] require_confirm` is a list of substrings; if any appears in
  a step's args, confirmation is requested.
- **Dangerous ops are off by default in the runner.** Terminal commands and raw input need an
  explicit opt-in in the *runner* config and still require confirmation:

  ```toml
  [policy]
  enabled_ops = ["action.terminal"]   # or "action.input"
  ```

- **Never weaken policy** by letting screen, accessibility, OCR or clipboard content author
  action arguments. The runner enforces this invariant and rejects such requests.
- **Dry run.** The `utter_py` plugin defaults `UTTER_DRY_RUN` to on; only `UTTER_DRY_RUN=0`
  touches the desktop. Route-only testing: `python -m utter.daemon --text "<cmd>" --dry-run`.
