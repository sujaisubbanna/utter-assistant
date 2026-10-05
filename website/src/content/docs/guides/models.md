---
title: "Models"
description: "The model store, which models are recommended for each GPU class, and how downloads are resumed and verified."
---

Utter uses up to three local models, and **works with none of them**. Rules, window state and
accessibility handle the deterministic commands. Each model you add unlocks something:

| Tier | What it does | Without it |
|---|---|---|
| **Speech recognition** | turns your voice into text | the push-to-talk keys have nothing to transcribe; text commands and the dry run still work |
| **Decision head** | chooses among prepared actions when no rule matches | only rule-matched phrasing works |
| **Screen vision** | finds a described element on a screenshot | "click ..." stops after the accessibility attempt |

Models are **your choice**. The installer never downloads one, and the settings app downloads
nothing without you pressing the button.

## Recommended models per machine

`assistant recommend` (and the **Recommended for your computer** section of the Models page)
looks at your GPU vendor, its VRAM and your RAM, and suggests one model per tier. These are the
rules it applies:

### Speech recognition

| Hardware | Backend | Model | Device | Footprint |
|---|---|---|---|---|
| NVIDIA GPU with 8 GB VRAM or more | faster-whisper | `large-v3-turbo` | CUDA | about 2 GB VRAM |
| AMD or Intel GPU (Vulkan) | whisper.cpp | `small` | Vulkan | about 1 GB VRAM |
| No usable GPU | whisper.cpp | `base.en` | CPU, int8 | about 1 GB RAM |

:::note[Other spoken languages]
The small default checkpoints ending in `.en` are English-only. For another spoken language,
choose a multilingual model instead (`small` on modest hardware, `large-v3-turbo` with more
VRAM). The Voice page offers the switch explicitly with the size shown, and **Utter never
downloads a model by itself** — whichever model you choose is fetched by the speech engine the
first time it is used. See
[Spoken language](/guides/configuration/#spoken-language-stt-and-tts).
:::

### Decision head and planner

| VRAM | Model class | Quantisation | Footprint |
|---|---|---|---|
| 24 GB or more | 7 to 8 B parameters | AWQ | about 6 GB VRAM |
| 8 to 24 GB | 4 B parameters | AWQ | about 3 GB VRAM |
| 8 GB or less | 1.5 to 3 B parameters on CPU, or an existing endpoint | q4 | about 3 GB RAM |

The shipped default serving script uses a 4-bit AWQ build of Qwen3-4B-Instruct under the served
name `qwen3-4b`.

### Screen vision

| VRAM | Model | Footprint |
|---|---|---|
| 16 GB or more | UI-TARS-7B | about 8 GB VRAM |
| 6 to 16 GB | UI-TARS-2B | about 4 GB VRAM |
| Less than 6 GB | none; accessibility only | |

On the Models page, **Get it** pre-fills a ready-to-pull source for a recommendation when one is
known. The UI-TARS vision repos ship sharded safetensors (`model-0000N-of-0000M.safetensors` plus
an index), so a single-file store pull cannot fetch them and `assistant recommend` omits `source`
for the vision tier. Provision vision with `scripts/install_inference.sh` (it downloads the full
repo directory) and serve it with `scripts/serve_vision.sh`. Applying a recommendation still
updates the matching config keys; for the decision model, match the name to what your server
actually serves.

The installer offers the same tiers and, for each one you accept, pulls a **curated default
source** — STT `hf:ggerganov/whisper.cpp:ggml-small.en.bin` on the 24 GB reference machine.
`UTTER_MODEL_STT`, `UTTER_MODEL_VISION` and `UTTER_MODEL_DECISION` override them; the vision tier
is sharded (use `scripts/install_inference.sh`) and the decision tier has no documented source and
must be set explicitly.

:::note[Smaller GPUs]
Running well on 8 GB cards and CPU-only machines (smaller defaults, quantised builds, one GPU
shared between the models) is on the roadmap. Today the comfortable setup for all three tiers
is a 16 GB or larger NVIDIA GPU. Speech recognition alone runs happily on CPU.
:::

## The model store

```text
$XDG_DATA_HOME/utter-models/      # override with UTTER_MODELS
  manifests/<host>/<ns>/<name>/<tag>.json
  blobs/sha256-<hex>
```

The store sits beside the install tree (`$PREFIX/share/utter`), not inside it, so
uninstalling keeps your models. An older store at `$XDG_DATA_HOME/utter/models`
is moved here once, on first use.

The layout is Ollama-style: manifests name a model and tag; blobs are content-addressed by
SHA-256, so two models that share a file share one blob.

### Sources

| Form | Resolves to |
|---|---|
| `hf:org/repo` | the Hugging Face repository |
| `hf:org/repo:file` | one file from that repository (`.../resolve/main/file`) |
| `https://...` | a direct download |
| `file://...` or a bare local path | a file already on disk |

### Pulling, listing and removing

```bash
assistant models list
assistant models show <name>
assistant models pull hf:org/repo[:file] [--tag latest]
assistant models rm <name>
assistant models prune
```

Add `--json` to any of them for machine-readable output; the settings app uses the same JSON
and shows **live progress** while a pull runs.

### What a pull guarantees

- **Resumable.** A partial file is kept and continued with `curl -C -` (or an HTTP `Range`
  request when curl is absent).
- **Retries** with backoff and stall detection.
- **Verified.** The SHA-256 of the finished file is checked before it becomes a blob. When the
  server exposes a digest up front it is compared too. A mismatch fails the pull.
- **Atomic.** The blob is renamed into place only after verification.
- **One pull at a time** per model (a lock file), with a disk-space preflight before starting.

`rm` drops the manifest and any blob no other manifest references. `prune` collects orphaned
blobs and unfinished downloads; the Models page calls this **Clean up**.

## Serving the language and vision models

The store holds the files. Serving them is a separate step, done by vLLM (or any
OpenAI-compatible server such as Ollama or llama.cpp) and pointed to from
`~/.config/utter/config.toml`:

```toml
[router]
llm_base_url = "http://127.0.0.1:8001/v1"
llm_model = "qwen3-4b"

[vision]
base_url = "http://127.0.0.1:8000/v1"
model = "uitars"
```

`scripts/serve_planner.sh` and `scripts/serve_vision.sh` start vLLM with sensible defaults. Each
resolves its model in order: `UTTER_PLANNER_MODEL_PATH` / `UTTER_VISION_MODEL_PATH`, then the
store, then a `models/<name>` checkout, then — for vision — the Hugging Face repo id, which vLLM
downloads itself. A store entry holds one content-addressed file, not the multi-file directory
vLLM needs, so the scripts report that and fall through; keep a full checkout (for example via
`scripts/install_inference.sh`) for the planner. See
[Configuration](/guides/configuration/#the-decision-head-and-the-planner). If you point either
endpoint at another machine, the settings app marks it in amber: that is the one case where
your data leaves the computer.

## GPU memory and latency

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
Use `assistant recommend` (or the **Recommended for your computer** section of the Models page) to
see what fits your machine.

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

## Sleep mode and models

Saying your sleep phrase stops the model services listed in `[sleep] services` and unloads the
speech model, freeing the GPU for something else. Utter also does this by itself after
`[sleep] idle_minutes` (15 by default) without a push-to-talk key or a spoken command; typing
and clicking in other apps do not count. Holding a push-to-talk key wakes everything: speech
comes back first, and the bigger models reload in the background. See
[Getting started](/getting-started/#5-sleep-mode) and the `[sleep]` keys in
[Configuration](/guides/configuration/#sleep).
