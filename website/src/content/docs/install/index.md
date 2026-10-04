---
title: "Install"
description: "The ways to install Utter on Linux and macOS: clone and install, the one-line remote installer, or build from source."
---

Utter runs on **Linux on Wayland** and **macOS**. On Linux, **niri** and **KDE Plasma (KWin)** are
first-class and other compositors get partial support (dictation, typing, launching; no window
actions). Both platforms need **Python 3.12+**; Linux needs **PipeWire**. Dictation and the
assistant key both work on Linux and macOS.
See [macOS](/guides/macos/) for the macOS-specific setup.
An NVIDIA GPU is recommended for the larger models but not required.
Building the settings app needs Node + pnpm and a Rust toolchain. Linux release assets are
published for x86_64 today; macOS ships `.dmg` bundles for Apple Silicon and Intel.

The installer is an **interactive wizard**. It walks each component (the runner and `assistant`
CLI, your spoken language, the settings app, the background services, speech models and the
optional Noctalia widget) and asks whether you want it. In a terminal, Enter accepts the
recommended default. `--yes` accepts them all non-interactively. Every download is verified against
the release's `sha256sums.txt`.

**English ships inline** — the language step defaults to English and downloads nothing, so the
default install needs no model fetch. Other languages are opt-in: the step offers the matching
multilingual speech model and voice (with sizes) and only downloads what you accept.

Pick the path that suits you; the remote installer below works on both Linux (Wayland) and macOS.
See [macOS](/guides/macos/) for the manual `.dmg` or Homebrew install.

## 1. Clone and install

Keep the repository and install from your own checkout:

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant

./install.sh --dry-run   # walk the wizard, print the plan, change nothing
./install.sh             # install the components you choose
```

Want the smallest possible install, distro packages and the background service and nothing else?
Use the developer installer:

```bash
install/install.sh --dry-run
install/install.sh --yes
```

Undo either one with `./install.sh --uninstall`. Details, including what the developer installer
does step by step, are in [Clone and build from source](/install/from-source/).

## 2. Remote install

No clone needed:

```bash
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash
```

:::note[A bare pipe changes nothing]
Piped input is not a terminal, so the wizard cannot prompt. A bare `curl | bash` **prints the
plan and exits without changing anything**. Pass `--yes` to accept the recommended defaults, or
any other flag:
:::

```bash
# recommended defaults, no prompts
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --yes

# native package (.deb/.rpm) through your package manager instead of the AppImage (needs sudo)
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --package --yes

# only these components
curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash -s -- --only core,gui --yes
```

Other flags: `--skip <csv>`, `--with-noctalia`, `--dry-run`, `--uninstall`. The full flag and
environment matrix, the ten wizard steps and where everything ends up are in
[Install from the web](/install/remote/).

## 3. Build from source

The assistant core is stdlib-only Python; the settings app is Tauri v2 + React + Tailwind CSS v4.

```bash
# the assistant core, straight from the checkout
python3 -m utter.daemon --text "open youtube" --dry-run
scripts/verify.sh            # unit + e2e + conformance

# the settings app
cd gui-tauri
pnpm install
pnpm tauri build             # release binary (and a .deb) in src-tauri/target/release
pnpm tauri dev               # ...or run it with hot reload
```

On Wayland with a dual-NVIDIA setup, launch the built app with the DMABUF renderer disabled.
The `utter-gui` launcher does this for you:

```bash
WEBKIT_DISABLE_DMABUF_RENDERER=1 ./gui-tauri/src-tauri/target/release/utter
```

See [Clone and build from source](/install/from-source/) for services, the `assistant` CLI and
the model store.

## GPU requirements and latency

The shipped serving scripts assume **one NVIDIA GPU shared by both vLLM servers**. Per-component
footprint:

| Component | Model | Precision | GPU memory setting | On disk |
|---|---|---|---|---|
| Speech recognition (in process) | `distil-small.en` | faster-whisper, float16 | ~0.5 GB | — |
| Decision head / planner | `Qwen3-4B-Instruct-2507-AWQ-4bit` | W4A16 (4-bit AWQ) | `--gpu-memory-utilization 0.30` | 3.3 GB |
| Screen vision | `UI-TARS-2B-SFT` | bf16 | `--gpu-memory-utilization 0.55` | 9.2 GB |

`0.30 + 0.55 = 0.85`, so the default pair fits one ~24 GB GPU.

| Tier | What runs | Status |
|---|---|---|
| **24 GB** | Full stack; planner ~7.2 GB (0.30), vision ~13 GB (0.55); together ~0.85 of the card | Fits the shipped defaults — the latency numbers below were measured with both models on a 24 GB card |
| **16 GB** | Same models with lower `UTTER_VISION_GPU_MEM_UTIL` and `UTTER_PLANNER_GPU_MEM_UTIL` (sum below ~0.9) | **Supported** |
| **8 GB** | 2B vision + 4B AWQ planner at lower utilisation (`assistant recommend` estimates 4B AWQ ≈ 3 GB, UI-TARS-2B ≈ 4 GB) | **Supported** |
| **No GPU / CPU-only** | Vision disabled (accessibility-only), smaller STT | **Supported** |

The 24 GB row is what the shipped defaults target; the other rows use lower utilisation settings.
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

See [Models](/guides/models/) for the recommendation rules and the model store.

## After installing

Open the **Utter settings app**, set your push-to-talk keys on the **Voice** page, and pick a
recommended model on the **Models** page. Then follow [Getting started](/getting-started/).

```bash
systemctl --user enable --now utter-runner.service   # start the runner
assistant doctor --json                              # verify deps + plugins
utter-gui                                            # open the settings window
```
