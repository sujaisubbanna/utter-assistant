# utter M0/M1 conformance suite

An **independent** conformance suite for the utter plugin protocol
(`protocol/PROTOCOL.md`). The client-side `Content-Length` framing is
implemented from the spec in `framing_client.py` — it does **not** import the
runner's framing code. If the runner and this client agree on the wire, the
wire format is real.

M1 features that the runner has not implemented yet are reported as
`NOT-YET-SUPPORTED` (counted separately, never as failures), so the suite runs
against an M0 runner while the M1 lane lands.

## Layout

```
tests/conformance/
  framing_client.py   independent Content-Length framing + JSON-RPC 2.0 client
                      (fd.pass/SCM_RIGHTS, stream helpers, runner.invoke, ...)
  run.py              the conformance suite (M0 + M1)
  report.json         machine-readable output of the measurement spike
  generated/          generated runner configs + logs (gitignored)
plugins/fake_py/      deterministic fake plugin (Python, stdlib only)
plugins/fake_rs/      minimal fake plugin (Rust, serde_json)
scripts/m0_spike.py   measurement spike (latency, backpressure, cancel, ...)
```

## Prerequisites

- Python 3.12+ (use the repo venv: `.venv-agent/bin/python`)
- Rust toolchain (`cargo`) for the Rust fake
- The runner (`runner/__main__.py`) — owned by another lane. If it is absent,
  `run.py` reports exactly which step blocked and exits `2`.

## Build the Rust fake

```bash
cargo build --release --manifest-path plugins/fake_rs/Cargo.toml
# -> plugins/fake_rs/target/release/fake_rs
```

## Run the conformance suite

```bash
.venv-agent/bin/python tests/conformance/run.py
```

It generates `tests/conformance/generated/conformance.toml`, starts
`python -m runner --config <that file>` from the repo root, waits for
`$XDG_RUNTIME_DIR/utter/runner.sock`, and asserts:

**M0**
- **handshake / negotiation** — both fakes handshaken, negotiated protocol,
  `provides ∩ requires`, unknown-capability tolerated, missing-require rejected
  (fail closed);
- **vertical slice** — `runner.command "open youtube"` (user provenance) →
  router fake plan → action fake invoked → `results[0].ok == true`;
- **policy** — `terminal` with `provenance:"screen"` rejected `-32006`; with
  `provenance:"user"` denied by policy `-32003` (terminal is off by default);
- **cross-language** — the Rust fake is handshaken and its capability recorded.

**M1**
- **end-to-end backpressure** — client `stream.subscribe` (lossy) through the
  runner; a deliberately slow consumer observes drop-oldest `seq` gaps while
  `runner.status` stays responsive; `stream.stop` is idempotent;
- **reliable flow control** — `stream.subscribe` (reliable) pauses at the credit
  window and resumes after `stream.ack`;
- **`runner.invoke`** — cross-language `fake_rs` `action.invoke` and `fake_py`
  `router.plan` through the runner; screen-authored `terminal` args rejected
  `-32006`;
- **`runner.validate_plugin`** — `unknown_capabilities`, `missing_requires`, and
  per-permission `enforced|advisory`;
- **handles + fd.pass** — end-to-end: `handle.create` → `handle.fetch` inline
  (sha256 + size match); a 128 KiB handle → `-32007`; `fd.pass kind="handle"`
  returns `{}` with exactly one fd whose content matches; `fd.pass kind="memfd"`
  returns its geometry metadata with one fd; plus endpoint probes (unknown handle
  rejected) and an independent `SCM_RIGHTS` socketpair round trip;
- **socket default-deny** — an unlisted client is rejected; an allow-listed
  client is accepted; token auth requires `runner.auth`;
- **memfd ring buffer** — `memfd.ring` creation + an `SCM_RIGHTS` fd round trip
  (ring wrap-around semantics are not-yet-supported: the runner's `memfd.ring`
  is a plain memfd, not a true ring buffer).

Exit code `0` = all assertions passed (or only not-yet-supported skips), `1` = a
check failed, `2` = blocked (runner absent / not ready).

Useful flags: `--keep` (leave the runner running), `--timeout 30`.

## Run the measurement spike

```bash
.venv-agent/bin/python scripts/m0_spike.py
```

Writes `tests/conformance/report.json` and prints a human summary. It measures:

1. **RPC round-trip latency** — N=200 `runner.status` calls → p50/p95/p99/max.
2. **backpressure** — a lossy stream from `fake_py` emits faster than a
   deliberately slow consumer; asserts drop-oldest / observable `seq` gaps and
   that other RPCs stay responsive.
3. **cancel-during-invoke** — a long `action.invoke` then `$/cancel`; asserts
   idempotent cancel and a `-32002` cancelled report.
4. **handle transfer** — create a blob, receive `handle://<sha256>`,
   `handle.fetch` it and verify the content hash matches; exercises `fd.pass`.
5. **crash/restart with in-flight** — kill the fake mid-request; asserts the
   runner respawns it with a **new epoch**, the in-flight request errors
   cleanly, and a subsequent request works.
6. **end-to-end backpressure** — lossy stream through the runner (gaps +
   responsiveness + idempotent stop).
7. **reliable flow** — pause at the credit window, resume after `stream.ack`.
8. **`runner.invoke`** — cross-language action + router plan + provenance.
9. **`runner.validate_plugin`** — negotiation, capabilities, permissions.
10. **handles + fd.pass** — end-to-end `handle.create` → inline fetch (sha256),
    >64 KiB → `-32007`, `fd.pass kind="handle"`/`kind="memfd"` fd round trip,
    plus endpoint probes and an `SCM_RIGHTS` socketpair round trip.
11. **socket default-deny** — unlisted rejected, allow-listed accepted.

## Manual handshake (no runner)

Drive a fake directly with the independent client:

```bash
.venv-agent/bin/python tests/conformance/framing_client.py \
    .venv-agent/bin/python plugins/fake_py/plugin.py
```

Or the Rust fake:

```bash
.venv-agent/bin/python tests/conformance/framing_client.py \
    plugins/fake_rs/target/release/fake_rs
```

## Determinism contract

`fake_py` is deterministic and asserted by the suite:

- `router.plan("open youtube")` →
  `{steps:[{op:"ensure_url", args:{url:"https://www.youtube.com"}, provenance:"user"}]}`
- `action.invoke("ensure_url", …)` → `ok`
- `action.invoke("terminal", …)` → `needs_confirm`

Both fakes terminate on stdin EOF.

## Known runner gaps (reported as NOT-YET-SUPPORTED)

- **`memfd.ring` is a plain memfd, not a true ring buffer.** The runner's
  `fd.pass kind="memfd.ring"` returns a flat memfd, so ring wrap-around /
  read-write cursor semantics cannot be tested. The suite exercises the memfd
  creation + `SCM_RIGHTS` fd round trip and records the ring semantics as
  not-yet-supported.

All other M1 client-facing pieces (`handle.create`, `handle.fetch` inline +
`-32007`, `fd.pass kind="handle"`/`"memfd"`, `runner.invoke`,
`runner.validate_plugin`, streams, socket default-deny) are now exercised
end-to-end through the runner.
