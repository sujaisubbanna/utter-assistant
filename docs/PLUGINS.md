# Writing a utter plugin

A **plugin** is any process that speaks the frozen JSON-RPC protocol and answers at
least the handshake. The **runner** owns policy, confirmation and the data plane; a
plugin is otherwise a plain program. This guide is grounded in the reference
implementations under `plugins/` and the frozen spec in `protocol/PROTOCOL.md`.

## Table of contents

1. [Contract: framing + handshake](#1-contract-framing--handshake)
2. [The manifest](#2-the-manifest)
3. [Capability registry](#3-capability-registry)
4. [Method namespaces by kind](#4-method-namespaces-by-kind)
5. [Streams & flow control](#5-streams--flow-control)
6. [Data plane: handles & `fd.pass`](#6-data-plane-handles--fdpass)
7. [Worked minimal plugin (Python)](#7-worked-minimal-plugin-python)
8. [Worked minimal plugin (Rust)](#8-worked-minimal-plugin-rust)
9. [Testing with the conformance suite](#9-testing-with-the-conformance-suite)
10. [Permissions & trust](#10-permissions--trust)
11. [Compatibility](#11-compatibility)

---

## 1. Contract: framing + handshake

The wire format and the handshake are **frozen** and live in
[`protocol/PROTOCOL.md`](../protocol/PROTOCOL.md). Do not change the envelope;
add methods instead.

- **JSON-RPC 2.0**, one message per frame.
- **Framing**: `Content-Length: <bytes>\r\n\r\n<utf8 json>` (LSP base protocol).
  See `runner/framing.py` for the reference implementation.
- **Transports** (`protocol/PROTOCOL.md` §1, §12):
  - `stdio` — the runner spawns the plugin; stdin/stdout carry frames. **No fd passing.**
  - `connect` / `listen` — a unix socket at
    `$XDG_RUNTIME_DIR/utter/plugins/<id>.sock` (`plugin_socket_path`, `runner/plugin.py`).
    `connect` = the runner listens, the plugin dials in; `listen` = the plugin
    listens, the runner connects.
- **`$/cancel {id}`** is best-effort and cascades; `stream.stop` / cancel are
  idempotent. Requests may carry `params.timeout_ms`; the runner enforces a hard
  max of 60000 ms (`HARD_MAX_TIMEOUT_MS`, `runner/host.py`).

### Handshake sequence (frozen)

From `_handshake` in `runner/plugin.py` and each fake's handler:

```text
runner → plugin   protocol.hello {protocol, abi, runner, epoch}
plugin → runner   {protocol, abi, plugin:{name,version,kind}, transport,
                   provides:[...], requires:[...], permissions:[...]}
runner → plugin   plugin.describe {}  → {methods:[...], streams:[...]}
runner → plugin   plugin.health {}    → {status:"ok"|"degraded", detail}
```

The runner then computes `provides ∩ requires`, validates capabilities, and records
an **epoch**. A plugin instance is `(plugin_id, epoch)`; responses from a stale
epoch are dropped (epoch check in `runner/rpc.py`), and a restart increments the epoch.

`protocol.hello` returns the **negotiated** version. The current values are
`protocol = "1.0"`, `abi = 1` (`PROTOCOL_VERSION` / `ABI`, `runner/plugin.py`). A mismatch fails with
`-32004` (`_handshake`, `runner/plugin.py`).

---

## 2. The manifest

The canonical on-disk form is `utter-plugin.toml`, validated by
[`protocol/plugin.schema.json`](../protocol/plugin.schema.json). A minimal, valid
manifest is `plugins/fake_rs/utter-plugin.toml`:

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

Required fields (`plugin.schema.json` `required`): `name`, `version`, `kind`,
`protocol`, `abi`, `runtime`, `transport`, `entrypoint`.

- `name` — plugin id, lowercase, `^[a-z0-9][a-z0-9._-]{1,63}$`.
- `kind` — one of `stt`, `router`, `knowledge`, `llm`, `perceive`, `action`,
  `input`, `tts`, `context`, `ui`, `bundle`.
- `runtime` — schema allows `subprocess | wasm | native`, but the reference runner
  **only supports `subprocess`** today (`runner/plugin.py`).
- `transport` — `stdio | connect | listen` (all three implemented).
- `entrypoint` — argv (array) for a subprocess, or a `.wasm` path.
- `permissions` — see [§10](#10-permissions--trust).
- `config_schema` / `settings` / `models` — declared in the schema. The model store itself is
  implemented (`assistant/models.py`, `assistant models pull`); what is **not implemented yet**
  is provisioning models *from a plugin manifest*.

> Note: `utter-plugin.toml` is the documented canonical form, but the runner
> itself is configured from a *runner* TOML (`[[plugin]]` entries) — see
> `runner/config.example.toml` and `config.m3.toml`. The manifest is what a plugin
> package ships.

---

## 3. Capability registry

[`protocol/capabilities.json`](../protocol/capabilities.json) is the **single source
of truth** for capability strings. Entries are versioned `name@N`, e.g.
`router.plan@1`, `audio.pcm_f32le@1`, or `experimental/<Name>@N`.

Rules (`validate_capabilities`, `runner/plugin.py`):

- **Unknown capability → warning** (LSP rule: ignore what you don't understand).
- **Missing `requires` → error, fail closed** (`-32005`,
  `validate_capabilities` in `runner/plugin.py`). Note `missing` is computed against the runner's own
  satisfiable set (`RUNNER_CAPS`, `runner/plugin.py`) plus the union of already-
  handshaken plugins' `provides` plus the plugin's own `provides`.
- `experimental/` is a collision-free extension namespace (no compatibility promise).

The runner's built-in capabilities are
`{"host.audio.ringbuffer@1", "host.fd.pass@1", "fs.tmp@1"}` (`RUNNER_CAPS`, `runner/plugin.py`).

---

## 4. Method namespaces by kind

Namespaces are `router.*`, `llm.*`, `stt.*`, `perception.*`, `action.*`,
`input.*`, `tts.*`, `context.*`, `ui.*`, plus `plugin.describe`, `plugin.health`
and `protocol.hello` (`protocol/PROTOCOL.md` §4). Core payload shapes:

| Method | Params | Result |
|---|---|---|
| `router.plan` | `{ utterance, context? }` | `{ steps:[{op,args,provenance,confirm}] }` |
| `llm.choose` | `{ utterance, context, candidates }` | `{ choice_id, probability, distribution }` |
| `llm.complete` | `{ prompt, ... }` | `{ text }` |
| `context.snapshot` | `{ sources? }` | a `Context` |
| `action.capabilities` | `{}` | `{ ops:[{op,side_effect,needs_confirm}] }` |
| `action.invoke` | `{ op, args, provenance }` | an `ActionResult` |
| `stt.*` | audio in / `stt.partial`/`stt.final` out | text |
| `tts.speak` | `{ text }` | `tts.audio` stream |

Minimal methods per kind:

| Kind | Role | Minimal methods |
|---|---|---|
| `router` | utterance + context → ordered steps | `router.plan` |
| `llm` | completion + constrained decision | `llm.complete`, `llm.choose` |
| `knowledge` | static catalog (apps/sites/niri/media) | catalog methods |
| `stt` | audio → text | `stt.*` (pull or push) |
| `perceive` | screenshot / a11y / OCR / tabs | `perception.*` |
| `action` | executors (niri, input, media, browser, terminal) | `action.capabilities`, `action.invoke` |
| `input` | PTT keys / injection (highest risk) | `input.*` |
| `tts` | speech output | `tts.speak` |
| `context` | live desktop state | `context.snapshot` |
| `ui` | declarative render + events (config owned by the runner) | `ui.render` |
| `bundle` | one process serving several namespaces | any subset |

**Actions are strings + JSON Schema**, never a closed enum
(`protocol/PROTOCOL.md` §4). The registry only special-cases the ops it enforces
(`runner/policy.py`: `ensure_url`, `open_url`, `terminal`, `input`, `niri`,
`launch_app`). A plugin advertises its real ops via `action.capabilities`.

`utter_py` is a realistic `bundle`: it serves `router.plan`, `action.*`,
`context.snapshot`, and declares perception capabilities
(`PROVIDES` / `OPS`, `plugins/utter_py/plugin.py`).

### Host callbacks

`host.context`, `host.perceive`, `host.action`, `host.confirm`, `host.emit` are the
*specified* plugin→runner callback surface (`protocol/PROTOCOL.md` §4). Current
status: **only `host.confirm` is wired** — and as a **runner→client** request when a
client connection is present (`_ask_confirm`, `runner/host.py`). The other callbacks are not
implemented yet; don't rely on them.

---

## 5. Streams & flow control

Methods: `stream.subscribe { method, params?, mode? }` → `{ stream_id, mode }`,
`stream.ack { stream_id, seq }`, `stream.stop { stream_id }`
(`protocol/PROTOCOL.md` §5, §11; relayed by `runner/streams.py`).

Notifications are `<method> { stream_id, seq, data }`.

- **lossy** (default; audio frames, `llm.delta`, `tts.audio`): a bounded queue,
  **drop-oldest**; `seq` lets the client detect gaps. Default queue 256
  (`DEFAULT_LOSSY_QUEUE`, `runner/streams.py`, overridable via runner `[runner] lossy_queue`).
- **reliable** (`*.final`, control): credit window; the server **pauses** when
  credits run out and resumes on `stream.ack`. Default window 64
  (`DEFAULT_CREDIT_WINDOW`, `runner/streams.py`; runner `[runner] credit_window`).

`stream.stop` is **idempotent** and frees buffers (`stop`, `runner/streams.py`).
The runner's `deliver()` never blocks the plugin read loop — it only enqueues / drops
/ holds synchronously (`deliver`, `runner/streams.py`).

A plugin implements `stream.subscribe` / `stream.stop` (and `stream.ack` for
reliable mode). See the emitter in `plugins/fake_py/plugin.py` for a working
example.

---

## 6. Data plane: handles & `fd.pass`

Bulk data is a **capability, not a path**: `handle://<sha256>`
(`HANDLE_RE`, `runner/handles.py`). The runner's store is content-addressed, plugin-scoped,
TTL/refcount-GC'd, and **can never resolve to an arbitrary filesystem path**
(`runner/handles.py`).

Client/runner methods (`HandlesApiMixin`, `runner/handles_api.py`):

- `handle.create { data_b64 | data | size, scope? }` → `{ handle, sha256, size }`
- `handle.fetch { handle, scope? }` → `{ size, sha256, data_b64 }` when
  `size ≤ 64 KiB` (`INLINE_MAX_BYTES`, `runner/handles.py`), else error **`-32007`**
- `handle.stat { handle, scope? }` → metadata
- `fd.pass { kind, meta }` → an `SCM_RIGHTS` fd, **socket transport only**
  (`fd_pass`, `runner/handles_api.py`). `kind="handle"` sends a read fd for the stored blob;
  `kind="memfd"` / `"memfd.ring"` sends a memfd.

> Known gap: `memfd.ring` is currently a **plain memfd**, not a true wrap-around ring
> buffer (`tests/conformance/README.md:144-150`).

---

## 7. Worked minimal plugin (Python)

The tested reference is [`plugins/fake_py/plugin.py`](../plugins/fake_py/plugin.py)
(stdlib only). The condensed skeleton below shows the handshake and the three methods
the vertical slice needs. Copy the framing helpers from `fake_py` verbatim.

```python
#!/usr/bin/env python3
"""hello_py — minimal stdio plugin."""
import json, sys

PROTOCOL, ABI = "1.0", 1
PROVIDES = ["action.open_url@1", "context.live@1", "fs.tmp@1"]
REQUIRES = ["fs.tmp@1"]

def read_message(stream):
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        chunk = stream.read(1)
        if not chunk:
            return None
        header += chunk
    length = int(header.split(b"content-length:")[1].split(b"\r\n")[0])
    body = stream.read(length)
    return json.loads(body.decode("utf-8")) if body else None

def write_message(stream, obj):
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    stream.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stream.flush()

def handle(method, params):
    if method == "protocol.hello":
        return {"protocol": PROTOCOL, "abi": ABI,
                "plugin": {"name": "hello_py", "version": "0.1.0", "kind": "bundle"},
                "transport": "stdio",
                "provides": PROVIDES, "requires": REQUIRES, "permissions": ["network"]}
    if method == "plugin.describe":
        return {"methods": ["protocol.hello", "plugin.describe", "plugin.health",
                            "router.plan", "action.capabilities", "action.invoke",
                            "context.snapshot"], "streams": []}
    if method == "plugin.health":
        return {"status": "ok", "detail": "hello_py ready"}
    if method == "router.plan":
        # "open youtube" -> one fully-resolved step
        utt = str(params.get("utterance", "")).strip().lower()
        if utt in ("open youtube", "go to youtube"):
            return {"steps": [{"op": "ensure_url",
                               "args": {"url": "https://www.youtube.com"},
                               "provenance": "user"}]}
        return {"steps": []}
    if method == "action.capabilities":
        return {"ops": [{"op": "ensure_url", "side_effect": "open_url",
                         "needs_confirm": False}]}
    if method == "action.invoke":
        args = params.get("args") or {}
        return {"ok": True, "op": params.get("op"),
                "detail": f"opened {args.get('url', '')}"}
    if method == "context.snapshot":
        return {"focused": None, "windows": [], "clipboard": "", "timestamp": 0}
    raise ValueError(f"method not found: {method}")

def main():
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    while True:
        msg = read_message(stdin)
        if msg is None:
            return 0
        if not isinstance(msg, dict) or msg.get("id") is None:
            continue
        try:
            result = handle(str(msg.get("method") or ""), msg.get("params") or {})
            write_message(stdout, {"jsonrpc": "2.0", "id": msg["id"], "result": result})
        except Exception as exc:                       # noqa: BLE001
            write_message(stdout, {"jsonrpc": "2.0", "id": msg["id"],
                                   "error": {"code": -32000, "message": str(exc)}})

if __name__ == "__main__":
    raise SystemExit(main())
```

You do **not** need to parse `provenance` yourself for policy: the runner stamps and
enforces it. A `screen`-provenance request that authors a concrete arg is rejected
before your plugin is called (`_enforce_policy`, `runner/host.py`, and `runner/policy.py`).

Wire it into a runner config:

```toml
[[plugin]]
id = "hello"
kind = "bundle"
runtime = "subprocess"
transport = "stdio"
entrypoint = ["python", "plugins/hello_py/plugin.py"]
provides = ["action.open_url@1", "context.live@1", "fs.tmp@1"]
requires = ["fs.tmp@1"]
```

If `entrypoint` is a relative path it is resolved relative to the runner's CWD; the
runner always prepends the repo root to `PYTHONPATH` so plugins can `import utter`
(`runner/plugin.py`). Use `cwd` for a plugin that needs its own directory as
the working directory (`config.m3.toml` does this for `utter_py`).

Validate a config without starting the runner:

```bash
.venv-agent/bin/python -m runner --check-config runner/config.example.toml
```

Drive a plugin by hand with the independent client:

```bash
.venv-agent/bin/python tests/conformance/framing_client.py \
    .venv-agent/bin/python plugins/fake_py/plugin.py
```

---

## 8. Worked minimal plugin (Rust)

The tested reference is [`plugins/fake_rs/src/main.rs`](../plugins/fake_rs/src/main.rs).
It hand-rolls the `Content-Length` framing and uses `serde_json` only for parsing.
Build it with:

```bash
cargo build --release --manifest-path plugins/fake_rs/Cargo.toml
# -> plugins/fake_rs/target/release/fake_rs
```

Its handshake and action replies (`src/main.rs:86-135`):

```rust
"protocol.hello" => json!({
    "protocol": PROTOCOL, "abi": ABI,
    "plugin": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION, "kind": PLUGIN_KIND},
    "transport": "stdio",
    "provides": PROVIDES, "requires": REQUIRES, "permissions": PERMISSIONS,
}),
"plugin.describe" => json!({ "methods": [...], "streams": [] }),
"plugin.health"   => json!({"status": "ok", "detail": "fake_rs ready"}),
"action.capabilities" => json!({"ops": [
    {"op": "ensure_url", "side_effect": "open_url", "needs_confirm": false}
]}),
"action.invoke" => json!({"ok": true, "op": "ensure_url",
                          "detail": format!("opened {}", url)}),
```

Terminate on stdin EOF (the runner closes stdin to drain a stdio plugin —
`runner/plugin.py`).

---

## 9. Testing with the conformance suite

The repository includes a conformance suite that exercises the protocol against the
runner. Prerequisites: the repo venv (`.venv-agent/bin/python`) and a built Rust fake.

```bash
# build the Rust fake once
cargo build --release --manifest-path plugins/fake_rs/Cargo.toml

# run the suite
.venv-agent/bin/python tests/conformance/run.py
```

It generates `tests/conformance/generated/conformance.toml`, starts
`python -m runner --config <that file>` from the repo root, waits for
`$XDG_RUNTIME_DIR/utter/runner.sock`, and checks (summary in
`tests/conformance/README.md`):

- handshake and negotiation, `provides ∩ requires`, unknown-capability
  tolerated, missing-require rejected fail-closed, the cross-language Rust fake, the
  `runner.command "open youtube"` vertical slice, and policy (`terminal` with
  `screen` provenance → `-32006`; with `user` provenance → `-32003`).
- end-to-end lossy backpressure (drop-oldest + `seq` gaps, responsive
  sibling RPCs, idempotent `stream.stop`), reliable flow (pause at the credit
  window, resume on `stream.ack`), `runner.invoke` (including `-32006`),
  `runner.validate_plugin`, handles + `fd.pass` (`-32007`, fd round trip),
  socket default-deny, and memfd.
- Features the runner has not implemented are reported `NOT-YET-SUPPORTED` and are
  counted separately, never as failures.

Exit codes: `0` = all assertions passed (or only skips), `1` = a check failed,
`2` = blocked (runner absent / not ready). Flags: `--keep`, `--timeout 30`.

Run the repository's full verification with:

```bash
scripts/verify.sh
```

---

## 10. Permissions & trust

Read [`docs/TRUST.md`](TRUST.md) before shipping side effects. The essentials:

- **Untrusted content selects, never authors.** Screen/a11y/OCR/titles/clipboard
  are `screen` provenance; they may only choose among precomputed candidates. Any
  concrete arg derived from them is rejected with **`-32006`**
  (`runner/policy.py`).
- **The runner enforces policy**, and confirmation is **argument-bearing** (shows the
  concrete URL/command, then re-validates — TOCTOU). A plugin's `needs_confirm` is
  only an untrusted hint; `runner.command` honors a step's `confirm` flag and the
  op registry (`_run_step` / `_enforce_policy`, `runner/host.py`; `runner/policy.py`).
- **`action.terminal` and `action.input` are off by default.** Enabling is explicit
  and still confirmation-required (`runner/policy.py`; runner config
  `[policy] enabled_ops`).
- **`open_url`/`ensure_url` have a scheme allow-list** `http, https, mailto`
  (`runner/policy.py`).
- **Socket is default-deny**: allow-list by binary (`SO_PEERCRED` → `/proc/<pid>/exe`)
  or a token via `runner.auth`; `allow_same_uid = true` is a dev escape hatch
  (`_authorize_creds`, `runner/socket.py`).
- **Sandboxing**: with runner `[security] enforce = true`, plugins spawn under
  `systemd-run --user --scope` (preferred) or `bwrap`, and
  `runner.validate_plugin` reports each permission as `enforced` or `advisory`
  (`runner/security.py`, `docs/TRUST.md` §6). If a permission can't be enforced it is
  labeled **advisory** — never implied safe.

---

## 11. Compatibility

See [`docs/COMPATIBILITY.md`](COMPATIBILITY.md) for the full policy. The three
distinct axes:

| Axis | Where | Meaning |
|---|---|---|
| **protocol** | manifest `protocol` | wire/JSON-RPC framing (`major.minor`); runner supports **N-2** |
| **abi** | manifest `abi` | runner↔plugin call semantics (integer) |
| **capability** | `protocol/capabilities.json` | vocabulary entries `name@N` |

- Major protocol/abi mismatch → refuse with `-32004`.
- Minor drift → allow + warn.
- Unknown capability → warning; missing `requires` → `-32005` (fail closed).
- Adding a capability → minor protocol bump; renaming/removing → major bump with a
  `deprecated:{since,replacement}` entry kept for N-2.
- `experimental/` is the collision-free extension namespace (no compatibility
  promise).
