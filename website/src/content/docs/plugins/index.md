---
title: "Plugin protocol"
description: "How plugins talk to the runner: JSON-RPC framing, the frozen handshake, manifests, the capability registry, method namespaces, streams, the data plane, permissions and compatibility."
---

A **plugin** is any process that speaks the frozen JSON-RPC protocol and answers at least the
handshake. The **runner** owns policy, confirmation and the data plane; a plugin is otherwise a
plain program in any language. The authoritative spec is `protocol/PROTOCOL.md` in the
repository; this page summarises it. For a hands-on walkthrough see
[Writing a plugin](/plugins/writing-a-plugin/).

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

## Framing and transports

- **JSON-RPC 2.0**, one message per frame.
- **Framing**: `Content-Length: <bytes>\r\n\r\n<utf8 json>`, the LSP base protocol.
- **Transports**:
  - `stdio`: the runner spawns the plugin; stdin and stdout carry frames. No fd passing.
  - `connect` / `listen`: a unix socket at `$XDG_RUNTIME_DIR/utter/plugins/<id>.sock`.
    `connect` means the runner listens and the plugin dials in; `listen` means the plugin
    listens and the runner connects.
- `$/cancel {id}` is best-effort and cascades. `stream.stop` and cancel are idempotent.
  Requests may carry `params.timeout_ms`; the runner enforces a hard maximum of 60 000 ms.

## The handshake (frozen)

```text
runner → plugin   protocol.hello {protocol, abi, runner, epoch}
plugin → runner   {protocol, abi, plugin:{name,version,kind}, transport,
                   provides:[...], requires:[...], permissions:[...]}
runner → plugin   plugin.describe {}  → {methods:[...], streams:[...]}
runner → plugin   plugin.health {}    → {status:"ok"|"degraded", detail}
```

The runner then computes `provides ∩ requires`, validates capabilities, and records an
**epoch**. A plugin instance is `(plugin_id, epoch)`; responses from a stale epoch are dropped,
and a restart increments the epoch. `protocol.hello` returns the **negotiated** version. The
current values are `protocol = "1.0"` and `abi = 1`; a major mismatch fails with `-32004`.

## The manifest

A plugin package ships `utter-plugin.toml`, validated by `protocol/plugin.schema.json`:

```toml
name = "fake_rs"
version = "0.1.0"
kind = "action"
protocol = "1.0"
min_runner = "0.1.0"
abi = 1

runtime = "subprocess"
transport = "stdio"
entrypoint = ["plugins/fake_rs/target/release/fake_rs"]

provides = ["action.open_url@1", "experimental/fake_rs@1"]
requires = ["context.live@1"]
permissions = ["network"]

platforms = ["linux-x86_64"]
```

Required fields: `name`, `version`, `kind`, `protocol`, `abi`, `runtime`, `transport`,
`entrypoint`.

- `name` is the plugin id: lowercase, matching `^[a-z0-9][a-z0-9._-]{1,63}$`.
- `kind` is one of `stt`, `router`, `knowledge`, `llm`, `perceive`, `action`, `input`, `tts`,
  `context`, `ui`, `bundle`.
- `runtime`: the schema allows `subprocess`, `wasm` and `native`, but the reference runner
  **only supports `subprocess`** today.
- `transport`: `stdio`, `connect` or `listen`, all implemented.
- `entrypoint`: argv for a subprocess.
- `config_schema`, `settings` and `models` are declared in the schema; plugin-declared model
  installation is **planned, not implemented**.

The runner itself is configured from a *runner* TOML with `[[plugin]]` entries
(`runner/config.example.toml`). The manifest is what a plugin package ships.

## Plugin kinds

| Kind | Role | Minimal methods |
|---|---|---|
| `router` | utterance + context → ordered steps (rules, candidate building, decision head) | `router.plan` |
| `llm` | completion and the constrained **choose** | `llm.complete`, `llm.choose` |
| `knowledge` | static catalog: apps, sites, niri actions, media keys | catalog methods |
| `stt` | audio → text, pull or stream | `stt.*` |
| `perceive` | screenshot, accessibility, OCR, browser tabs | `perception.*` |
| `action` | executors: niri, input, media, browser, terminal, launcher | `action.capabilities`, `action.invoke` |
| `input` | push-to-talk keys and injection (highest risk, mostly native) | `input.*` |
| `tts` | speech output | `tts.speak` |
| `context` | live desktop state | `context.snapshot` |
| `ui` | declarative render and events; config is owned by the runner | `ui.render` |
| `bundle` | one process serving several namespaces | any subset |

The real assistant, `utter_py`, is a `bundle`: it serves `router.plan`, `action.*` and
`context.snapshot`, and declares perception capabilities.

## Capability registry

`protocol/capabilities.json` is the **single source of truth** for capability strings. Entries
are versioned `name@N`, for example `router.plan@1`, `audio.pcm_f32le@1` or
`experimental/<Name>@N`.

- **Unknown capability**: a warning. Like LSP, ignore what you do not understand.
- **Missing `requires`**: an error, fail closed, `-32005`. "Missing" is computed against the
  runner's own set, the `provides` of plugins already handshaken, and the plugin's own
  `provides`.
- `experimental/` is a collision-free extension namespace with no compatibility promise.
- The runner's built-in capabilities are `host.audio.ringbuffer@1`, `host.fd.pass@1` and
  `fs.tmp@1`.

## Method namespaces

Namespaces are `router.*`, `llm.*`, `stt.*`, `perception.*`, `action.*`, `input.*`, `tts.*`,
`context.*`, `ui.*`, plus `plugin.describe`, `plugin.health` and `protocol.hello`. Core
payload shapes:

