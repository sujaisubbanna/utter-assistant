# Utter CLI for agents

`utter` drives desktop actions. `assistant` (invoked as `python -m assistant`) manages the runner, models, diagnostics, and installation state. They are separate entry points.

This is the headless path: no microphone or voice is needed. The same router, safety policy and desktop actions used by voice are available from a terminal, script or agent, with stable JSON output.

## Quickstart

```sh
utter capabilities --json
utter schema --json
utter assistant "open youtube" --dry-run --json
utter dictation "hello" --dry-run --json
utter assistant "open youtube" --json
```

All successful JSON responses use `{"schema":"utter.cli/v1","ok":true,"command":"…","data":…}`. Errors use the same envelope with `ok:false` and `error:{"code":"…","message":"…"}`. JSON is printed only on stdout; human diagnostics go to stderr. The schema command is the machine-readable command and error registry.

## Commands

| Command | Purpose |
|---|---|
| `utter assistant TEXT` / `utter --assistant TEXT` | Route a spoken-style command through Utter. `--dry-run` returns the plan without execution and has a 4 second hard limit; acting requires `--confirm`. |
| `utter assistant "<app> type …"` / `"<app> press …"` / `"<app> pause"` | Target a named app instead of the focused window: `utter assistant "codex type ok"`, `"close steam"`. On Wayland this is a brief focus round-trip; `close` and media are focus-free. See [CUSTOMISING §13](CUSTOMISING.md#13-app-targeted-actions--background-input). |
| `utter dictation TEXT` / `utter --dictation TEXT` | Type literal text through wtype, falling back to ydotool. `--dry-run` reports what would be typed. |
| `utter listen` | Capture for up to `--timeout SEC` (default 10) and act with `--confirm`; `--transcribe-only` returns recognized text. Requires sounddevice/PipeWire and a local STT model. |
| `utter speak TEXT` | Local TTS through `espeak-ng`, or `espeak` fallback. |
| `utter transcribe --file FILE` | Transcribe uncompressed PCM WAV (16 kHz, mono/stereo) with the configured local STT backend. |
| `utter capabilities --json` | Input/audio backends, TTS, GPU presence and compute runtime, installed models, and runner connectivity. GPU presence is probed independently from CUDA/ROCm availability. |
| `utter schema --json` | Versioned command and error registry plus the complete Draft 2020-12 response schema. |
| `utter apps list --json` | App profile identifiers and aliases. |
| `utter actions list [--app ID] --json` | Action catalog, optionally scoped to an app. |
| `utter profiles --json` | Loaded profile summary. |
| `utter status --json`, `utter doctor --json` | Runner state and diagnostics. |
| `utter version --json` | Utter version. |
| `utter settings list|get|set` | Read or edit the active TOML settings. |
| `utter commands list|set|remove` | List built-in app shortcuts and create/remove per-app custom spoken phrases that send a key chord. |

### Inference models (vision + planner)

The vision (UI-TARS) and planner (Qwen3-4B AWQ) checkpoints ship as multi-file
(sharded safetensors) repositories, so the single-file model store
(`assistant models pull`) cannot fetch them. Use the provisioner instead:

```sh
python -m assistant inference status  [--json]   # are the model dirs complete?
python -m assistant inference install [--json]   # download + prepare them
```

`status --json` returns
`{"vision":bool,"planner":bool,"vision_path":str,"planner_path":str}`. Human
output also names the platform's serve script (`scripts/serve_vision.sh` on
Linux, `scripts/serve_vision_transformers.py` on macOS).

`install` runs `scripts/install_inference.sh` and streams its output. With
`--json` it emits one JSON object per line (NDJSON):

```
{"event":"start"}
{"event":"progress","line":"…"}
{"event":"done","ok":true}
```

A failure emits `{"event":"error","error":"…"}` instead of `done`; the exit code
is 0 on success and 1 on failure. On Windows `install` exits 1 with
`not supported on Windows yet`. On macOS vLLM has no wheel, so the script
installs `transformers` + `torch` (Metal/MPS) + `accelerate` and serves vision
with `scripts/serve_vision_transformers.py`; Linux installs vLLM and serves with
`scripts/serve_vision.sh` / `scripts/serve_planner.sh`.

