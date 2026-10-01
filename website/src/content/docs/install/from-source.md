---
title: "Clone and build from source"
description: "Installing from a checkout: the developer installer, systemd user services, the assistant CLI, the model store and building the settings app."
---

This page is for people who keep a checkout of the repository: contributors, plugin authors, and
anyone who wants to read the code before running it. The instructions below are for Linux; the
macOS side is covered in [macOS](/guides/macos/).

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant
```

## The wizard from a checkout

The same wizard as the [remote installer](/install/remote/) runs from the repository root:

```bash
./install.sh --dry-run   # walk the wizard, print the plan, change nothing
./install.sh             # install the components you choose
./install.sh --uninstall # undo it
```

## The developer installer

`install/install.sh` is the minimal alternative: distro packages and the runner service, nothing
else. By default it only prints what it would do.

```bash
install/install.sh --dry-run        # default: print exactly what it would do
install/install.sh --yes            # actually install deps + enable the runner unit
install/install.sh --yes --no-deps  # skip distro packages, only wire the service
```

What it does:

1. Detects the distro from `/etc/os-release` (`ID` and `ID_LIKE`) and picks **pacman, apt, dnf
   or zypper** (falling back to `command -v`).
2. Installs the system dependencies, name-mapped per distro: `wtype`, `ydotool` (and
   `ydotoold`), `grim`, `wl-clipboard`, `pipewire`, `webkit2gtk-4.1` for the settings app, and
   optionally `keyd`.
3. Checks the `input` group and `/dev/uinput`, and **prints** the `usermod -aG input`, udev and
   re-login steps. It never silently changes groups.
4. Installs and, with `--yes`, enables the **user** service `utter-runner.service`, bound to the
   graphical session via the `scripts/utter-wayland-ready.sh` wrapper.
5. Records what it did in `$XDG_STATE_HOME/utter/install.json` so it can be reversed.
6. Runs `python -m assistant doctor --json` (or `recommend --json`) to verify.

Uninstall:

```bash
install/uninstall.sh --dry-run
install/uninstall.sh --yes            # stop/disable units, remove recorded files
install/uninstall.sh --yes --purge    # also remove models + config
```

Package removals are **printed**, never performed automatically.

## Services

The runner is a systemd **user** unit. User services do not inherit the session environment, so
the unit runs through `scripts/utter-wayland-ready.sh`, which discovers `WAYLAND_DISPLAY`,
`DBUS_SESSION_BUS_ADDRESS` and `NIRI_SOCKET` before starting the runner.

| Unit | Purpose |
|---|---|
| `utter-runner` | the modular runner (plugin supervisor), installed by the installer |
| `utter-bridge` | legacy: vocalinux + voice → action, if you use the Python assistant directly |
| `utter-vision` | vLLM UI-TARS grounding server (`:8000`) |
| `utter-planner` | vLLM planner (`:8001`) |
| `utter-audio-defaults` | keeps the chosen output and denoised input pinned |

Only the runner unit (and the legacy `utter.service` plus `ydotoold.service`) ship in the
repository. The vision, planner and audio-defaults units are conveniences on the reference
machine; the scripts they wrap (`scripts/serve_vision.sh`, `scripts/serve_planner.sh`,
`scripts/utter-audio-defaults.sh`) are in the repo, and you can turn them into units yourself.
See [Configuration](/guides/configuration/#services) for the shipped unit files.

```bash
systemctl --user status utter-runner.service
journalctl --user -u utter-runner.service -f
```

Clients such as the settings app and the Noctalia widget connect to the runner at
`$XDG_RUNTIME_DIR/utter/runner.sock`.

## The `assistant` CLI

```bash
python -m assistant doctor [--json]                    # deps + plugin negotiation + drift
python -m assistant recommend [--json]                 # hardware-aware profile suggestions
python -m assistant models list|show <n>|pull <src>|rm <n>|prune [--json]
python -m assistant status [--json]                    # runner.status passthrough
python -m assistant install-state record|show
```

`doctor --json` includes a `deps` section (which CLI tools and libraries are present) alongside,
per plugin, the negotiated protocol version, unknown capabilities, missing requirements and the
list of permissions with whether each is enforced or advisory. The full command reference is on
[The assistant CLI](/reference/cli/).

## The model store

Models live in an Ollama-style, XDG-compliant store:

```text
$XDG_DATA_HOME/utter/models/      # override with UTTER_MODELS
  manifests/<host>/<ns>/<name>/<tag>.json
  blobs/sha256-<hex>
