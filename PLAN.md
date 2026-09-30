# utter → plug-and-play assistant — architecture plan (v2)

Modular, open-source, plug-and-play local assistant: a tiny **runner** plus swappable
**plugins** (any language). Linux-only v1 (Wayland/niri first). Name: **utter**.
License: **Apache-2.0** (runner + plugin SDK). Vocalinux: **keep the bridge** (hardened).

**Cost boundaries:** runner is small/fixed; **models/STT RAM+VRAM are the user's choice** —
we *recommend* a profile from specs (§10) and never bundle models.

**Footprint reality:** models own ~8.9 GB RSS / ~42 GB VRAM here; the Python daemon is
~50 MB standalone / ~272 MB inside vocalinux. **Justify the Rust runner by determinism,
robustness and packaging (single binary vs venv) — not memory or latency** (IPC is sub-ms;
inference dominates). Unaffected: whisper RSS, vocalinux, vLLM, GUI baseline.

> v2 incorporates an independent @oracle review. The most important change: **build the
> trust/policy layer and one end-to-end vertical slice first; defer the Rust port, WASM,
> registry and the full method vocabulary until real plugins exist.** Freeze only framing +
> handshake at M0.

---

## 1. Principles

1. **Runner is a supervisor and the trust boundary** — single Rust/tokio binary; owns
   hotkeys, event loop, context cache, plugin lifecycle, IPC, config, and **policy**.
2. **Everything else is a plugin** behind a versioned protocol; any language.
3. **Local-first; a remote API is just another plugin.**
4. **Untrusted input may select, never author** (prompt-injection defence, §8).
5. **Incremental** — validate "swappable plugins" with real consumers before porting.

---

## 2. Protocol & transport

- **JSON-RPC 2.0**, `Content-Length`-framed (LSP base protocol).
  - **stdio** for runner-spawned plugins → data plane = tmp-file handles only.
  - **`$XDG_RUNTIME_DIR/utter/runner.sock`** for persistent/clients/UI → may use fd passing.
  - If a child needs fds, spawn it with a **socketpair** and use `recvmsg`/`sendmsg` (never
    `SCM_RIGHTS` over stdio pipes); otherwise an explicit `fd.pass` control frame.
- **MCP is an adapter, not the ABI** (no low-latency audio, stdio out of scope, no OS-event
  registration). Add a bidirectional MCP adapter later.
- **Flow-control / stream semantics (must be specified):**
  - *lossy* streams (audio frames, `llm.delta`, `tts.audio`): bounded queue, drop-oldest, never block the loop.
  - *reliable* streams (control, `*.final`, `action.invoke`): credits/ack.
  - **`$/cancel`** is best-effort and cascades runner→plugin→HTTP; `stop` is idempotent;
    cancelling frees tmp-file handles (lease/refcount GC).
  - **plugin instance epoch/generation** in correlation ids; reject late replies from a
    pre-restart instance; graceful drain before kill. In-process builtins don't hot-reload.
- **Data plane = capabilities, not paths:** content-addressed, plugin-scoped, unguessable
  handles; `O_TMPFILE`+`linkat` or unique-temp+rename; TTL/refcount GC; a handle can never
  be turned into an arbitrary-path read. Continuous audio prefers `memfd` ring-buffer fd.
- **Host-callback surface (must be defined):** plugins may call back into the runner —
  `host.context()`, `host.perceive()`, `host.action()`, `host.confirm()`, `host.emit()` —
  so composites (a11y→vision click) aren't duplicated or smuggled into one mega-plugin.

---

## 3. Manifest & compatibility

`utter-plugin.toml` (three distinct version axes: **protocol**, **runner ABI**,
**capability vocabulary**):
```toml
name="utter-stt-whisper"; version="0.3.1"; kind="stt"
protocol="1.0"; min_runner="0.4.0"; abi="1"          # wire / runner / ABI
runtime="subprocess"; transport="stdio"              # subprocess|wasm|native ; stdio|connect
entrypoint=["python","-m","my_stt_plugin"]
provides=["stt.pull","audio.pcm_f32le@1","audio.rate.16000"]
requires=["host.audio.ringbuffer","fs.tmp"]
permissions=["microphone","filesystem.read"]         # gated + consented + ENFORCED (or advisory, stated)
platforms=["linux-x86_64"]
models=[{name="ggml-small.en.bin", source="hf:ggerganov/whisper.cpp", sha256="…", bytes=487000000}]
config_schema="schema.json"
```
- **Capability registry is the source of truth** in `protocol/` (owner + versioned;
  `experimental/` namespace for extension — LSP escape hatch).