## Settings and custom commands

Settings use dotted keys matching the config sections. Values to `settings set` are JSON values, type-checked against Utter's config model. Use `--dry-run` to preview; writing requires `--confirm`. Edits preserve other TOML lines and comments and replace the file atomically.

```sh
utter settings list --json
utter settings get stt.device --json
utter settings set stt.device --value '"cuda"' --dry-run --json
utter settings set audio.sample_rate --value 48000 --confirm --json
```

### Language

The spoken language (speech-to-text and spoken replies) is a setting, independent of the
settings-app UI language. `"auto"` resolves from `LC_ALL`/`LC_MESSAGES`/`LANG`; otherwise set a
code such as `de-DE`. Non-English needs a multilingual Whisper model (the default is an
English-only `.en` model); pull one with `python -m assistant models pull <src>`.

```sh
utter settings set stt.language --value '"de-DE"' --confirm --json
utter settings set tts.language --value '"de-DE"' --confirm --json
utter settings set tts.voice    --value '"de"' --confirm --json
```

The settings-app UI ships 10 locales (en, es, de, fr, it, pt, zh, ja, ko, ru); see
[TRANSLATING.md](TRANSLATING.md) for how those are managed.

`commands set APP PHRASE CHORD` adds a phrase for the selected app. When that app is focused and the phrase is spoken, Utter sends the configured keyboard chord. It accepts only a bounded printable phrase and a keyboard chord; it cannot define shell commands or arbitrary action arguments. Preview writes with `--dry-run`; persist or remove them with `--confirm`.

```sh
utter commands list --app firefox --json
utter commands set firefox "toggle developer tools" ctrl+shift+i --dry-run --json
utter commands set firefox "toggle developer tools" ctrl+shift+i --confirm --json
utter commands remove firefox "toggle developer tools" --confirm --json
```

The canonical JSON Schema is packaged at `utter/data/cli.schema.json` and returned under `data.json_schema` by `utter schema --json`. Validate responses with any Draft 2020-12 JSON Schema validator.

The old `utter --text TEXT` and `python -m utter.daemon` service interfaces remain available. Management stays under `python -m assistant` (`doctor`, `recommend`, `status`, `macos-permissions`, `models`, `inference`, `install-state`).

## Exit and error contract

| Exit | Meaning | Error code examples |
|---:|---|---|
| 0 | Completed | — |
| 1 | Action failed or no action matched | `E_ACTION_FAILED`, `E_NO_ACTION` |
| 2 | Usage error | `E_USAGE` |
| 3 | Blocked or explicit confirmation required | `E_BLOCKED` |
| 4 | Required backend unavailable or preview timed out | `E_BACKEND_UNAVAILABLE`, `E_RUNNER_UNAVAILABLE`, `E_PREVIEW_TIMEOUT` |
| 5 | Requested app/resource not found | `E_NOT_FOUND` |

Use `--non-interactive` for automation; JSON mode never prompts. Mutating operations should be run with `--dry-run` first. Consequential actions require explicit confirmation, and risky `terminal`/`input` abilities remain governed by runner policy. CLI text is a user request; screen, accessibility, OCR, clipboard, and title data remain untrusted selectors and cannot supply action arguments. The runner's default-deny and provenance rules in [TRUST.md](TRUST.md) still apply.

## Examples

```sh
utter apps list --json
utter actions list --app firefox --json
utter speak "Utter is ready" --json
python -m assistant models list --json
```

One-shot capture and file transcription need the optional sounddevice/NumPy/STT runtime. File transcription accepts uncompressed 16 kHz WAV inputs.

Assistant dry-runs execute in an isolated daemon process with a four second timeout. The JSON `data.plan` contains the selected route and prepared action arguments; a timeout returns `E_PREVIEW_TIMEOUT` rather than waiting indefinitely.
