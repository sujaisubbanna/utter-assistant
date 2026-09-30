# utter widget for Noctalia (optional)

An **optional** Noctalia (v5) plugin for the utter assistant. It is *not* required to
use utter, and *not* installed by default — install it only if you run **Noctalia**
as your bar/shell.

Self-contained package: everything it needs is in this directory.

## What it provides
- **Bar widget** — utter status (idle / working / attention / error) with a tooltip;
  left-click opens the settings GUI (`utter-gui`), right-click refreshes.
- **Attention panel** — a persistent overlay panel (`layer = "overlay"`) shown when the
  runner is unreachable or a plugin reports a problem; closes on recovery.
- **Assistant OSD** — appears while the assistant push-to-talk key is held: a live level
  meter + best-effort in-progress transcript, then **green** (activated) / **red** (not),
  auto-dismissed. Reads `$XDG_RUNTIME_DIR/utter/osd.json`.

## Install
```bash
widgets/noctalia/install.sh            # copy + lint
widgets/noctalia/install.sh --yes      # + enable the plugin and add the bar widget
widgets/noctalia/install.sh --link     # symlink instead of copy (repo must stay put)
```
Then `noctalia msg config-reload` (or restart Noctalia). If Noctalia was already running
beforehand, the script lints and enables it for you.

```bash
# via the main installer (optional component)
install.sh --with-noctalia
```

## Uninstall
```bash
rm -rf "${NOCTALIA_PLUGINS_DIR:-$HOME/.local/share/noctalia/plugins}/utter"
noctalia msg config-reload
```

## Notes / gotchas
- Noctalia treats **every sibling directory** in the plugins dir as an overriding copy of a
  plugin. The installer never leaves a `*.bak*` sibling; previous installs are moved to
  `~/.local/state/noctalia/plugin-backups/`.
- The poller shells out to the repo's `assistant` CLI (interpreter = the `python_cmd`
  plugin setting → repo `.venv-agent/bin/python` → `.venv/bin/python` → `python3`).
- Requires Noctalia v5 with `plugin_api = 30` (persistent overlay panels).