- `protocol.hello` returns the **negotiated** version; runner computes
  `provides ∩ requires`.
- **Strict config validation** (unknown/mistyped keys warn) + config migration path.
- **Compatibility/deprecation policy:** support protocol N-2; document deprecations;
  `doctor` reports drift vs the install lockfile.
- **`doctor`** cheap by default; `doctor --deep` does model load + latency-budgeted round-trip.

---

## 4. Plugin taxonomy (revised from review)

| Kind | Methods | Notes |
|------|---------|-------|
| **router** | `router.plan{utterance,context}` → `Plan` | **rules + candidate-building + decide are ONE unit** (they share the app/site/niri catalog). Builtin initially; can be a plugin later. |
| **knowledge / catalog** | `catalog.apps/sites/niri/media` | static knowledge (app profiles, SITES, niri phrases, CLI agents). Separate lifetime/trust from live state. |
| **llm** | `llm.complete`, **`llm.choose{utterance,candidates}` → `{choice,probability,distribution}`** | the "Jev head" is an `llm.choose` capability (thin), not its own kind. |
| **stt** | `stt.transcribe{audio}`, `stt.subscribe` → `stt.partial/final` | plugin-owned capture preferred |
| **perceive** | `perception.snapshot/find/ocr` → handles/bboxes | untrusted output |
| **action** | `action.capabilities`, `action.invoke{op,args}`, `action.cancel` | ops are **strings + schema**, not the `Action` enum |
| **input** | watch PTT keys / inject (highest-risk) | mostly native/builtin |
| **tts** | `tts.speak` → `tts.audio` | |
| **context** | `context.snapshot`, `context.subscribe` | live desktop state only |
| **ui** | `ui.render`, events only | **config is owned by the runner**, not UI |

- **Action vocabulary is strings** (`open_url`, `ensure_url`, …) with a JSON Schema; the
  Python `Action` enum and `_do_{value}` dispatch become a *reference implementation*, not
  the public ABI.
- A ms-class **embedding classifier** for decisions is an in-runner builtin (not a subprocess).

---

## 5. Safety, policy & trust (new — must-fix from review)

- **Runner enforces policy**, argument-bearing: confirmation shows the **concrete URL /
  command / target**, re-validates after the user confirms (TOCTOU), and is a UI channel.
- **Prompt-injection defence:** provenance tagging — *user utterance = trusted*; screen /
  a11y / OCR / titles / clipboard / web = **untrusted**. Untrusted content **may only select
  among precomputed candidates; it may never author new `args`.** Keep the constrained
  decide head non-optional on the LLM path; truncate/sanitize titles; never let screen text
  become a `terminal` command or an `open_url` scheme.
- **`terminal` is off by default**, a separate capability requiring confirmation (no
  LLM-derived shell strings by default); restrict `open_url` schemes and `launch_app` argv.
- **Socket trust:** socket dir `0700`, socket `0600`, verify **`SO_PEERCRED`**, allow-list
  clients, rate-limit. Any same-uid process must not be able to drive actions.
- **Permission enforcement:** subprocess plugins run under systemd-run hardening
  (`NoNewPrivileges`, `RestrictAddressFamilies`, `DeviceAllow`, `ReadOnlyPaths`,
  seccomp/landlock or bubblewrap). If a permission can't be enforced, it is documented as
  **advisory** — never implied safe.
- **Secrets:** keyring/libsecret or 0600; redacted from logs/doctor; screen/clipboard never
  logged by default.
- **Supply chain:** plugins are untrusted code at user privilege — sign + pin digests,
  explicit consent, scoped sandbox on install; model downloads pinned by sha256 over https.

---

## 6. vocalinux integration (user choice: keep the bridge — hardened)

- Keep **A** (thin Python shim: `socket`+`json`, patches `inject_text`, forwards text+mode to
  the runner) — **but**: pinned vocalinux version range, `inspect.signature` validation +
  **contract test** in `doctor`, all patching isolated in one module, and **fail-safe** (if
  the runner socket is down, call the original `inject_text`; never swallow text silently).