```

- Sources: `hf:org/repo[:file]` resolves to the Hugging Face `resolve/main` URL; bare `https://`
  URLs and local `file://` paths also work.
- Pulls are **resumable** (partial file plus `curl -C -`, or urllib `Range`), with retry and
  backoff, SHA-256 verification, an atomic rename, a pull lock and a disk-space preflight.
- `rm` drops the manifest and any now-unreferenced blobs; `prune` collects orphans.

Models are **your choice**. The installer never downloads one. `assistant recommend` suggests a
profile for your GPU and RAM; you pull what you want. See the [Models guide](/guides/models/).

## Running the core from the checkout

The assistant core is stdlib-only Python, so you can run it directly:

```bash
# route a command without executing it (prints the plan)
python3 -m utter.daemon --text "open youtube" --dry-run

# the full verification: runner unit tests, socket e2e, conformance, measurement spike
scripts/verify.sh
```

The dry run is the fastest way to check what a phrase would do. The `utter_py` plugin defaults
`UTTER_DRY_RUN` to **on**, so only `UTTER_DRY_RUN=0` touches the desktop.

## Building the settings app

The settings app is Tauri v2 + React + Tailwind CSS v4. It needs Rust 1.90+, Node 22+ with
pnpm, and the `webkit2gtk-4.1` and `libsoup-3.0` libraries.

```bash
cd gui-tauri
pnpm install
pnpm tauri build          # release binary + .deb in src-tauri/target/release[/bundle]
pnpm tauri dev            # dev mode with hot reload
```

For a quick binary without bundling:

```bash
pnpm build                # frontend -> dist/
cd src-tauri
cargo build --release --features custom-protocol
```

The `custom-protocol` feature embeds the built frontend. Without it, Tauri treats the build as
*dev* and expects the Vite server on `http://localhost:1420`.

Run a built binary directly:

```bash
WEBKIT_DISABLE_DMABUF_RENDERER=1 ./src-tauri/target/release/utter
```

:::tip[Why `WEBKIT_DISABLE_DMABUF_RENDERER=1`?]
On Wayland with dual NVIDIA GPUs, WebKitGTK's DMABUF renderer can produce a blank or black
window. Disabling it makes the webview render through shared memory. The `gui-tauri/utter-gui`
launcher wrapper and the dev scripts set it for you; an installed `.desktop` entry may need it in
`Exec=` too.
:::

Two environment variables help with screenshots and testing: `UTTER_GUI_ROUTE` (for example
`voice`) forces the initial page and `UTTER_GUI_THEME` (`light`, `dark` or `system`) forces the
theme.

## Optional: the Noctalia widget

If you run the **Noctalia** shell, there is an optional widget package at `widgets/noctalia/`
(bar widget, persistent attention panel and assistant OSD). It is **not** installed by default.

```bash
widgets/noctalia/install.sh            # copy + lint
widgets/noctalia/install.sh --yes      # + enable and add the bar widget
./install.sh --with-noctalia           # via the main installer
```

Skip it entirely if you do not use Noctalia. The core assistant does not depend on it. See
[Noctalia widget and OSD](/guides/noctalia/).

## Writing a plugin?

Start from `plugins/fake_py/` (Python) or `plugins/fake_rs/` (Rust) and read
[Writing a plugin](/plugins/writing-a-plugin/).
