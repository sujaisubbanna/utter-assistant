# utter plugin protocol — v0.1 (M0 draft; framing + handshake frozen)

Goal: freeze **framing + handshake** only. Method sets accrete against real consumers.

## 1. Transport & framing
- **JSON-RPC 2.0**, one message per frame.
- Framing: `Content-Length: <bytes>\r\n\r\n<utf8 json>` (LSP base protocol).
- Two transports:
  - **stdio** — runner spawns the plugin; stdin/stdout carry frames. **No fd passing.**
  - **socket** — unix socket at `$XDG_RUNTIME_DIR/utter/plugins/<id>.sock` (plugin connects
    or listens, declared by manifest `transport`). May use fd passing via an explicit
    `fd.pass` control frame over a `socketpair`; never `SCM_RIGHTS` over stdio pipes.
- Every request carries a client id and optional `params.timeout_ms`; the runner enforces a
  hard max. **`$/cancel {id}`** is best-effort and cascades runner→plugin→downstream; it may
  arrive after side effects. `stream.stop`/cancel are **idempotent**.

## 2. Version axes (all three matter)
- `protocol` — wire/JSON-RPC framing (this doc): `1.0`.
- `abi` — runner↔plugin call semantics: integer.
- `capability` — vocabulary entries are versioned: `name@N` (e.g. `audio.pcm_f32le@1`).
`protocol.hello` returns the **negotiated** version (not merely checked).

## 3. Handshake (frozen)
1. Runner → plugin: `protocol.hello { protocol, abi, runner, epoch }`
2. Plugin → runner result: `{ protocol, abi, plugin:{name,version,kind}, transport,
   provides:[...], requires:[...], permissions:[...] }`
3. Runner → `plugin.describe {}` → `{ methods:[...], streams:[...] }`
4. Runner → `plugin.health {}` → `{ status:"ok"|"degraded", detail }`
5. Runner computes `provides ∩ requires`, validates permissions, records `epoch`.
A plugin instance is identified by `(plugin_id, epoch)`; responses from a stale epoch are
rejected. Restart = new epoch.

## 4. Methods (initial, minimal)
Namespaces: `router.*`, `llm.*`, `stt.*`, `perception.*`, `action.*`, `input.*`, `tts.*`,
`context.*`, `ui.*`; plus `plugin.describe`, `plugin.health`, `protocol.hello`.

- `router.plan { utterance, context? }` → `{ steps:[{op,args,provenance,confirm}] }`
- `llm.choose { utterance, context, candidates }` → `{ choice_id, probability, distribution }`
- `context.snapshot { sources? }` → `Context`
- `action.capabilities {}` → `{ ops:[{op,side_effect,needs_confirm}] }`
- `action.invoke { op, args, provenance }` → `ActionResult`
- `host.*` (plugin → runner callbacks): `host.context`, `host.perceive`, `host.action`,
  `host.confirm`, `host.emit`.

**Actions are strings + JSON Schema**, never a closed enum.

## 5. Streams & flow control
- `stream.subscribe { method, params }` → `{ stream_id }`; server notifies
  `<ns>.delta|partial|audio { stream_id, seq, data }`; `stream.stop { stream_id }`.
- **lossy** streams (audio frames, `llm.delta`, `tts.audio`): bounded queue, drop-oldest,
  never block the loop; `seq` lets the client detect gaps.
- **reliable** streams (`*.final`, control): credit/ack based.

## 6. Data plane — handles, not paths
- Bulk data (audio/images) as **capabilities**: `handle://<sha256>`, plugin-scoped,
  unguessable, TTL/refcount GC, created via `O_TMPFILE`+`linkat` or temp+rename.
- `handle.stat`, `handle.fetch` (runner-mediated). A handle can **never** be resolved to an
  arbitrary filesystem path. Continuous audio prefers a `memfd` ring-buffer fd.