- Roadmap: **B** native evdev + whisper-rs + PipeWire (eventual default), **C** upstream hook.
- **Licensing gate:** never distribute a patched vocalinux (AGPL); the shim runs inside the
  user's own venv. Confirm the IPC boundary before the OSS release.

---

## 7. UI — two separate things

### 7a. Standalone settings window — `utter-gui` (NOT the Noctalia widget)
GTK4 + libadwaita (gtk-rs), a **separate binary** from the runner; a **client** of the
runner socket; owns no state (writes go through `config.set`, applied live). Pages:
- **General / Services:** **autostart** toggle (systemd user unit + XDG autostart), start /
  stop / restart runner, vision, planner, audio-defaults units; status + logs.
- **Voice:** PTT key **capture** (dictation + assistant), STT plugin switch (whisper.cpp /
  faster-whisper / Vosk / Parakeet / remote), model + language, input device (RNNoise
  source), mic-level test.
- **Models:** installed list, **download/pull** (resumable, progress), remove, verify
  (sha256), storage path + disk usage, **"recommend for my hardware"**.
- **LLM:** provider switch (vLLM / Ollama / llama.cpp / remote), endpoint + model,
  `decide_threshold`, enable/disable the decision head.
- **TTS:** enable/disable, engine + voice, test.
- **Perception:** vision on/off + model; accessibility toggle.
- **Plugins:** installed list (kind/version/status), enable/disable, configure from
  `config_schema`, install from file/URL, **permission consent**, `doctor`.
- **Safety:** confirmation policy, blocked/off-by-default actions (e.g. `terminal`),
  allow-lists.
- **Diagnostics:** live log tail, `doctor` report, export support bundle.

### 7b. Noctalia widget (optional *extra*, unchanged)
Luau plugin: runner writes an atomic JSON state file; edge events via
`noctalia msg plugin <id>:<entry> focused <event> <json>` → `onIpc`/`update()` →
`noctalia.state` → widget renders; plus a persistent overlay attention panel. No hot-path
subprocess polling.

---

## 8. Repo layout

```
core/            # Rust runner (tokio)
gui/             # utter-gui (gtk4 + libadwaita)
protocol/        # spec, JSON Schema, capability registry, generated bindings
plugins/         # stt/ router/ llm/ perceive/ action/ input/ tts/ context/ ui/
install/         # utter-install + doctor
data/ profiles/ sounds/ docs/
```
Existing `utter/` Python = reference implementation; wrapped as `builtin` plugins so
nothing regresses.

---

## 9. Installer, model store, registry

- **`utter-install`** (Rust): `/etc/os-release` → pacman/apt/dnf/zypper; deps (`wtype`,
  `ydotool`+`ydotoold`, `grim`, `wl-clipboard`, `pipewire`, `gtk4`, `libadwaita`, optional
  `keyd`); **print** commands without sudo; never silently change groups (show `uinput`
  udev + re-login).
- **Binaries:** prebuilt **static-musl** via cargo-dist (checksums/attestations) for
  core/CLI; **the GTK4 GUI is not musl-static** (ships per-distro or as a normal dynamic
  binary). Not AppImage/Flatpak for the daemon (Flatpak blocks AT-SPI/uinput/hotkeys).
- **systemd user service** bound to the **graphical session** (not linger) + Wayland
  readiness wrapper (`$XDG_RUNTIME_DIR` discovery, retries); hardening; avoid `PrivateTmp`
  (tmp-file data plane).
- **Model store (Ollama-style):** XDG paths, content-addressed `manifests/`+`blobs/`,
  resumable range downloads (**defer a hand-rolled parallel downloader in v1**; use a
  proven downloader), sha256, atomic rename, disk-space preflight, pull lock, refcount GC
  vs `install.json`, Range-unsupported fallback.
- **Install manifest** `$XDG_STATE_HOME/utter/install.json` → reversible
  `assistant uninstall --purge` (prints package removals); idempotent.
- **Registry:** convention-first — static `index.json` + **custom repo URLs** (HACS-style) +
  offline `plugin install ./foo.lvpkg`; define the package layout + **one** signing chain
  (minisign over tarball + signed index). Defer OCI + MCP-registry adapter.

---

## 10. Hardware-aware recommendations (we suggest, user decides)