| Method | Params | Result |
|---|---|---|
| `router.plan` | `{ utterance, context? }` | `{ steps:[{op,args,provenance,confirm}] }` |
| `llm.choose` | `{ utterance, context, candidates }` | `{ choice_id, probability, distribution }` |
| `llm.complete` | `{ prompt, ... }` | `{ text }` |
| `context.snapshot` | `{ sources? }` | a `Context` |
| `action.capabilities` | `{}` | `{ ops:[{op,side_effect,needs_confirm}] }` |
| `action.invoke` | `{ op, args, provenance }` | an `ActionResult` |
| `stt.*` | audio in; `stt.partial` and `stt.final` out | text |
| `tts.speak` | `{ text }` | a `tts.audio` stream |

**Actions are strings plus JSON Schema**, never a closed enum. The policy registry only
special-cases the ops it enforces (`ensure_url`, `open_url`, `terminal`, `input`, `niri`,
`launch_app`); a plugin advertises its real ops via `action.capabilities`.

### Host callbacks

`host.context`, `host.perceive`, `host.action`, `host.confirm` and `host.emit` are the specified
plugin-to-runner callback surface. Current status: **only `host.confirm` is wired**, and it is
delivered as a runner-to-client request when a client connection is present. Do not rely on the
others yet.

## Streams and flow control

`stream.subscribe { method, params?, mode? }` returns `{ stream_id, mode }`; then
`stream.ack { stream_id, seq }` and `stream.stop { stream_id }`. Notifications are
`<method> { stream_id, seq, data }`.

- **lossy** (the default, for audio frames, `llm.delta`, `tts.audio`): a bounded queue with
  **drop-oldest**; `seq` lets the client detect gaps. Default queue 256, configurable with the
  runner's `[runner] lossy_queue`.
- **reliable** (`*.final`, control): a credit window; the server **pauses** when credits run out
  and resumes on `stream.ack`. Default window 64 (`[runner] credit_window`).

`stream.stop` is idempotent and frees buffers. The runner's delivery never blocks the plugin read
loop; it only enqueues, drops or holds.

## Data plane: handles and `fd.pass`

Bulk data is a **capability, not a path**: `handle://<sha256>`. The runner's store is
content-addressed, plugin-scoped, garbage-collected by TTL and refcount, and **can never resolve
to an arbitrary filesystem path**.

- `handle.create { data_b64 | data | size, scope? }` returns `{ handle, sha256, size }`.
- `handle.fetch { handle, scope? }` returns the data inline when it is 64 KiB or smaller, else
  error `-32007`.
- `handle.stat { handle, scope? }` returns metadata.
- `fd.pass { kind, meta }` passes a file descriptor over `SCM_RIGHTS`, **socket transport
  only**. `kind="handle"` sends a read fd for a stored blob; `kind="memfd"` or `"memfd.ring"`
  sends a memfd. Known gap: `memfd.ring` is currently a plain memfd, not a true ring buffer.

## Permissions and trust

Read [Trust and safety](/guides/trust-and-safety/) before shipping side effects. In short:

- **Untrusted content selects, never authors.** Screen-provenance arguments are rejected with
  `-32006` before your plugin is called.
- **The runner enforces policy** and confirmation is argument-bearing. Your `needs_confirm` is
  only a hint.
- **`action.terminal` and `action.input` are off by default**, and still confirmation-required
  when enabled through `[policy] enabled_ops`.
- **`open_url` and `ensure_url` have a scheme allow-list** of `http`, `https` and `mailto`.
- **The socket is default-deny**: an allow-list by binary via `SO_PEERCRED`, or a token via
  `runner.auth`.
- **Sandboxing**: with `[security] enforce = true`, plugins spawn under
  `systemd-run --user --scope` or `bwrap`, and `runner.validate_plugin` reports each permission
  as `enforced` or `advisory`.

## Lifecycle

- Plugin instances are `(plugin_id, epoch)`; restart increments the epoch and stale-epoch
  replies are dropped.
- Graceful drain: stdin EOF, then terminate, then kill. A stdio plugin should exit on EOF.
- A crashed plugin is respawned with a new epoch; in-flight requests error cleanly.

## Compatibility

| Axis | Where | Meaning |
|---|---|---|
| **protocol** | manifest `protocol` | wire framing and envelope (`major.minor`); the reference runner accepts exactly `1.0` |
| **abi** | manifest `abi` | runner-to-plugin call semantics (integer) |
| **capability** | `protocol/capabilities.json` | vocabulary entries `name@N` |
| **plugin** | manifest `version` | the plugin's own semver, independent of the rest |

- Any protocol or abi mismatch, including minor drift, is refused with `-32004`; the reference
  runner accepts exactly protocol `1.0` / abi `1`.
- Unknown capability: warning. Missing `requires`: `-32005`, fail closed.
- Adding a capability is a minor protocol bump. Renaming or removing one is a major bump with a
  `deprecated: {since, replacement}` entry kept for N-2. Removal is only allowed two protocol
  minors after `since`, and `doctor` surfaces deprecation warnings and drift between a plugin's
  declared axes and the install lockfile.

## Error codes you will meet

| Code | Meaning |
|---|---|
| `-32003` | op disabled by policy (for example `terminal` with `user` provenance before opt-in) |
| `-32004` | incompatible protocol or abi version |
| `-32005` | a required capability is missing (fail closed) |
| `-32006` | arguments authored from untrusted (`screen`) provenance |
| `-32007` | handle too large to return inline; use `fd.pass` |
