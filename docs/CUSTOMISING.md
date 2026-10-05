# Customising utter

How to configure the assistant: config files, hotkeys/PTT, STT, the LLM decision head,
vision, audio, sounds and services. Real paths and copy-pastable commands are used
throughout; anything not shipped in this repo is called out explicitly.

## Table of contents

1. [Config files & precedence](#1-config-files--precedence)
2. [Config sections](#2-config-sections)
3. [Hotkeys & push-to-talk](#3-hotkeys--push-to-talk)
4. [STT backends](#4-stt-backends)
5. [LLM / decision head](#5-llm--decision-head)
6. [Vision](#6-vision)
7. [Audio](#7-audio)
8. [Sounds](#8-sounds)
9. [Services (systemd user units)](#9-services-systemd-user-units)
10. [Profiles & apps](#10-profiles--apps)
11. [Safety](#11-safety)
12. [Sleep, wake and the OSD](#12-sleep-wake-and-the-osd)
13. [App-targeted actions & background input](#13-app-targeted-actions--background-input)

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
(`config.runner.toml` in production, `config.m3.toml` for the M3 verification,
and `runner/config.example.toml` as a template) with `[[plugin]]` entries and
`[runner]` / `[socket]` / `[security]` / `[policy]` sections. The session wrapper
resolves `$UTTER_CONFIG` → `config.runner.toml` → `config.m3.toml` →
`runner/config.example.toml`. See [`docs/PLUGINS.md`](PLUGINS.md) and the
comments in `config.runner.toml`.

---

## 2. Config sections

Defaults below are from `config.default.toml` (shipped) and the dataclasses in
`utter/config.py` (in-code fallback). Where they differ, the shipped file wins.

### `[general]`

| Key | Default (shipped) | Meaning |
|---|---|---|
| `trigger` | `hotkey` | `hotkey` = Utter's own evdev push-to-talk |

`trigger` is retained for config compatibility but is currently **ignored** by the code.

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
| `language` | `auto` | spoken language (`auto`, `en`, `en-GB`, `de-DE`, …); independent of the UI language |

### `[tts]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Linux spoken replies on/off (macOS still uses `[macos]`) |
| `engine` | `auto` | Linux engine: `auto` (piper → espeak-ng → espeak → spd-say), `none`, or a name to force |
| `language` | `auto` | spoken language, same rules as `[stt] language` |
| `voice` | `""` | engine voice: espeak name (`en-gb`, `de`) or a Piper `.onnx` model/path; empty derives it from `language` |

On macOS spoken replies still use `[macos] tts_backend` / `tts_voice` / `tts_rate`; `[tts]` is
the Linux path (see [§4](#4-stt-backends)).

### `[dictation]`

| Key | Default | Meaning |
|---|---|---|
| `format` | `off` | `off` = type the raw transcript; `local` = clean it up first with the local LLM |

`format = "local"` runs a **reformat-only** pass over the dictation transcript before it is typed:
punctuation, capitalisation and filler removal ("um", "uh"). It **never changes meaning**, answers
the text or translates it, and it applies to the **dictation lane only** — assistant commands are
routed verbatim and are never formatted. It reuses the model already used for routing
(`[router] llm_base_url` on Linux, `[macos.runtime]` on macOS). It is **off by default**, has a
5 s timeout, and on any failure (server down, timeout, empty/odd reply) the **raw transcript is
typed instead** — your words are never lost. Unknown values are treated as `off`.

### `[router]`

| Key | Default | Meaning |
|---|---|---|
| `llm_fallback` | `true` | allow the fallback planner |
| `llm_base_url` | `http://127.0.0.1:8001/v1` | OpenAI-compatible endpoint |
| `llm_model` | `qwen3-4b` | served model name |
| `decision_head_enabled` | `true` | Jev-style constrained decision head; off = deterministic rules only |
| `decide_threshold` | `0.5` | min probability for the decision head to act |

### `[perception]`

| Key | Default | Meaning |
|---|---|---|
| `accessibility_enabled` | `true` | read buttons/labels from the accessibility tree before taking a screenshot |

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
| `confirm_enabled` | `true` | ask before discretionary actions matching `require_confirm`; off leaves the runner's always-on confirmations |
| `require_confirm` | `["send","submit","delete","purchase","pay","confirm order"]` | substrings in args that force confirmation |
| `click_duration_ms` | `40` | parsed but **unused** (legacy; the GUI control was removed and no code reads it) |

### `[daemon]`

| Key | Default | Meaning |
|---|---|---|
| `log_level` | `INFO` | daemon log level |

---

## 3. Hotkeys & push-to-talk

Utter runs its own **standalone evdev PTT**: the daemon's `voice/hotkey.py` listener
watches `hotkey.key`, and `voice/stt.py` transcribes the captured audio
(`run_hotkey`, `daemon.py`). The two dedicated `[ptt]` keys are also handled by
utter's own listener:

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

## 4. STT backends

`utter/voice/stt.py` supports (`stt.py`):

- **`whisper_cpp`** — via `pywhispercpp`; no GPU required; model stays resident.
- **`faster_whisper`** — optional dependency; GPU via `device`/`compute_type`.
- **`none`** — transcription disabled.

Model lookup for whisper.cpp (`_candidate_model_paths`, `stt.py`) checks, in order:

1. an explicit path / `$UTTER_WHISPER_MODEL`;
2. `$UTTER_MODELS_DIR` (prepended);
3. `<repo>/models/whisper`;
4. `~/.cache/whisper`;
5. the model store (`$XDG_DATA_HOME/utter-models`, override `UTTER_MODELS`), resolving a pulled
   file through its manifest because blobs are content-addressed.

The default whisper.cpp filename is `ggml-small.en.bin`
(`_DEFAULT_WHISPERCPP_NAME`, `stt.py`). If no local file exists and the configured name is a valid whisper.cpp
model, `pywhispercpp` will download it (`_resolve_whispercpp_model`, `stt.py`).

faster-whisper falls back to CPU/int8 if the requested device fails
(`Transcriber`, `stt.py`).

### Spoken language (STT & TTS)

`[stt] language` and `[tts] language` are a **separate axis from the settings-app UI
language** (English/Español strings). They describe what you speak and hear.

Resolution is shared (`utter/locale.py`):

1. A concrete value is normalised: `en_GB`/`en-US.UTF-8` → `en-GB` (encoding and `@modifier`
   are stripped, `_` becomes `-`).
2. `auto` (the default) reads the system locale in `LC_ALL` → `LC_MESSAGES` → `LANG` order.
3. If nothing resolves, the language is **unknown**: Whisper auto-detects and TTS uses the
   engine's default voice. Utter never silently guesses English.

**English-only models.** Whisper `.en` checkpoints (`distil-small.en`, `small.en`,
`ggml-base.en.bin`, …) understand English only. Pairing one with a non-English language logs a
clear warning; Utter **does not switch the model and does not download anything by itself** —
the default install stays small and English. The Voice page shows an inline offer to switch to
a multilingual model, with sizes:

| Model | Approx. download | Notes |
|---|---|---|
| `small` | ~480 MB | multilingual, modest GPU/CPU cost |
| `large-v3-turbo` | ~1.6 GB | multilingual, fastest large variant |

Linux speech output is selected in `[tts]`: `engine = "auto"` probes
**piper** (only with a local voice model: `UTTER_PIPER_VOICES`,
`~/.local/share/piper/voices`, or `<repo>/models/piper`), then **espeak-ng**, **espeak**,
**spd-say**; `voice` is an espeak name or a Piper `.onnx` path, and an empty value derives an
espeak voice from `language` (`de-DE` → `de`, `en-GB` → `en-gb`). Every path is argv-based (no
shell), spawned without blocking, and degrades to a warning plus `False` if no engine is
installed.

**Adding a language** therefore means downloading one piece per axis:

| Axis | What to get | How |
|---|---|---|
| Speech recognition | a multilingual Whisper model | set `[stt] model = "small"` / `"large-v3-turbo"` (the engine fetches it on first use) or point at a whisper.cpp `.bin` |
| Speech output (Linux) | an engine voice | espeak-ng/espeak voices ship with the distro package (`espeak-ng --voices`); Piper needs the `piper` binary plus a `.onnx` voice in `[tts] voice` (real-Piper playback is implemented but not yet verified on hardware) |
| Settings UI | translated strings | **10 locales ship inline** (en, es, de, fr, it, pt, zh, ja, ko, ru); downloadable UI language packs are **not implemented yet** |

On macOS, a resolved `[stt] language` becomes the `SFSpeechRecognizer` locale (for example
`de-DE`); `[macos] speech_locale` is the fallback when no language resolves (`en-US` by
default). `[macos] tts_backend`/`tts_voice` are unchanged.

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

Serve the planner (port 8001, model name `qwen3-4b`). On **Linux** it is vLLM + 4-bit AWQ
(GPU 1 by default):

```bash
scripts/serve_planner.sh
# backgrounded with logs:
setsid bash -c 'scripts/serve_planner.sh > /tmp/vllm-planner.log 2>&1 &'
```

Model/port/GPU are overridable via `UTTER_PLANNER_MODEL_PATH`,
`UTTER_PLANNER_PORT`, `UTTER_PLANNER_SERVED_NAME`,
`UTTER_PLANNER_GPU_MEM_UTIL`, `UTTER_CUDA_VISIBLE_DEVICES`
(`serve_planner.sh:5-25,36-51`).

The Linux default checkpoint is `models/Qwen3-4B-Instruct-2507-AWQ-4bit` (W4A16 AWQ).

On **macOS/Windows** the planner is **llama.cpp** over the
`unsloth/Qwen3-4B-Instruct-2507-GGUF` Q4_K_M checkpoint, on the same endpoint and served name so
`[router] llm_base_url` / `llm_model` are unchanged. `python -m assistant inference install`
fetches the GGUF and a pinned `llama-server` build, so there is nothing to install by hand:

```bash
scripts/serve_planner_llamacpp.sh
# under the hood:
# llama-server --model <gguf> --alias qwen3-4b --host 127.0.0.1 --port 8001 \
#     -c 4096 -ngl auto -fa auto --jinja --reasoning off -np 1 --no-webui
```

`--reasoning off` is **mandatory** (Qwen3-4B-Instruct-2507 is often misdetected as a thinking
model); `-ngl auto` offloads what it can (Metal/CUDA) and falls back to CPU. Overrides:
`UTTER_PLANNER_PORT`, `UTTER_PLANNER_SERVED_NAME`, `UTTER_PLANNER_MODEL_PATH`,
`UTTER_PLANNER_CTX`, `UTTER_LLAMACPP_NGL`, `UTTER_LLAMACPP_SERVER`, `UTTER_LLAMACPP_DIR`,
`UTTER_LLAMACPP_TAG`. Vision is still served separately (below). Any other OpenAI-compatible server
works on any platform; just point `llm_base_url` and `llm_model` at it.

### GPU memory & latency

The shipped serving scripts assume **one NVIDIA GPU shared by both vLLM servers** — this section
is Linux-specific; on macOS/Windows the planner runs under llama.cpp and vision under
`scripts/serve_vision_transformers.py`, so these fractions do not apply. Per-component footprint:

| Component | Model | Precision | GPU memory setting | On disk |
|---|---|---|---|---|
| Speech recognition (in process) | `distil-small.en` | faster-whisper, float16 | ~0.5 GB | — |
| Decision head / planner | `Qwen3-4B-Instruct-2507-AWQ-4bit` | W4A16 (4-bit AWQ) | `--gpu-memory-utilization 0.30` | 3.3 GB |
| Screen vision | `UI-TARS-2B-SFT` | bf16 | `--gpu-memory-utilization 0.55` | 9.2 GB |

`0.30 + 0.55 = 0.85`, so the default pair fits one ~24 GB GPU.

| Tier | What runs | Status |
|---|---|---|
| **24 GB** | Full stack; planner ~7.2 GB (0.30), vision for ~13 GB (0.55) | **Measured** — the shipped defaults target this |
| **16 GB** | Same models with lower `UTTER_VISION_GPU_MEM_UTIL` and `UTTER_PLANNER_GPU_MEM_UTIL` (sum below ~0.9) | **Expected; untested** |
| **8 GB** | 2B vision + 4B AWQ planner at lower utilisation (`assistant recommend` estimates 4B AWQ ≈ 3 GB, UI-TARS-2B ≈ 4 GB) | **Expected; untested** |
| **No GPU / CPU-only** | Vision disabled (accessibility-only), smaller STT | **Expected; untested** |

Only the 24 GB row is what the shipped defaults target; the other rows have **not** been tested.
Use `assistant recommend` to see what fits your machine.

Latency was measured on **NVIDIA RTX 3090 Ti (24 GB)** with the models above, **2026-10-02**
(30 warm calls and 1 cold call per path). It will differ per machine.

| Path | Cold (first call) | Warm p50 | Warm p95 |
|---|---|---|---|
| Rules (layer 1, no model) | 9.2 ms | <1 ms | <1 ms |
| Decision head (layer 2, local LLM) | 108.8 ms | 9.2 ms | 11.6 ms |
| Vision (UI-TARS screenshot grounding) | 676.5 ms | 91.0 ms | 140.6 ms |
| End-to-end `utter assistant --dry-run` | 114 ms | 113 ms | 114 ms |
| Sleep → wake (planner reload to ready) | ~21 s | — | — |

- **"Cold"** is the first call after the servers are up but idle (cold CUDA kernels/caches), not
  model loading.
- The end-to-end time is dominated by Python interpreter startup (~113 ms), not the decision head
  (about 9 ms warm).
- The vision numbers include a synthetic 1344×756 image.

---

## 6. Vision

The T3 tier grounds a description to a click point using **UI-TARS-2B-SFT**. On **Linux** it is
served by vLLM:

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

On **macOS/Windows** the same UI-TARS checkpoint is served by the cross-platform
`scripts/serve_vision_transformers.py` on the same `http://127.0.0.1:8000/v1` / `uitars` endpoint;
there is no vLLM wheel there. See [MACOS.md](MACOS.md) and [WINDOWS.md](WINDOWS.md).

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

### `[sounds] sink`

Sounds play to the system default sink unless you name one. Set `[sounds] sink`
to a PipeWire sink (list them with `pactl list short sinks`; the daemon still
keeps its own default) to route them elsewhere — useful when a virtual sink
(e.g. Sunshine's) is the system default and you never hear the cues locally:

```toml
[sounds]
sink = "alsa_output.pci-0000_01_00.1.hdmi-stereo"
```

This is passed to `pw-play --target` (or `paplay --device`; `afplay` on macOS
ignores it). Empty means the system default. `UTTER_SOUND_SINK` in the
environment overrides the config value; `afplay` (macOS) ignores the sink.

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

**Opt-in gate.** Every profile is off unless it is in the shipped
`utter/profiles/_preselected.yaml` set or you explicitly set `enabled: true` in
your `~/.config/utter/profiles/<id>.yaml`. A disabled app is ignored entirely by
Utter (no launch/focus/close/shortcut/custom/media/targeted input), while sites,
generic media keys and CLI agents stay available. See
[`docs/APPS.md`](APPS.md) §2 for the full rule.

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

  The production config (`config.runner.toml`) keeps both off; the GUI Safety
  page writes the allow-list to the file the runner actually loads.
- **Never weaken policy** by letting screen/a11y/OCR/clipboard content author action
  args — that is the `-32006` invariant enforced by the runner.
- The legacy assistant's dry-run is controlled by `UTTER_DRY_RUN`: the
  `utter_py` plugin defaults it **on**, so only `UTTER_DRY_RUN=0` touches the
  desktop (`_dry_run`, `plugins/utter_py/plugin.py`). The shipped runner unit and
  the macOS launchd agent both export `UTTER_DRY_RUN=0` for real actions; the M3
  tests set `UTTER_DRY_RUN=1`/use `config.m3.toml`. Route-only testing without the
  plugin: `python -m utter.daemon --text "<cmd>" --dry-run`.

---

## 12. Sleep, wake and the OSD

Sleep mode is configured under `[sleep]` in `config.default.toml`: the sleep phrase stops the
services listed in `[sleep] services` and unloads the speech model, and idle sleep does the same
after `[sleep] idle_minutes` (15 by default). Holding a push-to-talk key wakes everything; speech
comes back first and the larger models reload in the background.

The OSD state contract includes a `loading` state, shown while models come back after wake or a
cold start; a model-readiness watcher clears it once the servers are ready.

---

## 13. App-targeted actions & background input

Shipped. An utterance can name the target up front instead of acting on the focused window. The
leading `<app>` must resolve to a real profile or a CLI agent (`utter/data/cli_agents.json`);
generic words ("media", "editor", "music", "terminal") are never claimed, so `type ok`,
`press enter` and `pause` keep their existing focused behaviour (`_app_target`,
`_claim_app_target` in `utter/router/rules.py`).

| Utterance | Plan |
|-----------|------|
| `codex type ok` | `TYPE_TEXT{text="ok", app="codex"}` |
| `codex press enter` | `KEY{chord="Return", app="codex"}` |
| `spotify pause` | `MEDIA{command="pause", app="spotify"}` |
| `close steam` | `CLOSE_APP{app="steam"}` |

Target-first `type`/`write`, `press`/`hit`/`send` and `<app> <media-command>` are matched before
the generic focused `type`/`key` rules. `close <app>` closes one of the app's windows. A
`window_id` is never set at plan time: the executor resolves the target from the live compositor
window list, which may only *select* a window.

**Mechanism.** Wayland has no background key injection — `wtype`/`ydotool` emit to the focused
surface only, and niri/KWin expose no per-window injection. So a targeted `key`/`type_text` is a
**focus round-trip**: focus the target, inject, then restore the previous focus. `close_app` and
`media` are genuinely focus-free; they never focus.

**Latency** (measured on one machine — niri, RTX 3090 Ti, 2026-10-02):

- same workspace: ~**38 ms**, invisible (no viewport movement);
- cross-workspace, compositor animations **off**: ~**41 ms**;
- cross-workspace, animations **on**: ~**250 ms** of visible viewport scroll
  (`horizontal-view-movement`) — this is why it is gated.

```toml
[target]
mode = "round_trip"            # round_trip | leave | off
cross_workspace = "ask"        # ask | allow | refuse  (fallback; see [wayland])
restore = "if_unchanged"       # if_unchanged | always | never
focus_timeout_ms = 500

[wayland]
cross_workspace = "auto"       # auto | ask | allow | refuse
assume_animations_off = false
```

- `[target].mode`: `round_trip` = focus, act, restore; `leave` = focus, act, stay on the target;
  `off` = only focus/close/media, refuse targeted input.
- `[target].cross_workspace` is the fallback policy. `[wayland].cross_workspace` **supersedes** it:
  `auto` allows cross-workspace without asking **only** when `assume_animations_off` is true,
  otherwise it falls back to `[target].cross_workspace`; an explicit `ask`/`allow`/`refuse` wins.
- `restore = "if_unchanged"` only restores focus if the user did not move away during the
  round-trip.
- Same-workspace single-window input runs without asking; cross-workspace or a fullscreen previous
  window requires confirmation (or refuses when there is no confirmation channel, e.g. headless).

**Trust.** The app name comes from the user (trusted intent) and profile `app_ids` are
precomputed; the compositor window list is untrusted and may only select a window — a window title
is never turned into text or a command. `screen`-provenance args are still rejected `-32006`, and
`close_app` requires confirmation.

| Platform | Mechanism | Notes |
|----------|-----------|-------|
| Linux/Wayland (niri, KWin) | Focus round-trip | Visible only when the target is off-screen or on another workspace with animations on. |
| Hyprland | Focus round-trip | `sendshortcut` exists but is unreliable for native-Wayland Electron/Chromium apps and can silently do nothing; the round-trip is the safer path. |
| macOS | `CGEventPostToPid` | Native key event posted directly to a target process with **no focus change** (keyboard only; the mouse cannot target a background window). Natively supported. |
| Windows | Not supported | — |
