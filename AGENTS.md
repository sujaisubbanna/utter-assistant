# AGENTS.md — utter

Guidance for AI agents (and humans) working in this repo.

## What this is
A local, context-aware **voice → desktop-action** assistant, being turned into a modular,
open-source, plug-and-play product: a tiny **runner** (supervisor + trust boundary) plus
swappable **plugins** for STT, decision ("Jev head"), LLM, perception, actions, TTS, context
and UI. **Linux only for now** (Wayland/niri first).

Two things coexist in this repo right now:
1. **The original Python assistant** (`utter/`) — production code, currently run by
   systemd user units (`utter-bridge`, `utter-vision`, `utter-planner`,
   `utter-audio-defaults`). It keeps working; do not regress it.
2. **The new modular core** (`runner/`, `protocol/`, `plugins/`, `tests/`, `docs/`) — the
   M0/M1 protocol + reference runner, with the real assistant being wrapped as a plugin (M3).

## Repo map
```
protocol/   PROTOCOL.md, capabilities.json, plugin.schema.json   # frozen contracts
docs/       ARCHITECTURE.md, TRUST.md, COMPATIBILITY.md, PLUGINS.md, APPS.md, CUSTOMISING.md
runner/     Python reference runner host (framing, rpc, plugins, streams, handles, policy, socket, security)
plugins/    fake_py/ + fake_rs/ (conformance fakes), utter_py/ (the real assistant as a plugin)
tests/      conformance/ (independent suite + report.json), m3/ (real-plugin verification)
scripts/    verify.sh, m0_spike.py, zen_bidi.py, serve_*.sh, gen_*.py
utter/   the original Python assistant (router, executor, context, actions, vision, voice, profiles, data)
PLAN.md     the architecture plan + milestone status
```

## Contracts — read before changing anything
- `protocol/PROTOCOL.md` — framing + handshake are **frozen**; M1 additions in §10–14.
- `protocol/capabilities.json` — the single source of truth for capability strings.
- `protocol/plugin.schema.json` — manifest schema.
- `docs/TRUST.md` — provenance + policy rules (do not weaken).
- `docs/COMPATIBILITY.md` — version axes (protocol / abi / capability) + deprecation.

## Run & verify
```bash
scripts/verify.sh          # runner unit + e2e + conformance + spike (use before declaring done)
.venv-agent/bin/python -m runner._selftest
.venv-agent/bin/python tests/conformance/run.py
.venv-agent/bin/python scripts/m0_spike.py
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

## Task conventions
- Work in **bounded lanes** with a single writer per file/dir; announce ownership.
- Update `PLAN.md` milestone status when you finish a milestone.
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
- **M0 ✅** — framing/handshake, runner host, conformance (Python+Rust), spike, trust doc.
- **M1 ✅** — streams + flow control, `runner.invoke`/`validate_plugin`, handles + `fd.pass`,
  socket transport, default-deny, sandbox wrapper, `terminal` opt-in. (79/79 unit, 86/86 e2e,
  60/60 conformance, RPC p50 ~0.04 ms.)
- **M3 ✅** — the real assistant is wrapped as `plugins/utter_py`; `runner.command
  "open youtube"` drives the real rules + Jev head + actions end-to-end (dry-run default;
  `tests/m3/verify_m3.py` 20/20).
- **Next** — installer, GTK4 settings GUI + Noctalia widget, model store.
