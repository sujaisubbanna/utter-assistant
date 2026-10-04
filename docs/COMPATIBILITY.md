# Compatibility & deprecation policy

## 1. Version axes (all distinct)
| Axis | Where | Meaning |
|------|-------|---------|
| **protocol** | `protocol/PROTOCOL.md`, manifest `protocol` | wire/JSON-RPC framing + method envelope (`major.minor`) |
| **abi** | manifest `abi` | runner↔plugin call semantics (integer) |
| **capability** | `protocol/capabilities.json` | vocabulary entries, versioned `name@N` |
| **plugin** | manifest `version` | the plugin's own semver (independent) |

`protocol.hello` returns the **negotiated** protocol/abi; it is not merely checked.

## 2. Support policy
- The **reference runner accepts exactly protocol `1.0` and abi `1`** today; anything else is
  refused (`runner/plugin.py`). There is **no N-2 window implemented** yet.
- **Mismatch** → refuse with `-32004 incompatible version`.
- Capability checks: **unknown capability = warning** (LSP rule — ignore what you don't
  understand); **missing `requires` = error** (fail closed, `-32005`).
- Platform/arch mismatch → refuse at load.

## 3. Capability registry governance
- `protocol/capabilities.json` is the **single source of truth** (owner + versioned).
- **Adding** a capability → minor protocol bump; old runners warn, don't break.
- **Renaming/removing** a capability → **major** bump + deprecation entry, kept for N-2.
- **`experimental/` prefix** is a collision-free namespace for extension (owner-controlled,
  no compatibility promise).
- Every capability entry may carry `deprecated: {since, replacement}`.

## 4. Deprecation process
1. Mark the entry/capability `deprecated` in the registry with a `since` version + replacement.
2. Runner emits a deprecation **warning** (visible in `doctor`), keeps working.
3. Removal is only allowed after **two** protocol minors past `since`.
4. `doctor` reports drift between a plugin's declared axes and the lockfile.

## 5. Config schema migration — planned, not implemented
- Plugins may declare `config_schema` in their manifest (`protocol/plugin.schema.json`), but the
  reference runner **does not validate it or run migrations today**.
- Planned: strict validation (unknown/mistyped keys → warn, surfaced in the GUI) and recorded
  migrations so downgrades are at least detectable.

## 6. Install lockfile
- The installer records `{files, units, packages, version, protocol}` in
  `$XDG_STATE_HOME/utter/install.json` (`assistant/install_state.py`). It does not record a
  per-plugin `name → {version, protocol, abi, digest}` map or digests.
- `doctor` compares the recorded **protocol** and **version** against the running runner and
  reports drift (`assistant/doctor.py`); upgrades are explicit.

## 7. SDK versioning
- The protocol, manifest schema and capability registry are the compatibility contract for
  plugin SDKs in any language. An SDK pins the **protocol major** it targets.
- Breaking SDK changes follow the same N-2 rule as the protocol.

## 8. Doctor output (stable fields)
```json
{
  "ok": true,
  "runner": {"protocol": "1.0", "abi": 1, "version": "0.4.0"},
  "plugins": [
    {"id": "...", "kind": "...", "epoch": 0, "status": "ok",
     "negotiated": {"protocol": "1.0", "abi": 1},
     "unknown_capabilities": [], "missing_requires": [],
     "permissions": [{"name": "microphone", "enforced": true, "advisory": false}],
     "deprecations": []}
  ],
  "drift": []
}
```
