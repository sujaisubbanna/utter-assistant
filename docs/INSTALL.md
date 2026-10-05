# Install & model store

Target: Linux on Wayland — **niri** first, plus **KDE Plasma (KWin)** implemented and unit-tested
(not yet exercised on a live Plasma session), other compositors get partial support (dictation,
typing, launching; no window actions). Dictation and the assistant key work on Linux and macOS.
**macOS is natively supported** (see [`MACOS.md`](MACOS.md)); Windows is not supported.

## 1. Installer

There are two scripts on a source checkout:

- **`install/install.sh`** — the minimal **developer installer**: distro deps, the runner
  service, install-state and a `doctor`/`recommend` check. It has **no language or model step**.
- **root `install.sh`** — the **full wizard** (the same one served from
  `https://utter.sujaisubbanna.com/install.sh`): it additionally walks components, the
  **spoken-language** step, model tiers, the GUI and the optional Noctalia widget, with
  `--only`/`--skip`/`--with-noctalia`/`--package`.

```bash
./install.sh --dry-run               # full wizard (default: print exactly what it would do)
./install.sh --yes                   # apply recommended defaults, no prompts
./install.sh --yes --only core,gui   # apply only chosen components

install/install.sh --dry-run         # minimal developer installer
install/install.sh --yes             # deps + runner unit
install/install.sh --yes --no-deps   # skip distro packages, only wire the service
```

The walk below (steps 1–7) describes the **full root `install.sh` wizard**, which is what the
hosted one-liner runs; `install/install.sh` covers steps 1, 3–4 and 7 only.

