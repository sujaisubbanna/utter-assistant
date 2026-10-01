---
title: "The assistant CLI"
description: "Reference for the assistant command: doctor, recommend, models, status and install-state."
---

`assistant` is the command-line companion to the runner. The installer puts a wrapper at
`$PREFIX/bin/assistant`; from a checkout the same thing is `python -m assistant`. Every command
takes `--json` for machine-readable output, which is what the settings app consumes.

## `doctor`

```bash
assistant doctor [--json] [--timeout SECONDS]
```

Checks the system and the runner:

- **deps**: which command-line tools and libraries are present (`wtype`, `ydotool`,
  `ydotoold`, `grim`, `wl-copy`, `pw-play`, systemd `--user`, `input` group membership,
  `uinput`, `webkit2gtk`, GTK).
- **plugins**: per plugin, the negotiated protocol and abi, `unknown_capabilities`,
  `missing_requires`, and `permissions` as `{name, enforced, advisory}`.
- **drift**: differences between what the install lockfile recorded and what is running, and
  any deprecation warnings.

The JSON shape is stable:

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

## `recommend`

```bash
assistant recommend [--json]
```

Looks at your GPUs (via `nvidia-smi`, falling back to `lspci`), VRAM and RAM, and suggests a
model per tier (speech recognition, decision head and planner, vision) with an estimated
footprint and the reason. It **never installs anything**. The rules are listed in
[Models](/guides/models/#recommended-models-per-machine).

## `models`

```bash
assistant models list [--json]
assistant models show <name> [--json]
assistant models pull <source> [--tag TAG] [--json]
assistant models rm <name> [--json]
assistant models prune [--json]
```

`<source>` is `hf:org/repo[:file]`, an `https://` URL, or a `file://` path (a bare local path
also works). `pull` streams newline-delimited JSON progress with `--json`, which the settings app
turns into a progress bar. Pulls are resumable and verified by SHA-256; `rm` removes a manifest
and any blob nothing else references; `prune` collects orphans and unfinished downloads. Ctrl-C
stops an in-flight download cleanly.

Store location: `$XDG_DATA_HOME/utter/models/`, or `UTTER_MODELS`.

## `status`

```bash
assistant status [--json] [--timeout SECONDS]
```

Connects to the runner socket and prints `runner.status`: each plugin's id, kind, epoch and
status. Exits `1` with a clear message if the socket is unavailable.

## `install-state`

```bash
assistant install-state record
assistant install-state show
```

Reads and writes `$XDG_STATE_HOME/utter/install.json`, the lockfile the installer uses to make
installs reversible and that `doctor` compares against the running system.

## Environment variables

| Variable | Effect |
|---|---|
| `UTTER_MODELS` | model store location |
| `UTTER_PYTHON` | interpreter the `assistant` wrapper uses |
| `UTTER_REPO` | repository root for the settings app and the wrapper |
| `UTTER_DRY_RUN` | the `utter_py` plugin defaults this to on; set `0` to touch the desktop |
| `UTTER_SOUNDS` | `0` disables the UI sounds |
| `UTTER_OSD` | `0` disables the on-screen display |
| `XDG_RUNTIME_DIR` | where the runner socket, plugin sockets and OSD state live |
# Utter command line

The `utter` executable drives desktop actions and speech. The separate `python -m assistant` command manages models, runner health, recommendations, and install state. See the [agent CLI reference](../../../../docs/CLI.md) for command details, JSON contract, and exit codes.

```sh
utter schema --json
utter assistant "open youtube" --dry-run --json
utter dictation "hello" --dry-run --json
```

JSON uses the stable `utter.cli/v1` envelope. `utter --text TEXT` remains supported for compatibility.