`assistant recommend [--json]` probes CPU/RAM/GPU (nvidia-smi, vulkaninfo, lspci, ROCm,
`/dev/accel*`)/compositor → suggests profile + estimated RAM/VRAM. STT: CPU→whisper.cpp
tiny/base/small int8; NVIDIA≥8GB→faster-whisper/Parakeet large-v3-turbo; AMD/Intel→Vulkan.
LLM: ≥24GB→7–8B AWQ; 8–16GB→4B AWQ; ≤8GB→1.5–3B/CPU; or existing endpoint. Vision: ≥16GB→7B;
≥6GB→UI-TARS-2B; else a11y-only. Zero-model mode works (rules + context + a11y).

---

## 11. Build order (revised from @oracle)

**M0 — de-risk the hard parts (keep the daemon in Python)** — ✅ **DONE**
- Framing + `protocol.hello`/`plugin.describe`/`plugin.health` + error taxonomy + `$/cancel`
  + deadlines ✅
- Conformance harness with fakes in **Python + Rust** ✅ (20/20)
- Vertical slice: router → policy/confirmation → action ✅ (44/44 e2e)
- Measurement spike ✅ (RPC p50 0.028 ms / p95 0.056 ms; cancel idempotent; handle hash
  matches; crash-restart epoch 0→1 with clean in-flight error)
- Trust-model doc + version policy ✅
Residual gaps → **M1**.

**M1 — close the M0 gaps and harden** — ✅ **DONE**
- Client streams + flow control end-to-end: `stream.subscribe/ack/stop`; **lossy** drop-oldest
  (seq gaps) and **reliable** credit window (pauses at 64, resumes on ack) ✅
- `runner.invoke` (policy applied, `provenance` required for side effects) + `runner.validate_plugin`
  (negotiated, unknown caps warn, missing requires fail, per-permission enforced/advisory) ✅
- Handles over the client API (`handle.create/fetch/stat`, `-32007`) + **`fd.pass`** (`handle`,
  `memfd`) via `SCM_RIGHTS` over the socket ✅
- Plugin **socket transport** (`connect`/`listen`) in addition to stdio ✅
- `[socket]` **default-deny** (allow-list / token; `SO_PEERCRED`) ✅
- `[security] enforce` spawns under a hardened wrapper (`systemd-run`→`bwrap`), reported
  enforced-vs-advisory ✅
- `action.terminal` explicit opt-in ✅
Verified: **79/79 unit · 86/86 socket e2e · 60/60 conformance (1 skip)**; RPC p50 ~0.04 ms.
Residual (accepted, M2+): `memfd` is a plain memfd, not a true ring buffer (no wrap-around
cursor yet); runner→plugin fd passing not implemented; reliable streams buffer (bounded) rather
than backpressuring the producer; stream-scoped handle refcount on `stop` not tracked.

**M2** bulk-data layer tied to the first real consumer (STT), not built abstractly.
**M3** wrap the real Python assistant as plugins — ✅ **DONE**
`plugins/utter_py` wraps `utter/` (router + Jev decision head + real actions/context)
with dry-run; `config.m3.toml`; `tests/m3/verify_m3.py` **20/20**. Real action verified:
`runner.command "open youtube"` → `ensure_url` → activated Zen's existing YouTube tab via BiDi.
No M0/M1 regression (79/79 · 86/86 · 60/60).
**M4/M5/M7** `doctor` + install manifest + installer + graphical-session unit + model store —
✅ **DONE** (`assistant` CLI: `doctor`/`recommend`/`status`/`models`/`install-state`;
`install/{install,uninstall}.sh` + `install/utter-runner.service` +
`scripts/utter-wayland-ready.sh`; content-addressed resumable model store). Verified:
M5 24/24, installer `--dry-run` + `systemd-analyze` rc 0, `doctor --json` against a
wrapper-started runner.
**M6** standalone **`utter-gui`** + optional Noctalia widget + **assistant-mode OSD** — ✅ **DONE**
**UI decision (revised):** the settings UI is now the **Tauri v2 app** (`gui-tauri/`) — a clean,
modern web UI with a **Light/Dark/System** toggle (persisted, follows the system live) and matugen
palette hot-swap. Superseded: the GTK4 + libadwaita alternative (least memory, PSS ≈ 79 MB) is kept
in `gui/` for reference only.
- **Tauri GUI** (`gui-tauri/`): 10 pages, 24 Rust commands; Tailwind v4 token bridge over the
  matugen palette (`src-tauri/src/theme.rs` + debounced `notify` watcher); `pnpm tauri build` → deb
  (CI adds AppImage/rpm).