**Agent-driven install.** Any of these can also be driven by an AI coding agent: point it at
[`INSTALL-AGENT.md`](INSTALL-AGENT.md) (also on the site as
[Agent-driven install](https://utter.sujaisubbanna.com/install/agent/)). It is a self-contained
runbook — platform detection, install, verification, macOS permissions, first run, uninstall —
with no prior repo context required.

What it does:
1. Detects the distro from `/etc/os-release` (`ID`/`ID_LIKE`) → **pacman / apt / dnf / zypper**
   (falls back to `command -v`).
2. Asks which **spoken language** you use. **English ships inline** (the default STT model
   `distil-small.en` and the English UI strings) and needs **no downloads**; press Enter to keep
   it. Other languages are opt-in: the installer offers the matching multilingual STT model,
   a TTS voice and (when configured) a UI localization pack, showing sizes, and downloads
   nothing unless you accept. The choice is written to `[stt] language` / `[tts] language`
   (and `[tts] voice`) in `config.toml`. With `--yes` it stays English and prints the
   `assistant models pull` command to add a language later.
3. Installs the system dependencies (name-mapped per distro): `wtype`, `ydotool` (+`ydotoold`),
   `grim`, `wl-clipboard`, `pipewire`, `webkit2gtk-4.1` and `libsoup-3.0` (the Tauri v2 WebKit
   runtime; the old GTK4/libadwaita window is gone), optional `keyd`.
   Accessibility (reading the focused element via AT-SPI) additionally needs PyGObject
   (`python-gobject`) and `at-spi2-core`; these are **optional** — a11y degrades gracefully
   when absent, so the installer does not require them.
4. Checks the `input` group and `/dev/uinput`; **prints** the `usermod -aG input` + udev + re-login
   steps (it never silently changes groups).
5. Installs and (with `--yes`) enables the **user** service `utter-runner.service`, bound to
   the graphical session via the `scripts/utter-wayland-ready.sh` wrapper.
6. Records what it did in `$XDG_STATE_HOME/utter/install.json` (reversible).
7. Runs `python3 -m assistant doctor --json` (or `recommend --json`) to verify.

On first launch the settings app opens the **first-run setup wizard** — language, permissions,
push-to-talk keys, which apps Utter may control, and a model to run. It is documented in
[`ONBOARDING.md`](ONBOARDING.md).

The GUI step also installs a desktop entry (`~/.local/share/applications/utter-gui.desktop`,
`Name=Utter`, `Categories=Utility;Accessibility;`) and refreshes the desktop database, so
**Utter appears in the application menu** of KDE and other desktops. Opening it starts the
setup wizard, which starts the runner service. CLI fallback:
`systemctl --user enable --now utter-runner.service` then `utter-gui`.

Uninstall:
```bash
install/uninstall.sh --dry-run
install/uninstall.sh --yes            # stop/disable units, remove recorded files
install/uninstall.sh --yes --purge    # also remove models + config
```
Package removals are **printed**, never performed automatically.

## 2. Services (systemd user)

| Unit | Purpose |
|---|---|
| `utter-runner` | the modular runner (plugin supervisor) — installed by this installer |
| `utter-bridge` | legacy Python assistant (voice→action), for older installs |
| `utter-vision` | vLLM UI-TARS grounding server (`:8000`) |
| `utter-planner` | vLLM planner (`:8001`) |
| `utter-audio-defaults` | keeps TV output / RNNoise input pinned |

The runner unit uses `scripts/utter-wayland-ready.sh`, which discovers `WAYLAND_DISPLAY`,
`DBUS_SESSION_BUS_ADDRESS` and `NIRI_SOCKET` before exec'ing the runner — user services do not
inherit the session environment automatically.

## 3. `assistant` CLI

```bash
python3 -m assistant doctor [--json]                    # deps + plugin negotiation + drift
python -m assistant recommend [--json]                 # hardware-aware profile suggestions
python -m assistant models list|show <n>|pull <src>|rm <n>|prune [--json]
python -m assistant status [--json]                    # runner.status passthrough
python -m assistant install-state record|show
```

`doctor --json` includes a `deps` section (which CLI tools and libraries are present) alongside
the per-plugin `negotiated`, `unknown_capabilities`, `missing_requires`, and
`permissions:[{name,enforced,advisory}]` from the protocol (see `docs/COMPATIBILITY.md`).

## 4. Model store

Layout (Ollama-style, XDG):
```
$XDG_DATA_HOME/utter-models/      # override with UTTER_MODELS
  manifests/<host>/<ns>/<name>/<tag>.json
  blobs/sha256-<hex>
```
The store is a sibling of the install tree (`$PREFIX/share/utter`), never inside
it, so uninstalling the core tree keeps your models. An older store at
`$XDG_DATA_HOME/utter/models` is moved here once, on first use.
- Sources: `hf:org/repo[:file]` → resolved to `https://huggingface.co/org/repo/resolve/main/file`;
  bare `https://…`; local `file://`.
- **Resumable**: partial file + `curl -C -` (or urllib `Range`), retry/backoff, sha256 verify,
  atomic rename, pull lock, disk-space preflight.
- `rm` drops the manifest and any now-unreferenced blobs; `prune` GCs orphans.

The installer offers the model tiers (default **No**) and, for each tier you accept, pulls a
**curated default source** through the store. On the 24 GB reference machine (RTX 3090 Ti) those
defaults are:

| Tier | Default source | Notes |
|---|---|---|
| STT | `hf:ggerganov/whisper.cpp:ggml-small.en.bin` | ~466 MB; runs on CPU or GPU |
| Vision | — | UI-TARS repos are sharded safetensors (no single-file pull); provision with `scripts/install_inference.sh` |
| Decision / planner | — | no documented single Hugging Face source; set `UTTER_MODEL_DECISION` |

`UTTER_MODEL_STT` / `UTTER_MODEL_VISION` / `UTTER_MODEL_DECISION` override the defaults. Nothing
is downloaded unless you accept the tier, and `assistant recommend` suggests a profile for the
machine's GPU/RAM before you choose.

### Spoken language and downloads

The installer's **Language** step writes the spoken language to `[stt] language` and
`[tts] language` (plus `[tts] voice`) in `config.toml`. `"auto"` (the config default) resolves
from `LC_ALL`/`LC_MESSAGES`/`LANG`; the installer records an explicit code instead. English is
the only inline locale — **no downloads are needed for English** — and the default STT model
`distil-small.en` is English-only.

For another language the installer *offers* (default No) the matching downloads and never fetches
them unless you accept:

| Download | Size | Source env |
|---|---|---|
| Multilingual STT model | ~480 MB (`small`) / ~1.6 GB (`large-v3-turbo`) | `UTTER_MODEL_STT_<LANG>` → `UTTER_MODEL_STT_<LANG2>` → `UTTER_MODEL_STT` |
| TTS voice | varies | `UTTER_MODEL_TTS_<LANG>` → `UTTER_MODEL_TTS` (voice name via `UTTER_TTS_VOICE_<LANG>`, default = the language code) |
| UI localization pack | typically < 5 MB | `UTTER_LOCALE_PACK_<LANG>` → `UTTER_LOCALE_PACK` |

`<LANG>` is the uppercased language with `-` → `_` (`de-DE` → `DE_DE`, then `DE`). Every accepted
download goes through the normal model store (`assistant models pull <src>`); if no source is
configured the installer prints that command for you to run later. Nothing uses `sudo`.

### GPU planning (VRAM & latency)

The shipped serving scripts (`scripts/serve_planner.sh`, `scripts/serve_vision.sh`) assume **one
NVIDIA GPU shared by both vLLM servers**. Per-component footprint:

| Component | Model | Precision | Server | GPU memory setting | On disk |
|---|---|---|---|---|---|
| Speech recognition | `distil-small.en` | faster-whisper, float16 | in process (no vLLM) | ~0.5 GB | — |
| Decision head / planner | `Qwen3-4B-Instruct-2507-AWQ-4bit` | W4A16 (4-bit AWQ) | vLLM `:8001` | `--gpu-memory-utilization 0.30` | 3.3 GB |
| Screen vision | `UI-TARS-2B-SFT` | bf16 | vLLM `:8000` | `--gpu-memory-utilization 0.55` | 9.2 GB |

`0.30 + 0.55 = 0.85`, so the default pair fits one ~24 GB GPU.

| Tier | What runs | GPU budget | Status |
|---|---|---|---|
| **24 GB** | Full stack: STT + 4B AWQ planner + 2B bf16 vision | Planner ~7.2 GB (0.30), vision ~13 GB (0.55); together ~0.85 of the card | Fits the shipped defaults; the latency numbers below were measured with both models running on a 24 GB card |
| **16 GB** | Same models, lower `UTTER_VISION_GPU_MEM_UTIL` and `UTTER_PLANNER_GPU_MEM_UTIL` (keep the sum below ~0.9) | — | **Expected; untested** |
| **8 GB** | 2B vision + 4B AWQ planner at lower utilisation (`assistant recommend` estimates 4B AWQ ≈ 3 GB, UI-TARS-2B ≈ 4 GB) | — | **Expected; untested** |
| **No GPU / CPU-only** | Vision disabled (accessibility-only), smaller STT | — | **Expected; untested** |

Only the 24 GB row is what the shipped defaults target. The 16 GB, 8 GB and CPU-only rows have
**not** been tested — they are expected to work, not confirmed. Use `assistant recommend` to see
what fits your machine.

Latency is measured on **NVIDIA RTX 3090 Ti (24 GB)** with the models above, **2026-10-02**
(30 warm calls and 1 cold call per path). Numbers are from one machine; your hardware will differ.

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

## 5. Optional UI: Noctalia widget

If you run the **Noctalia** shell, there is an optional widget package at `widgets/noctalia/`
(bar widget + persistent attention panel + assistant OSD). It is **not** installed by default.

```bash
widgets/noctalia/install.sh            # copy + lint
widgets/noctalia/install.sh --yes      # + enable and add the bar widget
install.sh --with-noctalia             # via the main installer (optional)
```
Skip it entirely if you don't use Noctalia — the core assistant does not depend on it.

## 6. Zero-model mode

The runner works with **no models at all**: rules + on-screen context + accessibility handle
deterministic commands; STT is needed only for voice, and vision/LLM plugins are optional.
