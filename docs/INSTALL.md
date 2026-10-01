# Install & model store

Target: Linux on Wayland — **niri** and **KDE Plasma (KWin)** are first-class, other compositors
get partial support (dictation, typing, launching; no window actions). **macOS is experimental**
(see [`MACOS.md`](MACOS.md)); Windows is not supported.

## 1. Installer

```bash
install/install.sh --dry-run     # default: print exactly what it would do
install/install.sh --yes         # actually install deps + enable the runner unit
install/install.sh --yes --no-deps   # skip distro packages, only wire the service
```

What it does:
1. Detects the distro from `/etc/os-release` (`ID`/`ID_LIKE`) → **pacman / apt / dnf / zypper**
   (falls back to `command -v`).
2. Installs the system dependencies (name-mapped per distro): `wtype`, `ydotool` (+`ydotoold`),
   `grim`, `wl-clipboard`, `pipewire`, `gtk4`, `libadwaita` (Tauri GUI), optional `keyd`.
3. Checks the `input` group and `/dev/uinput`; **prints** the `usermod -aG input` + udev + re-login
   steps (it never silently changes groups).
4. Installs and (with `--yes`) enables the **user** service `utter-runner.service`, bound to
   the graphical session via the `scripts/utter-wayland-ready.sh` wrapper.
5. Records what it did in `$XDG_STATE_HOME/utter/install.json` (reversible).
6. Runs `python -m assistant doctor --json` (or `recommend --json`) to verify.

Uninstall:
```bash
install/uninstall.sh --dry-run
install/uninstall.sh --yes            # stop/disable units, remove recorded files
install/uninstall.sh --yes --purge    # also remove models + config
```
Package removals are **printed**, never performed automatically.

## 2. Services (systemd user)

| Unit | Purpose |
|---|---|
| `utter-runner` | the modular runner (plugin supervisor) — installed by this installer |
| `utter-bridge` | legacy: vocalinux + voice→action (if you use the Python assistant today) |
| `utter-vision` | vLLM UI-TARS grounding server (`:8000`) |
| `utter-planner` | vLLM planner (`:8001`) |
| `utter-audio-defaults` | keeps TV output / RNNoise input pinned |

The runner unit uses `scripts/utter-wayland-ready.sh`, which discovers `WAYLAND_DISPLAY`,
`DBUS_SESSION_BUS_ADDRESS` and `NIRI_SOCKET` before exec'ing the runner — user services do not
inherit the session environment automatically.

## 3. `assistant` CLI

```bash
python -m assistant doctor [--json]                    # deps + plugin negotiation + drift
python -m assistant recommend [--json]                 # hardware-aware profile suggestions
python -m assistant models list|show <n>|pull <src>|rm <n>|prune [--json]
python -m assistant status [--json]                    # runner.status passthrough
python -m assistant install-state record|show
```

`doctor --json` includes a `deps` section (which CLI tools and libraries are present) alongside
the per-plugin `negotiated`, `unknown_capabilities`, `missing_requires`, and
`permissions:[{name,enforced,advisory}]` from the protocol (see `docs/COMPATIBILITY.md`).

## 4. Model store

Layout (Ollama-style, XDG):
```
$XDG_DATA_HOME/utter/models/      # override with UTTER_MODELS
  manifests/<host>/<ns>/<name>/<tag>.json
  blobs/sha256-<hex>
```
- Sources: `hf:org/repo[:file]` → resolved to `https://huggingface.co/org/repo/resolve/main/file`;
  bare `https://…`; local `file://`.
- **Resumable**: partial file + `curl -C -` (or urllib `Range`), retry/backoff, sha256 verify,
  atomic rename, pull lock, disk-space preflight.
- `rm` drops the manifest and any now-unreferenced blobs; `prune` GCs orphans.

Models are **the user's choice** — the installer never downloads one. `assistant recommend`
suggests a profile for the machine's GPU/RAM; you pull what you want.

## 5. Optional UI: Noctalia widget

If you run the **Noctalia** shell, there is an optional widget package at `widgets/noctalia/`
(bar widget + persistent attention panel + assistant OSD). It is **not** installed by default.

```bash
widgets/noctalia/install.sh            # copy + lint
widgets/noctalia/install.sh --yes      # + enable and add the bar widget
install.sh --with-noctalia             # via the main installer (optional)
```
Skip it entirely if you don't use Noctalia — the core assistant does not depend on it.

## 6. Zero-model mode

The runner works with **no models at all**: rules + on-screen context + accessibility handle
deterministic commands; STT is needed only for voice, and vision/LLM plugins are optional.
