# Architecture

## 1. What it is
A local, context-aware voice → desktop-action assistant. The design goal is a **tiny runner**
(supervisor + trust boundary) with **everything else as swappable plugins** in any language.

## 2. Why this shape (footprint reality)
On the reference machine the **models dominate**: vLLM owns ~8.9 GB RSS / ~42 GB VRAM; the
combined Python dictation process is ~272 MB; noctalia 208 MB. A Rust runner (~3 MB) saves
~30–50 MB — **~0.05% of RAM**. So the port is justified by **determinism, robustness and
packaging (single binary vs venv), not memory**. Local plugin RPC is **~0.04 ms**; inference
is hundreds of ms — so protocol latency is irrelevant next to model latency. **Defer the Rust
port until profiling shows a bottleneck.**

## 3. Topology
```
                     ┌─────────────────────────────┐
   hotkeys (evdev) ─▶ │           RUNNER            │ ◀── config (TOML)
   audio (pipewire)─▶ │  event loop · context cache │ ◀── clients / GUI (unix socket)
                      │  plugin supervisor · policy │
                      └───────┬─────────┬───────────┘
              JSON-RPC 2.0 (Content-Length) over stdio / unix socket
   ┌──────────┬───────────┼──────────────┬──────────────┬─────────┐
 stt        router       llm          perceive        action     ui
(whisper)  (+decide)  (vllm/ollama)  (a11y/vision)  (niri/input) (bar/gui)
```

## 4. Protocol (see `protocol/PROTOCOL.md`)
- **JSON-RPC 2.0**, `Content-Length`-framed (LSP base protocol).
- **Transports**: `stdio` (runner spawns the plugin) or unix socket
  (`connect`/`listen`, `$XDG_RUNTIME_DIR/utter/plugins/<id>.sock`).
- **Handshake (frozen)**: `protocol.hello → plugin.describe → plugin.health`; the runner
  negotiates protocol/abi, validates `provides ∩ requires`, and records an **epoch**.
- **Three version axes**: `protocol` (wire), `abi` (runner↔plugin), `capability` (`name@N`).
- **Streams**: `stream.subscribe/ack/stop`; **lossy** (drop-oldest, seq gaps) vs **reliable**
  (credit window, pause/ack). Notifications: `<method> {stream_id, seq, data}`.
- **Data plane**: content-addressed **handles** (`handle://sha256`), `handle.create/fetch/stat`
  (inline ≤64 KiB, else `-32007`), and **`fd.pass`** via `SCM_RIGHTS` (`handle`, `memfd`).
- **Host callbacks**: plugins may call `host.context/perceive/action/confirm/emit`.

## 5. Plugin taxonomy
| Kind | Role |
|------|------|
| `router` | utterance + context → ordered steps (rules + candidate building + decision head) |
| `llm` | `complete` and **`choose`** (the constrained "Jev head" over candidates) |
| `knowledge` | static catalog: apps, sites, niri actions, media keys |
| `stt` | audio → text (pull/stream) |
| `perceive` | screenshot / a11y / OCR / browser tabs |
| `action` | executors (niri, input, media, browser, terminal, launcher) |
| `input` | PTT keys / injection (highest risk; mostly native) |
| `tts` | speech output |
| `context` | live desktop state |
| `ui` | declarative render + events (config is owned by the runner) |

Manifest: `utter-plugin.toml` validated by `protocol/plugin.schema.json`.

## 6. Trust & policy (see `docs/TRUST.md`)
- **Provenance tagging**: user utterance = trusted; screen/a11y/OCR/titles/clipboard = untrusted.
- **Select, never author**: untrusted content may only choose among precomputed candidates;
  any concrete args derived from it are rejected (`-32006`). The constrained decision head is
  the enforcement mechanism.
- **Runner-enforced, argument-bearing confirmation** with post-approval re-validation (TOCTOU).
- **Dangerous ops off by default** (`terminal`, `input`); `open_url` scheme allow-list.
- **Socket default-deny** (`SO_PEERCRED` allow-list / token); **`[security] enforce`** sandboxes
  plugin subprocesses (systemd-run/bwrap) and reports enforced vs advisory.

## 7. Lifecycle & failure handling
- Plugin instances are `(plugin_id, epoch)`; **restart increments the epoch** and stale-epoch
  replies are dropped. Graceful drain (stdin EOF → terminate → kill).
- `$/cancel` is best-effort and cascades; `stream.stop` is idempotent and frees buffers.
- Crash of a plugin → supervisor respawns with a new epoch; in-flight requests error cleanly.

## 8. Compatibility
See `docs/COMPATIBILITY.md`: N-2 protocol support, capability registry governance, deprecation,
config-schema migration, install lockfile, stable `doctor` output.

## 9. Deployment
- The legacy assistant runs via **systemd user units** (bridge/vision/planner/audio-defaults),
  bound to the session, with a Wayland-readiness wrapper.
- The modular runner is a user service too; clients (GUI, Noctalia widget) connect to
  `$XDG_RUNTIME_DIR/utter/runner.sock`.
- Installer (planned): `/etc/os-release` detection → pacman/apt/dnf/zypper; prebuilt static-musl
  core (GTK4 GUI is dynamic, not musl); **not** AppImage/Flatpak for the daemon.

## 10. Milestones
M0 ✅ protocol/runner/conformance/spike · M1 ✅ streams/flow-control/handles/fd/socket/security ·
M3 ✅ real assistant as a plugin · then installer, GUI + Noctalia widget, model store.
See `PLAN.md`.
