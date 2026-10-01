---
title: "The utter CLI (for agents)"
description: "Drive Utter from the command line: assistant, dictation, listen, speak, transcribe, plus capabilities and schema discovery, with a stable JSON contract and documented exit codes."
---

`utter` **drives desktop actions**. `assistant` (invoked as `python -m assistant`) **manages** the
runner, models, diagnostics and installation state. They are separate entry points — this page
covers `utter`; the management commands are on [the assistant CLI](/reference/cli-assistant/) page.

The CLI is built to be driven by another program: every command takes `--json`, output is stable
and versioned, and the exit codes are part of the contract.

## Quickstart

```bash
utter capabilities --json
utter schema --json
utter assistant "open youtube" --dry-run --json
utter dictation "hello" --dry-run --json
utter assistant "open youtube" --json
```

## The JSON contract

Every successful response uses the same envelope:

```json
{ "schema": "utter.cli/v1", "ok": true, "command": "assistant", "data": { } }
```

Errors use the same envelope with `ok: false` and an `error` object:

```json
{ "schema": "utter.cli/v1", "ok": false, "command": "assistant",
  "error": { "code": "E_BLOCKED", "message": "Action execution requires --confirm." } }
```

JSON is printed **only on stdout**; human diagnostics go to stderr. `utter schema --json` is the
machine-readable command and error registry, and returns the complete Draft 2020-12 response
schema (also packaged at `utter/data/cli.schema.json`).

## Commands

| Command | Purpose |
|---|---|
| `utter assistant TEXT` / `utter --assistant TEXT` | Route a spoken-style command. `--dry-run` returns the plan without executing; acting requires `--confirm`. |
| `utter dictation TEXT` / `utter --dictation TEXT` | Type literal text into the focused field (`wtype`, falling back to `ydotool`). |
| `utter listen` | Capture for up to `--timeout SEC` (default 10) and act with `--confirm`; `--transcribe-only` returns the recognised text. |
| `utter speak TEXT` | Local text-to-speech (`espeak-ng`, falling back to `espeak`). |
| `utter transcribe --file FILE` | Transcribe an uncompressed 16 kHz WAV with the configured local STT backend. |
| `utter capabilities --json` | Input/audio backends, TTS, GPU presence and compute runtime, installed models, runner connectivity. |
| `utter schema --json` | Versioned command and error registry plus the full response schema. |
| `utter apps list --json` | App profile identifiers and aliases. |
| `utter actions list [--app ID] --json` | Action catalog, optionally scoped to an app. |
| `utter profiles --json` | Loaded profile summary. |
| `utter status --json`, `utter doctor --json` | Runner state and diagnostics. |
| `utter version --json` | Utter version. |
| `utter settings list\|get\|set` | Read or edit the active TOML settings. |
| `utter commands list\|set\|remove` | List built-in app shortcuts; create or remove per-app custom spoken phrases. |

## Settings and custom commands

Settings use dotted keys matching the config sections. Values passed to `settings set` are JSON
values, type-checked against Utter's config model. Use `--dry-run` to preview; writing requires
`--confirm`. Edits preserve other TOML lines and comments and replace the file atomically.

```bash
utter settings list --json
utter settings get stt.device --json
utter settings set stt.device --value '"cuda"' --dry-run --json
utter settings set audio.sample_rate --value 48000 --confirm --json
```

`commands set APP PHRASE CHORD` adds a phrase for one app: when that app is focused and the phrase
is spoken, Utter sends the configured key chord. It accepts only a bounded printable phrase and a
keyboard chord — it **cannot** define shell commands or arbitrary action arguments.

```bash
utter commands list --app firefox --json
utter commands set firefox "toggle developer tools" ctrl+shift+i --dry-run --json
utter commands set firefox "toggle developer tools" ctrl+shift+i --confirm --json
utter commands remove firefox "toggle developer tools" --confirm --json
```

## Exit and error contract

| Exit | Meaning | Error codes |
|---:|---|---|
| 0 | Completed | — |
| 1 | Action failed or no action matched | `E_ACTION_FAILED`, `E_NO_ACTION` |
| 2 | Usage error | `E_USAGE` |
| 3 | Blocked, or explicit confirmation required | `E_BLOCKED` |
| 4 | Required backend unavailable, or preview timed out | `E_BACKEND_UNAVAILABLE`, `E_RUNNER_UNAVAILABLE`, `E_PREVIEW_TIMEOUT` |
| 5 | Requested app or resource not found | `E_NOT_FOUND` |

Use `--non-interactive` for automation; JSON mode never prompts. Run mutating operations with
`--dry-run` first. Consequential actions require explicit confirmation, and the risky `terminal`
and `input` abilities remain governed by runner policy.

## Safety

CLI text is a **user request**. Screen, accessibility, OCR, clipboard and window-title data remain
**untrusted selectors** and can never supply action arguments — the runner's default-deny and
provenance rules in [Trust & safety](/guides/trust-and-safety/) still apply.

## Notes

- Assistant dry-runs execute in an isolated daemon process with a four-second hard limit; the JSON
  `data.plan` contains the selected route and prepared arguments, and a timeout returns
  `E_PREVIEW_TIMEOUT` rather than waiting indefinitely.
- `utter listen` and `utter transcribe` need the optional sounddevice/NumPy/STT runtime.
- The older `utter --text TEXT` and `python -m utter.daemon` service/bridge interfaces remain
  available.
