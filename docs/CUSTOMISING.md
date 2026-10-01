# Customising utter

How to configure the assistant: config files, hotkeys/PTT, STT, the LLM decision head,
vision, audio, sounds and services. Real paths and copy-pastable commands are used
throughout; anything not shipped in this repo is called out explicitly.

## Table of contents

1. [Config files & precedence](#1-config-files--precedence)
2. [Config sections](#2-config-sections)
3. [Hotkeys & push-to-talk](#3-hotkeys--push-to-talk)
4. [STT backends & the vocalinux bridge](#4-stt-backends--the-vocalinux-bridge)
5. [LLM / decision head](#5-llm--decision-head)
6. [Vision](#6-vision)
7. [Audio](#7-audio)
8. [Sounds](#8-sounds)
9. [Services (systemd user units)](#9-services-systemd-user-units)
10. [Profiles & apps](#10-profiles--apps)
11. [Safety](#11-safety)

---

## 1. Config files & precedence

The legacy assistant reads TOML via `utter/config.py::load_config()`
(`config.py`):

1. `~/.config/utter/config.toml` (honours `XDG_CONFIG_HOME`) — your override.
2. Fallback: `<repo>/config.default.toml` when the user file does not exist.

```bash
mkdir -p ~/.config/utter
cp config.default.toml ~/.config/utter/config.toml
```

Top-level `[daemon] log_level` is read separately (`load_config`, `config.py`); all other
sections map onto dataclasses in `utter/config.py`. Unknown keys are ignored by
`_merge` (`config.py`).

Separately, the **modular runner** has its own TOML config
(`runner/config.example.toml`, `config.m3.toml`) with `[[plugin]]` entries and
`[runner]` / `[socket]` / `[security]` / `[policy]` sections. See
[`docs/PLUGINS.md`](PLUGINS.md) and the comments in `runner/config.example.toml`.

---

## 2. Config sections

Defaults below are from `config.default.toml` (shipped) and the dataclasses in
`utter/config.py` (in-code fallback). Where they differ, the shipped file wins.

### `[general]`

| Key | Default (shipped) | Meaning |
|---|---|---|
| `trigger` | `hotkey` | `hotkey` = own evdev PTT; `bridge` = reuse vocalinux recognition |

(The in-code default is `bridge`; `config.default.toml` sets `hotkey`.)

### `[hotkey]`

| Key | Default | Meaning |
|---|---|---|
| `key` | `KEY_RIGHTCTRL` | evdev key held for the standalone PTT path |

### `[ptt]`

| Key | Default | Meaning |
|---|---|---|
| `dictation_key` | `KEY_F13` | held → transcript is **typed** |
| `assistant_key` | `KEY_INSERT` | held → transcript is **executed** as a command |

The defaults assume a common `keyd` remap (see [§3](#3-hotkeys--push-to-talk)).

### `[audio]`

| Key | Default | Meaning |
|---|---|---|
| `sample_rate` | `16000` | STT input rate |
| `channels` | `1` | mono |
| `device` | `""` | empty = default input |

### `[stt]`

| Key | Default | Meaning |
|---|---|---|
| `backend` | `faster_whisper` | `faster_whisper` \| `whisper_cpp` \| `none` |
| `model` | `distil-small.en` | backend-specific model name/path |
| `device` | `cuda` | faster-whisper device |
| `compute_type` | `float16` | faster-whisper compute type |

### `[router]`

| Key | Default | Meaning |
|---|---|---|
| `llm_fallback` | `true` | allow the fallback planner |
| `llm_base_url` | `http://127.0.0.1:8001/v1` | OpenAI-compatible endpoint |
| `llm_model` | `qwen3-4b` | served model name |
| `decide_threshold` | `0.5` | min probability for the decision head to act |

### `[vision]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | enable the T3 vision tier |
| `base_url` | `http://127.0.0.1:8000/v1` | UI-TARS vLLM endpoint |
| `model` | `uitars` | served model name |
| `target_width` | `1344` | screenshot resize width (latency lever) |
| `cuda_visible_devices` | `""` | Optional GPU index for the vision model (empty = default) |

### `[actions]`

| Key | Default | Meaning |
|---|---|---|
| `require_confirm` | `["send","submit","delete","purchase","pay","confirm order"]` | substrings in args that force confirmation |
| `click_duration_ms` | `40` | click press duration |

### `[daemon]`

| Key | Default | Meaning |
|---|---|---|
| `log_level` | `INFO` | daemon log level |

---

## 3. Hotkeys & push-to-talk

There are **two models**:

- **Standalone evdev PTT** (`trigger = "hotkey"`): the daemon runs its own
  `voice/hotkey.py` listener on `hotkey.key` and transcribes with the configured STT
  backend (`run_hotkey`, `daemon.py`).
- **vocalinux bridge** (`trigger = "bridge"` or `--bridge`): the daemon monkeypatches
  vocalinux's single injection choke point and drives vocalinux's own recognition
  from **two** dedicated keys (`voice/vocalinux_bridge.py`):
  - **dictation** (`ptt.dictation_key`) → text is typed normally;
  - **assistant** (`ptt.assistant_key`) → text is routed to utter and **never
    typed**.

Keys are evdev names (`KEY_F13`, `KEY_INSERT`, `KEY_RIGHTCTRL`, …), resolved by
`resolve_keycode` (`voice/hotkey.py`). The listener needs only membership in the `input` group; it
does **not** `grab()` the device (`hotkey.py`).

### keyd remap

This machine remaps two awkward keys at the kernel input layer via
`/etc/keyd/default.conf`:

```ini
[ids]
*

[main]
rightalt = insert
capslock = f13

[shift]
capslock = capslock
```

What it means:

- Physical **Caps Lock → F13** (dictation key) normally.
- Hold **Shift + Caps Lock** → the real **Caps Lock** (because of the `[shift]`
  layer). To toggle Caps Lock, hold Shift while tapping Caps Lock.
- Physical **Right Alt → Insert** (assistant key). Hold Right Alt to issue a command
  without typing it.

After editing, reload keyd (requires root):

```bash
sudo keyd reload
# or restart the service: sudo systemctl restart keyd
```

Then align `[ptt]` with the remapped names. The shipped defaults
(`dictation_key = "KEY_F13"`, `assistant_key = "KEY_INSERT"`) already match.

---

## 4. STT backends & the vocalinux bridge

`utter/voice/stt.py` supports (`stt.py`):

- **`whisper_cpp`** — via `pywhispercpp`; no GPU required; model stays resident.
- **`faster_whisper`** — optional dependency; GPU via `device`/`compute_type`.
- **`none`** — transcription disabled (e.g. the vocalinux bridge supplies text).

Model lookup for whisper.cpp (`_candidate_model_paths`, `stt.py`) checks, in order:

1. an explicit path / `$UTTER_WHISPER_MODEL`;
2. `$UTTER_MODELS_DIR` (prepended);
3. `<repo>/models/whisper`;
4. `~/.local/share/vocalinux/models/whispercpp`;
5. `~/.cache/whisper`.

The default whisper.cpp filename is `ggml-small.en.bin`
(`_DEFAULT_WHISPERCPP_NAME`, `stt.py`). If no local file exists and the configured name is a valid whisper.cpp
model, `pywhispercpp` will download it (`_resolve_whispercpp_model`, `stt.py`).

faster-whisper falls back to CPU/int8 if the requested device fails
(`Transcriber`, `stt.py`).

### vocalinux bridge

- Module: `utter/voice/vocalinux_bridge.py`.
- Enable with `trigger = "bridge"` in `[general]`, or run
  `python -m utter.daemon --bridge`.
- The bridge is installed by `daemon.run_bridge()` (`daemon.py`) and launched
  in practice via `scripts/utter-vocalinux.sh`, which sets `PYTHONPATH` to the
  repo and execs `python -m utter.daemon --bridge --config <repo>/config.default.toml`.
  That script is intended to replace the stock vocalinux launcher/autostart entry, and
  has hard-coded reference paths (edit them for your checkout).
- The bridge never types assistant utterances: it routes them to
  `Utter.handle_utterance` (wired in `run_bridge`, `daemon.py`).

---

## 5. LLM / decision head

Two things use the local planner endpoint on `:8001`:

- **`router.decide`** — the constrained "Jev" decision head
  (`utter/router/decide.py`, with the LLM transport in `utter/router/decide_llm.py`).
  It asks the model to pick a letter over
  fully-resolved candidates; `[router] decide_threshold` gates the choice. It tries,
  in order, `structured_outputs.choice` (vLLM ≥ 0.6), the legacy `guided_choice`, then
  a plain call (`_query`, `decide_llm.py`), and **fails open** to rules on any error.
- **`router.planner`** — the free-form JSON fallback, used only when rules and the
  decision head both fail (`utter/router/planner.py`). Disable with
  `[router] llm_fallback = false`.

Serve the planner (GPU 1, port 8001, model name `qwen3-4b`):

```bash
scripts/serve_planner.sh
# backgrounded with logs:
setsid bash -c 'scripts/serve_planner.sh > /tmp/vllm-planner.log 2>&1 &'
```

Model/port/GPU are overridable via `UTTER_PLANNER_MODEL_PATH`,
`UTTER_PLANNER_PORT`, `UTTER_PLANNER_SERVED_NAME`,
`UTTER_PLANNER_GPU_MEM_UTIL`, `UTTER_CUDA_VISIBLE_DEVICES`
(`serve_planner.sh:5-25,36-51`).

The default checkpoint is `models/Qwen3-4B-Instruct-2507-AWQ-4bit` (W4A16 AWQ).

---

## 6. Vision

The T3 tier grounds a description to a click point using **UI-TARS-2B-SFT** served by
vLLM:

```bash
scripts/serve_vision.sh
# backgrounded with logs:
setsid bash -c 'scripts/serve_vision.sh > /tmp/vllm-serve.log 2>&1 &'
```

- Endpoint `http://127.0.0.1:8000/v1`, model name `uitars`
  (`serve_vision.sh:4-6,36-43`).
- Overrides: `UTTER_VISION_MODEL_PATH`, `UTTER_VISION_PORT`,
  `UTTER_VISION_GPU_MEM_UTIL`, `UTTER_CUDA_VISIBLE_DEVICES`.
- The planner and vision servers share GPU 1 via `--gpu-memory-utilization`
  (vision 0.55, planner 0.30 — `serve_planner.sh:9-12`).

Client side (`utter/vision/`):

- `screenshot.py` captures with `grim` against niri and returns the logical
  `Rect` (`capture`, `screenshot.py`).
- `client.py::ground()` POSTs the resized screenshot (default width 1344, rounded to
  a multiple of 28 for Qwen2-VL) and parses UI-TARS 0–1000 normalized coordinates
  into screen pixels (`prepare_image` / `ground`, `client.py`).
- Env overrides: `UTTER_VISION_URL`, `UTTER_VISION_MODEL`,
  `UTTER_VISION_TARGET_WIDTH`, `UTTER_VISION_TIMEOUT` (`client.py`).
- Disable entirely with `[vision] enabled = false`; `click_element` then returns
  "vision disabled" after the a11y attempt (`_do_click_element`, `executor.py`).

---

## 7. Audio

utter uses PipeWire (via `sounddevice` for capture and `pactl`/`pw-play` for
routing/sounds). It does **not** ship a PipeWire configuration; the reference setup is
described here.

- **Capture**: the daemon opens an input stream at `[audio] sample_rate`/`channels`
  (`run_hotkey`, `daemon.py`). Keep an RNNoise-denoised source as the default input for
  clean dictation.
- **RNNoise source**: a filter-chain node conventionally configured under
  `~/.config/pipewire/pipewire.conf.d/` (not shipped in this repo). The reference
  script targets a source named **`DualSense_Denoised`**.
- **Defaults keeper**: `scripts/utter-audio-defaults.sh` loops every 10 s and
  re-asserts the default sink and source after PipeWire restarts
  (`utter-audio-defaults.sh:1-23`). It is idempotent and does not force volume
  (only unmutes when it (re)sets the sink). The reference sink is an HDMI passthrough:
  `alsa_output.pci-0000_01_00.1.hdmi-stereo`, and the source `DualSense_Denoised`.

Inspect your devices and change the two names at the top of the script:

```bash
pactl list short sinks
pactl list short sources
pactl get-default-sink
pactl get-default-source
```

The script assumes those names; if you use different hardware, edit `SINK` / `SRC`
(`utter-audio-defaults.sh:5-6`).

---

## 8. Sounds

`utter/sounds.py` synthesises three UI sounds on first use (stdlib only) into
`<repo>/sounds/` and plays them non-blockingly with `pw-play` (fallback `paplay`,
`_player`, `sounds.py`):

| Name | When |
|---|---|
| `start` | listening started |
| `detected` | a command was understood |
| `not_detected` | nothing matched |

The recipes/tones are in `_RECIPES` (`sounds.py`); generated files are
`sounds/start.wav`, `sounds/detected.wav`, `sounds/not_detected.wav`. Disable with:

```bash
export UTTER_SOUNDS=0
```

Playback runs detached (`start_new_session=True`) so it never blocks the daemon
(`play`, `sounds.py`).

---

## 9. Services (systemd user units)

The **repo ships two unit files**:

| Unit | File | Role |
|---|---|---|
| `utter.service` | `systemd/utter.service` | the daemon (`python -m utter.daemon`) |
| `ydotoold.service` | `systemd/ydotoold.service` | input injection daemon used by `ydotool` |

Both `PartOf=graphical-session.target` and `WantedBy=default.target`.

> `AGENTS.md` also references `utter-bridge`, `utter-vision`,
> `utter-planner` and `utter-audio-defaults` units. Those are **systemd user
> units on the reference machine and are not stored in this repo**; here, the
> vision/planner servers are started with `scripts/serve_*.sh` and the audio defaults
> keeper with `scripts/utter-audio-defaults.sh`. If you want them as units on
> your machine, wrap those scripts yourself.

Install / manage the shipped units (adjust the hard-coded
`WorkingDirectory`/`ExecStart` paths in `utter.service` for your checkout first —
they point at the reference path):

```bash
mkdir -p ~/.config/systemd/user
sed "s|@REPO@|$PWD|g" systemd/utter.service > ~/.config/systemd/user/utter.service
cp systemd/ydotoold.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service utter.service

# status / logs
systemctl --user status utter.service
journalctl --user -u utter.service -f

systemctl --user restart utter.service
systemctl --user disable --now utter.service
```

`ydotoold.service` runs `/usr/bin/ydotoold --socket-path=%t/.ydotool_socket
--socket-perm=0600`; clients set `YDOTOOL_SOCKET=%t/.ydotool_socket`, which utter
does automatically (`systemd/ydotoold.service:8-12`,
`_ydotool_env`, `utter/actions/keyboard.py`).

---

## 10. Profiles & apps

Adding or editing applications (profiles, aliases, app_ids, catalogs, niri phrases)
is covered in [`docs/APPS.md`](APPS.md) §6. Short version: create
`utter/profiles/<kind>_<id>.yaml`, set `id`/`name`/`aliases`/`launch`/`app_ids`/
`kind`, then run `scripts/gen_app_catalog.py` (and `scripts/gen_niri_phrases.py` if
you touched niri phrases).

Relevant config knobs here: `[router] llm_fallback` and `[actions] require_confirm`.

---

## 11. Safety

Read [`docs/TRUST.md`](TRUST.md) in full. For customisation the relevant points:

- **Confirmation list**: `[actions] require_confirm` is a list of substrings; if any
  appears in a step's args, confirmation is requested
  (`_needs_confirm`, `plugins/utter_py/plugin.py`). The default is
  `["send","submit","delete","purchase","pay","confirm order"]`.
- **Dangerous ops are off by default in the runner**: `action.terminal` and
  `action.input` require an explicit opt-in and still require confirmation
  (`runner/policy.py`). Enable in the *runner* config, not the legacy config:

  ```toml
  [policy]
  enabled_ops = ["action.terminal"]   # or "action.input"
  # disabled_ops = []
  ```

  See `runner/config.example.toml:30-35` and `config.m3.toml:21-24`.
- **Never weaken policy** by letting screen/a11y/OCR/clipboard content author action
  args — that is the `-32006` invariant enforced by the runner.
- The legacy assistant's dry-run is controlled by `UTTER_DRY_RUN`: the
  `utter_py` plugin defaults it **on**, so only `UTTER_DRY_RUN=0` touches the
  desktop (`_dry_run`, `plugins/utter_py/plugin.py`). Route-only testing without the
  plugin: `python -m utter.daemon --text "<cmd>" --dry-run`.
