# example_quicknote

A small, real demonstration plugin for utter: a local **quick capture / voice
inbox**. It appends one timestamped line to a dated markdown file — offline, no
network, stdlib only.

## What it demonstrates

- A plugin is just a process speaking the frozen JSON-RPC protocol, nothing more.
- `action.capabilities` advertises the plugin's real ops (string + JSON-Schema-ish
  shape), not a closed enum.
- `action.invoke` performs one `local_write` side effect and returns
  `{ok, path, line}`.
- Errors use the standard JSON-RPC error envelope (`-32602` for bad args,
  `-32601` for an unknown method).

It is deliberately boring about trust: the plugin reads **only** its own
`args.text` and `$XDG_DATA_HOME`. It never reads the screen, clipboard or
filesystem, so it cannot author an argument from untrusted content. **Plugins
extend capability, not the trust model** — the runner still owns policy and
confirmation (`docs/TRUST.md`).

## The op

| field | value |
|---|---|
| op | `action.quicknote.append` |
| args | `{ "text": "..." }` (required, 1–2000 chars) |
| side_effect | `local_write` |
| needs_confirm | `false` |
| result | `{ok: true, path, line}` |

## Where notes go

Default inbox directory:

```
$XDG_DATA_HOME/utter/quicknote     # fallback: ~/.local/share/utter/quicknote
```

Each capture is appended as `- [YYYY-MM-DDTHH:MM] <text>` to
`<inbox>/<YYYY-MM>.md`, e.g. `~/.local/share/utter/quicknote/2026-10.md`. To
redirect it (for a test or a different vault), set `XDG_DATA_HOME`.

## Run it by hand

```bash
# handshake only
.venv-agent/bin/python tests/conformance/framing_client.py \
    .venv-agent/bin/python plugins/example_quicknote/plugin.py
```

Full round trip with the independent client (spawns the plugin, calls
`action.invoke`, prints the result):

```bash
.venv-agent/bin/python - <<'PY'
import json, sys
sys.path.insert(0, "tests/conformance")
from framing_client import FramingClient
c = FramingClient.open_plugin([sys.executable, "plugins/example_quicknote/plugin.py"])
print(json.dumps(c.request("protocol.hello", {"protocol": "1.0", "abi": 1}), indent=2))
print(json.dumps(c.request("action.capabilities", {}), indent=2))
print(json.dumps(c.request("action.invoke", {
    "op": "action.quicknote.append", "args": {"text": "demo note"}}), indent=2))
c.close()
PY
```

## Run it via the runner

Use the bundled config:

```bash
.venv-agent/bin/python -m runner --config plugins/example_quicknote/runner-config.example.toml
```

```toml
[[plugin]]
id = "example_quicknote"
kind = "action"
runtime = "subprocess"
transport = "stdio"
entrypoint = ["python", "plugins/example_quicknote/plugin.py"]
provides = ["action.quicknote@1", "experimental/example_quicknote@1"]
requires = []
permissions = ["filesystem.write"]
```

Validate the config without starting anything:

```bash
.venv-agent/bin/python -m runner --check-config \
    plugins/example_quicknote/runner-config.example.toml
```

## Tests

```bash
.venv-agent/bin/python tests/plugins/test_quicknote.py
```

The test drives the plugin over stdin/stdout with the independent conformance
client and points `XDG_DATA_HOME` at a temp dir, so it never touches your real
inbox.
