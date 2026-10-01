---
title: "Writing a plugin"
description: "A worked minimal plugin in Python and in Rust, wiring it into the runner, and testing it with the conformance suite."
---

This guide builds the smallest useful plugin: it answers the handshake, routes "open youtube" to
a single fully resolved step, and invokes it. The tested references are `plugins/fake_py/`
(Python, standard library only) and `plugins/fake_rs/` (Rust). Read the
[protocol summary](/plugins/) first if the terms are new.

## Python

Copy the framing helpers from `plugins/fake_py/plugin.py` verbatim; the skeleton below shows the
handshake and the three methods the vertical slice needs.

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

You do **not** need to check `provenance` yourself for policy: the runner stamps and enforces
it. A `screen`-provenance request that authors a concrete argument is rejected before your plugin
is called.

### Wire it into a runner config

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

A relative `entrypoint` is resolved against the runner's working directory, and the runner always
prepends the repository root to `PYTHONPATH` so plugins can `import utter`. Use `cwd` for a
plugin that needs its own directory as the working directory.

Validate a config without starting the runner:

```bash
python3 -m runner --check-config runner/config.example.toml
```

Drive a plugin by hand with the independent client:

```bash
python3 tests/conformance/framing_client.py python3 plugins/hello_py/plugin.py
```

## Rust

The tested reference is `plugins/fake_rs/src/main.rs`. It hand-rolls the `Content-Length`
framing and uses `serde_json` only for parsing.

```bash
cargo build --release --manifest-path plugins/fake_rs/Cargo.toml
# -> plugins/fake_rs/target/release/fake_rs
```

Its handshake and action replies:

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

Terminate on stdin EOF: the runner closes stdin to drain a stdio plugin.

The manifest for the Rust fake, `plugins/fake_rs/utter-plugin.toml`, is the minimal valid
example of a package manifest; see [the manifest](/plugins/#the-manifest).

## Streams

A plugin that produces audio, deltas or events implements `stream.subscribe` and `stream.stop`,
plus `stream.ack` for reliable mode. The emitter in `plugins/fake_py/plugin.py` is a working
example of both lossy (drop-oldest with `seq` gaps) and reliable (credit window) streams.

## Testing with the conformance suite

`tests/conformance/run.py` exercises the protocol against the runner from a separate client.
It needs a Python interpreter with the repo on its path and a built Rust fake.

```bash
# build the Rust fake once
cargo build --release --manifest-path plugins/fake_rs/Cargo.toml

# run the suite
python3 tests/conformance/run.py
```

It generates a runner config, starts `python -m runner --config <that file>` from the repository
root, waits for `$XDG_RUNTIME_DIR/utter/runner.sock`, and asserts:

- Handshake and negotiation, `provides ∩ requires`, unknown capability tolerated,
  missing requirement rejected fail-closed, the cross-language Rust fake, the
  `runner.command "open youtube"` vertical slice, and policy (`terminal` with `screen`
  provenance gives `-32006`; with `user` provenance it gives `-32003`).
- End-to-end lossy backpressure (drop-oldest, `seq` gaps, responsive sibling RPCs,
  idempotent `stream.stop`), reliable flow (pause at the credit window, resume on `stream.ack`),
  `runner.invoke` including `-32006`, `runner.validate_plugin`, handles and `fd.pass`
  (`-32007`, fd round trip), socket default-deny, and memfd.
- Features the runner has not implemented are reported `NOT-YET-SUPPORTED` and counted
  separately, never as failures.

Exit codes: `0` all assertions passed (or only skips), `1` a check failed, `2` blocked (runner
absent or not ready). Flags: `--keep`, `--timeout 30`.

Run the repository's full verification with:

```bash
scripts/verify.sh
```

## Checklist before you ship

- Answer `protocol.hello`, `plugin.describe` and `plugin.health`.
- Declare only the capabilities you really provide; declare everything you require.
- Advertise your real ops in `action.capabilities`.
- Never turn screen text into arguments. Let the runner's provenance policy do its job.
- Declare permissions honestly, and check what `doctor` reports as enforced versus advisory.
- Exit cleanly on stdin EOF.
- Run the conformance suite.
