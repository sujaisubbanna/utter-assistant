---
title: "Architecture"
description: "The runner, the protocol, the plugin taxonomy, trust boundaries, lifecycle and deployment, in one page."
---

Utter is a local, context-aware voice → desktop-action assistant. The design goal is a **tiny
runner** (supervisor plus trust boundary) with **everything else as swappable plugins** in any
language.

## Why this shape

The models dominate the footprint by a wide margin: a vLLM server owns gigabytes of RAM and tens
of gigabytes of VRAM, while the Python assistant process sits in the low hundreds of megabytes.
A Rust runner would save tens of megabytes, a rounding error. Local plugin RPC costs tens of
microseconds; inference costs hundreds of milliseconds, so protocol latency is irrelevant next
to model latency. The runner is therefore judged on **determinism, robustness and packaging**,
not memory, and a Rust port is deferred until profiling shows a bottleneck.

## Topology

```text
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

## Protocol

- **JSON-RPC 2.0**, `Content-Length`-framed (the LSP base protocol).
- **Transports**: `stdio` (the runner spawns the plugin) or a unix socket (`connect` or
  `listen`) at `$XDG_RUNTIME_DIR/utter/plugins/<id>.sock`.
- **Handshake (frozen)**: `protocol.hello`, then `plugin.describe`, then `plugin.health`. The
  runner negotiates protocol and abi, validates `provides ∩ requires`, and records an **epoch**.
- **Three version axes**: `protocol` (wire), `abi` (runner to plugin), `capability` (`name@N`).
- **Streams**: `stream.subscribe`, `stream.ack`, `stream.stop`; **lossy** (drop-oldest with
  `seq` gaps) or **reliable** (credit window with pause and ack).
- **Data plane**: content-addressed **handles** (`handle://sha256`) with inline fetch up to
  64 KiB, and **`fd.pass`** over `SCM_RIGHTS` for handles and memfds.
- **Host callbacks**: `host.context`, `host.perceive`, `host.action`, `host.confirm`,
  `host.emit` (only `host.confirm` is wired today).

Full detail: [Plugin protocol](/plugins/).

## Plugin taxonomy

| Kind | Role |
|---|---|
| `router` | utterance + context → ordered steps (rules, candidate building, decision head) |
| `llm` | `complete` and the constrained **`choose`** over candidates |
| `knowledge` | static catalog: apps, sites, niri actions, media keys |
| `stt` | audio → text (pull or stream) |
| `perceive` | screenshot, accessibility, OCR, browser tabs |
| `action` | executors: niri, input, media, browser, terminal, launcher |
| `input` | push-to-talk keys and injection (highest risk; mostly native) |
| `tts` | speech output |
| `context` | live desktop state |
| `ui` | declarative render and events (config is owned by the runner) |

Manifest: `utter-plugin.toml`, validated by `protocol/plugin.schema.json`.

## The Python core

The legacy assistant, now wrapped as the `utter_py` bundle plugin, is organised as:

```text
utter/
  types.py, config.py          interfaces + config
  context/niri.py              focused window / monitors / workspaces / focus window
  context/clipboard.py         wl-paste
  context/atspi.py             accessibility tree dump
  actions/launch.py            launch app (.desktop Exec), open URL (xdg-open)
  actions/keyboard.py          wtype / ydotool key + type
  actions/mouse.py             ydotool move/click/scroll (needs ydotoold)
  actions/a11y_action.py       invoke an AT-SPI action on a node
  vision/screenshot.py         grim capture + multi-monitor geometry
  vision/client.py             HTTP client to the vLLM UI-TARS server
  router/profiles.py           load app profiles
  router/rules.py              deterministic rule engine -> Plan
  router/decide.py             constrained decision head -> Plan
  router/planner.py            tiny-LLM fallback -> Plan
  voice/hotkey.py              evdev push-to-talk global hotkey
  voice/stt.py                 faster-whisper / whisper.cpp transcription
  daemon.py                    ties it together
  profiles/*.yaml              per-app rules
```

Tiers, cheapest first: **T0 App** (focused window, profiles, URL handlers), **T1 Accessibility**
(AT-SPI), **T2 Keyboard** (per-app shortcuts), **T3 Vision** (screenshot grounded by UI-TARS).
All executors are safe by construction: no shell, list arguments only, and context is re-read
after any mutation before the next step.

## Trust and policy

- **Provenance tagging**: the user's utterance is trusted; screen, accessibility, OCR, titles
  and clipboard are untrusted.
- **Select, never author**: untrusted content may only choose among precomputed candidates; any
  concrete args derived from it are rejected (`-32006`). The constrained decision head is the
  enforcement mechanism.
- **Runner-enforced, argument-bearing confirmation** with post-approval re-validation.
- **Dangerous ops off by default** (`terminal`, `input`); `open_url` scheme allow-list.
- **Socket default-deny** (`SO_PEERCRED` allow-list or token); `[security] enforce` sandboxes
  plugin subprocesses and reports enforced versus advisory.

Full detail: [Trust and safety](/guides/trust-and-safety/).

## Lifecycle and failure handling

- Plugin instances are `(plugin_id, epoch)`; **restart increments the epoch** and stale-epoch
  replies are dropped. Graceful drain: stdin EOF, terminate, kill.
- `$/cancel` is best-effort and cascades; `stream.stop` is idempotent and frees buffers.
- A crashed plugin is respawned by the supervisor with a new epoch; in-flight requests error
  cleanly.

## Compatibility

The reference runner accepts exactly protocol `1.0` / abi `1`; any mismatch is refused (there is
no N-2 window yet). The capability registry is governed with deprecation entries, the installer
records a lockfile that `doctor` compares against reality, and `doctor` output has stable fields.
Versioned, migrated config schemas are **planned, not implemented**. See the compatibility
section of [Plugin protocol](/plugins/#compatibility).

## Deployment

- The runner is a **systemd user unit**, bound to the graphical session, started through a
  Wayland-readiness wrapper that discovers the session environment.
- Clients (the settings app, the Noctalia widget) connect to `$XDG_RUNTIME_DIR/utter/runner.sock`.
- The installer detects the distro from `/etc/os-release` and uses pacman, apt, dnf or zypper for
  system dependencies. The settings app ships as an AppImage, `.deb` and `.rpm`; the Python core
  ships as a tarball. The daemon is deliberately **not** an AppImage or Flatpak.

## Settings app

The settings app (Tauri v2 + React) is a pure client. It edits `~/.config/utter/config.toml`
with a comment-preserving TOML editor, shells out to the `assistant` CLI with list arguments
(never a shell string), drives systemd user units, streams model-pull progress and log lines
through events, and watches the matugen palette for live theming. No assistant logic lives
there.
