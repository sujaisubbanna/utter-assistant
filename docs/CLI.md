# Utter CLI for agents

`utter` drives desktop actions. `assistant` (invoked as `python -m assistant`) manages the runner, models, diagnostics, and installation state. They are separate entry points.

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
| `utter assistant TEXT` / `utter --assistant TEXT` | Route a spoken-style command through Utter. `--dry-run` routes without execution; acting requires `--confirm`. |
| `utter dictation TEXT` / `utter --dictation TEXT` | Type literal text through wtype, falling back to ydotool. `--dry-run` reports what would be typed. |
| `utter listen` | Capture for up to `--timeout SEC` (default 10) and act with `--confirm`; `--transcribe-only` returns recognized text. Requires sounddevice/PipeWire and a local STT model. |
| `utter speak TEXT` | Local TTS through `espeak-ng`, or `espeak` fallback. |
| `utter transcribe --file FILE` | Transcribe uncompressed PCM WAV (16 kHz, mono/stereo) with the configured local STT backend. |
| `utter capabilities --json` | Input/audio backends, TTS, GPU, models, and runner connectivity. |
| `utter schema --json` | Versioned command and error registry. |
| `utter apps list --json` | App profile identifiers and aliases. |
| `utter actions list [--app ID] --json` | Action catalog, optionally scoped to an app. |
| `utter profiles --json` | Loaded profile summary. |
| `utter status --json`, `utter doctor --json` | Runner state and diagnostics. |
| `utter version --json` | Utter version. |

The old `utter --text TEXT` and `python -m utter.daemon` service/bridge interfaces remain available. Management stays under `python -m assistant` (`doctor`, `recommend`, `status`, `models`, `install-state`).

## Exit and error contract

| Exit | Meaning | Error code examples |
|---:|---|---|
| 0 | Completed | — |
| 1 | Action failed or no action matched | `E_ACTION_FAILED`, `E_NO_ACTION` |
| 2 | Usage error | `E_USAGE` |
| 3 | Blocked or explicit confirmation required | `E_BLOCKED` |
| 4 | Required backend unavailable | `E_BACKEND_UNAVAILABLE`, `E_RUNNER_UNAVAILABLE` |
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