## 7. Error taxonomy
`-32000` plugin error · `-32001` timeout · `-32002` cancelled · `-32003` permission denied ·
`-32004` incompatible version · `-32005` degraded/unavailable · `-32006` untrusted-argument
rejected by policy.

## 8. Capability registry
`protocol/capabilities.json` is the single source of truth (owner + versioned). Unknown
capabilities are **warnings** (LSP rule); a missing `requires` is an **error** (fail closed).
`experimental/` prefix is a collision-free extension namespace.

## 9. Compatibility policy
Runner supports protocol **N-2**. Deprecations are announced in the registry; `doctor`
reports drift against the install lockfile. Config schema changes ship a migration path.

---

# M1 additions (freeze these before implementing)

## 10. Client API (over `runner.sock`)
- `stream.subscribe { method, params?, mode? }` → `{ stream_id, mode: "lossy"|"reliable" }`
- `stream.ack { stream_id, seq }` → `{}` (reliable mode only; replenishes credit)
- `stream.stop { stream_id }` → `{}` (idempotent; frees buffers)
- `runner.invoke { plugin, method, params }` → result (runner-mediated plugin call; policy
  applies, side-effecting ops require `provenance`)
- `runner.validate_plugin { plugin }` →
  `{ ok, negotiated:{protocol,abi}, unknown_capabilities:[], missing_requires:[],
     permissions:[{name, enforced: bool}] }`
- `handle.fetch { handle }` → `{ size, sha256, data_b64 }` when size ≤ 64 KiB, else
  error `-32007` (use `fd.pass`)
- `fd.pass { kind, meta }` → `{}` — fds are carried as `SCM_RIGHTS` ancillaries over the
  **socket** transport (never stdio pipes)

## 11. Streams & flow control
- Notifications: `<method> { stream_id, seq, data }`.
- **lossy** (audio frames, `llm.delta`, `tts.audio`): server-side bounded queue (default 256
  frames), **drop-oldest**; the client detects gaps via `seq`.
- **reliable** (`*.final`, control): credit window (default 64). The server **pauses** when
  credits are exhausted; the client replenishes via `stream.ack`.
- `stream.stop` is idempotent and releases handle references created for the stream.

## 12. Plugin transports
- `stdio` (runner spawns) **or** `connect`/`listen` (unix socket at
  `$XDG_RUNTIME_DIR/utter/plugins/<id>.sock`).
- `fd.pass` is only available over socket transports.

## 13. Security (M1)
- **`[socket]` default-deny:** require `allow_binaries` (verified via `SO_PEERCRED` exe
  path) **or** a token; dev override `allow_same_uid = true`.
- **`[security] enforce = true`** spawns plugins under systemd-run/bubblewrap hardening
  where the host supports it: `NoNewPrivileges`, `RestrictAddressFamilies=AF_UNIX`, a
  private `/tmp`, a default-deny device cgroup (`DevicePolicy=closed` + `DeviceAllow` for
  `/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/random`, `/dev/tty`, plus `/dev/snd`
  only when a plugin declares `microphone`), and read-only system/interpreter paths
  (`ReadOnlyPaths`; declared `read_paths`/`write_paths` are applied as
  `ReadOnlyPaths`/`ReadWritePaths`). `runner.validate_plugin` reports each permission as
  `enforced` or `advisory`.
- **Known gap (systemd, `--user --scope`):** on systemd releases that reject exec-context
  properties on transient *scopes* (e.g. systemd 262), the runner falls back to `bwrap`,
  which applies the equivalent isolation (`--unshare-all`, read-only root, `--tmpfs`
  `/tmp`+`/var/tmp`, read-only re-binds, `--dev-bind` only for declared devices). If
  neither wrapper runs, plugins spawn unhardened and every permission is **advisory**.
- `action.terminal` / `action.input` remain **off by default**; enabling is explicit and
  confirmation-required.

## 14. New error code
- `-32007` handle too large for inline fetch (use `fd.pass`).

