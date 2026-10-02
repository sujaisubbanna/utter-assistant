# AGENTS.md — utter

Guidance for AI agents (and humans) working in this repo.

## What this is
A local, context-aware **voice → desktop-action** assistant, being turned into a modular,
open-source, plug-and-play product: a tiny **runner** (supervisor + trust boundary) plus
swappable **plugins** for STT, decision ("Jev head"), LLM, perception, actions, TTS, context
and UI. Natively supported on **Linux** (Wayland: niri and KDE Plasma/KWin via `utter/context/compositor.py`,
see `docs/PLASMA.md`) and **macOS** (native Speech/Quartz backends behind
`utter/platform.py`, see `docs/MACOS.md`).

Two things coexist in this repo right now:
1. **The original Python assistant** (`utter/`) — production code, currently run by
   systemd user units (`utter-bridge`, `utter-vision`, `utter-planner`,
   `utter-audio-defaults`). It keeps working; do not regress it.
2. **The modular core** (`runner/`, `protocol/`, `plugins/`, `tests/`, `docs/`) — the
   protocol + reference runner, with the real assistant wrapped as `plugins/utter_py`.

## Repo map
```
protocol/   PROTOCOL.md, capabilities.json, plugin.schema.json   # frozen contracts
docs/       ARCHITECTURE.md, TRUST.md, COMPATIBILITY.md, PLUGINS.md, APPS.md, CUSTOMISING.md
runner/     Python reference runner host (framing, rpc, plugins, streams, handles, policy, socket, security)
plugins/    fake_py/ + fake_rs/ (conformance fakes), utter_py/ (the real assistant as a plugin)
tests/      conformance/ (protocol suite), m3/ (real-plugin verification)
scripts/    verify.sh, zen_bidi.py, serve_*.sh, gen_*.py
utter/   the original Python assistant (router, executor, context, actions, vision, voice, profiles, data)
PLAN.md     the architecture plan
```

## Contracts — read before changing anything
- `protocol/PROTOCOL.md` — framing + handshake are **frozen**; additions in §10–14.
- `protocol/capabilities.json` — the single source of truth for capability strings.
- `protocol/plugin.schema.json` — manifest schema.
- `docs/TRUST.md` — provenance + policy rules (do not weaken).
- `docs/COMPATIBILITY.md` — version axes (protocol / abi / capability) + deprecation.

## Run & verify
```bash
scripts/verify.sh          # full verification (use before declaring done)
```
Use `.venv-agent/bin/python` (Python 3.14) for protocol/runner work. `runner/**` is
**stdlib-only** (no third-party deps). Never use `shell=True`.

## Invariants (do not break)
1. **Framing + handshake are frozen.** Method sets accrete; don't change the envelope.
2. **Provenance: untrusted content selects, never authors.** Screen/a11y/OCR/titles/clipboard
   are untrusted; they may only choose among precomputed candidates, never create `args`.
   Rejection code `-32006`.
3. **`action.terminal`/`action.input` are off by default**; enabling is explicit and confirmed.
4. **Runner enforces policy**; a plugin's `needs_confirm` is only an untrusted hint.
5. **Socket is default-deny** (allow-list/token, `SO_PEERCRED`).
6. **Handles are capabilities, not paths** (`handle://sha256`, plugin-scoped).
7. **Verification is required**: run `scripts/verify.sh`; add checks for new behaviour.
8. **Language is two independent axes**: the UI locale (`gui-tauri/src/i18n/*.ts`, plus
   `install/i18n/*.sh` for the installer) and the *spoken* language (`[stt] language` /
   `[tts] language`). Never couple them. English ships inline; other languages are opt-in
   downloads and nothing is fetched automatically. Every non-English UI locale must keep key
   parity with `en.ts` (`pnpm exec tsc --noEmit` enforces it) — see `docs/TRANSLATING.md`.

## Task conventions
- Work in **bounded lanes** with a single writer per file/dir; announce ownership.
- Keep `PLAN.md` current when you complete planned work.
- Prefer wrapping existing `utter/` code over rewriting; the Rust port is deferred until
  profiling justifies it (local RPC is already ~0.04 ms; inference dominates).
- Keep the legacy assistant running: changes to `utter/**` must not break the systemd units.

## Branching & releases
- **Never commit to `main`.** Every change lands on a feature branch — `fix/…`, `feat/…`
  or `chore/…` — pushed to `origin` for review. `main` is only advanced once the change is
  accepted.
- **Releases are cut on request, not per change.** When the owner asks for a release:
  1. add or update `CHANGELOG.md` with the user-visible changes;
  2. bump the version everywhere it lives — **patch by default** (`0.1.0` → `0.1.1`); reserve a **minor** bump for notable features — `pyproject.toml`,
     `gui-tauri/package.json`, `gui-tauri/src-tauri/Cargo.toml`,
     `gui-tauri/src-tauri/tauri.conf.json` (and any version shown in the UI);
  3. merge to `main`, then tag `v<version>` and push the tag — the `release` workflow
     builds the AppImage/deb/rpm bundles plus the core tarball and attaches them.

## How-to pointers
- **Architecture**: `docs/ARCHITECTURE.md`
- **Write a plugin**: `docs/PLUGINS.md`
- **Apps/steps, adding an app, the Zen case study**: `docs/APPS.md`
- **Customising config/profiles/hotkeys/models**: `docs/CUSTOMISING.md`
- **Trust & permissions**: `docs/TRUST.md`; **versioning**: `docs/COMPATIBILITY.md`

## Current status
- **Runner** — frozen framing/handshake, streams + flow control, `runner.invoke` /
  `validate_plugin`, handles + `fd.pass`, the socket transport with default-deny, and the
  sandbox wrapper. `action.terminal` / `action.input` are opt-in and confirmed.
- **Real assistant** — wrapped as `plugins/utter_py`; `runner.command "open youtube"` drives
  the real rules, decision head and actions end-to-end (dry-run by default).
