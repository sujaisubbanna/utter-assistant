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
known (for UI-TARS-7B that is `hf:ByteDance-Seed/UI-TARS-1.5-7B`). Applying a recommendation
also updates the matching config keys; for the decision model, match the name to what your
server actually serves.

:::note[Smaller GPUs]
Running well on 8 GB cards and CPU-only machines (smaller defaults, quantised builds, one GPU
shared between the models) is on the roadmap. Today the comfortable setup for all three tiers
is a 16 GB or larger NVIDIA GPU. Speech recognition alone runs happily on CPU.
:::

## The model store

```text
$XDG_DATA_HOME/utter/models/      # override with UTTER_MODELS
  manifests/<host>/<ns>/<name>/<tag>.json
  blobs/sha256-<hex>
```

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

`scripts/serve_planner.sh` and `scripts/serve_vision.sh` start vLLM with sensible defaults; see
[Configuration](/guides/configuration/#the-decision-head-and-the-planner). If you point either
endpoint at another machine, the settings app marks it in amber: that is the one case where
your data leaves the computer.

## Sleep mode and models

Saying your sleep phrase stops the model services listed in `[sleep] services` and unloads the
speech model, freeing the GPU for something else. Utter also does this by itself after
`[sleep] idle_minutes` (15 by default) without a push-to-talk key or a spoken command; typing
and clicking in other apps do not count. Holding a push-to-talk key wakes everything: speech
comes back first, and the bigger models reload in the background. See
[Getting started](/getting-started/#5-sleep-mode) and the `[sleep]` keys in
[Configuration](/guides/configuration/#sleep).