- **GTK4 GUI** (`gui/`, legacy): 9 pages; matugen theming via `gui/utter_gui/theme.py`
  (CssProvider + `Gio.FileMonitor` live reload) + `scripts/install-matugen-utter.sh`
  (installed: adds `[templates.utter]`, palette at `~/.local/share/utter/colors.css`).
- **Noctalia plugin** (`plugins/ui/noctalia/`): bar widget + persistent attention panel + OSD
  panel (verified with screenshots; attention panel closes when the runner is up).
- **OSD**: driven by `$XDG_RUNTIME_DIR/utter/osd.json` (`idle|listening|final` + `level` +
  `text` + `activated`); emitter `utter/voice/osd.py` (`[osd]` config) — live level meter +
  best-effort windowed transcript, then green (activated) / red (not), auto-dismiss.
- `scripts/verify.sh` is now **hermetic** (throwaway `XDG_RUNTIME_DIR`) so it can't collide with a
  live `utter-runner` service socket.
**M8** registry → MCP adapter → (optional) WASM tier and native Rust port **driven by
profiling**, not upfront.

Cut from v1: WASM/Extism, OCI, MCP adapter, deep GTK features, default latency benchmarking.

---

## 12. Open items

- Registry now vs later (plan: static index/custom repos now; OCI/MCP later).
- First plugin SDKs: Python + Rust (TypeScript next).
- Licensing gate for the vocalinux bridge before OSS release.
- Decide when (if) to port the Python core to Rust — after profiling shows a real bottleneck.

## 13. Risks

Prompt injection via screen/utterance (mitigated by select-never-author + non-optional
constrained decisions); protocol/MCP drift (pin versions); ydotool/keyd packaging varies
(probe); cargo-dist lacks cross-compilation (native runners); measure RPC budgets on the
real target.

## 14. Packaging, installer & UI (in flight)

- **UI ✅** (reconciled): Tauri v2 app (`gui-tauri/`) — clean/modern, **Light/Dark/System**
  theme toggle (persisted, follows the system live), matugen palette + debounced hot-swap.
  10 pages, 24 Rust commands; `pnpm tauri build` → deb, CI adds AppImage/rpm. GTK4 (`gui/`)
  is superseded (kept for reference).
- **Packaging / CI ✅** (reconciled): `.github/workflows/release.yml` builds **AppImage + deb
  + rpm** from `gui-tauri/` on `ubuntu-24.04` plus `utter-core-<ver>.tar.gz`
  (+ `sha256sums.txt`) and attaches them to the Release; `.github/workflows/pages.yml`
  publishes `install.sh` for `curl … | bash`. Artifacts:
  `utter-gui_<ver>_amd64.AppImage`, `utter-gui_<ver>_amd64.deb`,
  `utter-gui-<ver>-1.x86_64.rpm`, `utter-core-<ver>.tar.gz`, `sha256sums.txt`.
- **Installer ✅** (reconciled): `install.sh` is an **interactive step-by-step wizard** —
  9 steps (system deps → core → systemd units → models → GUI → STT → perception → optional
  Noctalia widget → config), Enter = recommended default, `y/n/a/s/q`, plan review + confirm,
  per-component install-state, `--uninstall` menu; `--yes` for `curl | bash`, no-TTY without
  `--yes` prints the plan and changes nothing. `scripts/build-core-tarball.sh` builds the core
  tarball (now including `widgets/`). Docs: `docs/RELEASING.md`, `docs/INSTALL-FROM-WEB.md`.
  Remaining gaps: STT/perception steps are advisory (no distributable artifact); model tiers
  need an explicit `UTTER_MODEL_*` source; aarch64 + code signing deferred; Pages must be
  enabled once and the repo owner placeholder set.
- **Noctalia widget is optional**: package at `widgets/noctalia/` (moved from
  `plugins/ui/noctalia/`), installed only via `install.sh --with-noctalia` or
  `widgets/noctalia/install.sh`; never installed by default.


