---
title: "Install"
description: "The three ways to install Utter on Linux: clone and install, the one-line remote installer, or build from source."
---

Utter runs on **Linux on Wayland** (niri is the first-class target) with **PipeWire** and
**Python 3.12+**. An NVIDIA GPU is recommended for the larger models but not required.
Building the settings app needs Node + pnpm and a Rust toolchain. Only x86_64 release assets are
published today.

The installer is an **interactive wizard**. It walks each component (the runner and `assistant`
CLI, the settings app, the background services, speech models and the optional Noctalia widget)
and asks whether you want it. In a terminal, Enter accepts the recommended default. `--yes`
accepts them all non-interactively. Every download is verified against the release's
`sha256sums.txt`.

Pick the path that suits you.

## 1. Clone and install

Keep the repository and install from your own checkout:

```bash
git clone https://github.com/sujaisubbanna/utter-assistant.git
cd utter-assistant

./install.sh --dry-run   # walk the wizard, print the plan, change nothing
./install.sh             # install the components you choose
```

Want the smallest possible install, distro packages and the background service and nothing else?
Use the developer installer:

```bash
install/install.sh --dry-run
install/install.sh --yes
```

Undo either one with `./install.sh --uninstall`. Details, including what the developer installer
does step by step, are in [Clone and build from source](/install/from-source/).

## 2. Remote install

No clone needed:

```bash
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash
```

:::note[A bare pipe changes nothing]
Piped input is not a terminal, so the wizard cannot prompt. A bare `curl | bash` **prints the
plan and exits without changing anything**. Pass `--yes` to accept the recommended defaults, or
any other flag:
:::

```bash
# recommended defaults, no prompts
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --yes

# native package (.deb/.rpm) through your package manager instead of the AppImage (needs sudo)
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --package --yes

# only these components
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --only core,gui --yes
```

Other flags: `--skip <csv>`, `--with-noctalia`, `--dry-run`, `--uninstall`. The full flag and
environment matrix, the nine wizard steps and where everything ends up are in
[Install from the web](/install/remote/).

## 3. Build from source

The assistant core is stdlib-only Python; the settings app is Tauri v2 + React + Tailwind CSS v4.

```bash
# the assistant core, straight from the checkout
python3 -m utter.daemon --text "open youtube" --dry-run
scripts/verify.sh            # unit + e2e + conformance + spike

# the settings app
cd gui-tauri
pnpm install
pnpm tauri build             # release binary (and a .deb) in src-tauri/target/release
pnpm tauri dev               # ...or run it with hot reload
```

On Wayland with a dual-NVIDIA setup, launch the built app with the DMABUF renderer disabled.
The `utter-gui` launcher does this for you:

```bash
WEBKIT_DISABLE_DMABUF_RENDERER=1 ./gui-tauri/src-tauri/target/release/utter
```

See [Clone and build from source](/install/from-source/) for services, the `assistant` CLI and
the model store.

## After installing

Open the **Utter settings app**, set your push-to-talk keys on the **Voice** page, and pick a
recommended model on the **Models** page. Then follow [Getting started](/getting-started/).

```bash
systemctl --user enable --now utter-runner.service   # start the runner
assistant doctor --json                              # verify deps + plugins
utter-gui                                            # open the settings window
```
