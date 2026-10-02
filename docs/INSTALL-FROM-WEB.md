# Install from the web

The one-line installer downloads the latest release, verifies every asset
against `sha256sums.txt`, and installs into `$PREFIX` (default `~/.local`).

In a terminal it is an **interactive, step-by-step wizard**: it walks every
component, shows what it is, its size, whether sudo is needed and what was
detected on this machine, and asks whether you want it. With `--yes` it accepts
the recommended defaults non-interactively.

The wizard uses a built-in ANSI UI (coloured section banners, aligned tables, a
step indicator and download progress). It falls back to plain ASCII when it is
piped, when `NO_COLOR` is set or `TERM=dumb`; if `gum` is already on `PATH` it
is used for menus and confirmations. Override with `UTTER_UI=auto|gum|plain`.

## Download and run

Download the script, make it executable, and run it. This is the recommended
form: it runs in a real terminal, so the **interactive wizard** can ask you
about each component.

```bash
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh -o install.sh
chmod +x install.sh
./install.sh
```

Preview without changing anything:

```bash
./install.sh --dry-run
```

> The URL is `https://sujaisubbanna.github.io/utter-assistant/install.sh` once GitHub Pages is
> enabled (Settings → Pages → Source: **GitHub Actions**). Until then, use the
> raw file from the repo:
> `curl -fsSL https://raw.githubusercontent.com/sujaisubbanna/utter-assistant/main/install.sh -o install.sh`.

## Piping into bash

Piping straight into `bash` also works, but a pipe is **not** a terminal, so the
wizard cannot prompt: the installer prints the plan and how to customise it,
then exits `0` **without changing anything**. Use this form only when you pass
flags explicitly.

```bash
# accept all recommended defaults, no prompts
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --yes

# only install the core and the GUI; skip everything else
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --only core,gui --yes

# install everything recommended but the models, and change nothing (preview)
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --skip models --dry-run

# native package (deb/rpm) via the system package manager (needs sudo)
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --package --yes

# include the optional Noctalia widget
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --with-noctalia
```

## The wizard

The preview lists every component; the wizard then walks them one at a time.
At each prompt, press **Enter** for the recommended default, or answer
`y` / `n`, plus:

| Key | Meaning |
|---|---|
| `y` / `n` | yes / no for this component |
| `a` | yes to this **and all remaining** components |
| `s` | skip **all remaining** components |
| `q` | quit **without making any changes** |
| Enter | the recommended default shown in `[Y/n]` / `[y/N]` |

The ten steps, in order:

1. **System deps** — probes `python3`, systemd `--user`, PipeWire, `ydotool`
   (+`ydotoold`), `wtype`, `grim`, `wl-clipboard`, the Tauri v2 WebKit runtime
   `webkit2gtk-4.1`/`libsoup-3.0` (and optional `keyd`); offers to install what is
   missing with the detected package manager (**sudo**), or prints the exact command
   when there is no passwordless sudo. AT-SPI accessibility (`python-gobject` +
   `at-spi2-core`) is optional and degrades gracefully.
2. **Core runner + CLI** — the Python core (protocol, runner, `assistant` CLI,
   plugins) to `$PREFIX/share/utter`, plus the `assistant` wrapper at
   `$PREFIX/bin/assistant`. PyYAML and requests are installed into a per-user
   venv at `$PREFIX/share/utter/.venv-agent`, so the CLI and the plugin run
   without a system-wide install. Recommended.
3. **Language** — shows the detected system language (from
   `LC_ALL`/`LC_MESSAGES`/`LANG`, normalised like `en_GB.UTF-8` → `en-GB`) and lets
   you keep **English (default)** or pick another language. English ships inline
   and needs **no downloads**. For a non-English language the step *offers*
   (default No) the matching multilingual STT model (~480 MB / ~1.6 GB), a TTS
   voice and a UI localization pack when one is configured — each with its size —
   and downloads nothing unless you accept. Never sudo, never forced. With
   `--yes` it stays English and prints the one-line `assistant models pull`
   command to add a language later. The choice is saved to `[stt] language` /
   `[tts] language` (and `[tts] voice`) in `config.toml`.
4. **systemd user units** — installs `utter-runner.service` and runs
   `daemon-reload`; a **separate question** asks whether to `enable --now`
   (recommended: no — start it when you are ready).
5. **Models** — presents the `assistant recommend` tiers (STT / decision head /
   vision) with the model and estimated footprint, and asks **per tier**.
   Declining any tier skips it cleanly; nothing is downloaded unless you opt in
   and provide a source (see the env matrix).
6. **GUI** — the Tauri app. AppImage (no sudo) to `$PREFIX/bin/utter-gui`
   plus a `.desktop` entry; if `$PREFIX/bin` is not on `PATH` and Noctalia is
   present, an optional `~/.local/bin/utter-gui` symlink is created so the
   widget's left-click finds it.
7. **STT backend** — detects a whisper backend; if none, advises how to add one.
   Advisory only.
8. **Perception** (vision server deps) — detects a UI-TARS/vLLM/transformers
   stack; advises how to serve it. Advisory only.
9. **Noctalia widget** — optional. If Noctalia is **not** detected, prints a
   one-line hint and skips. If accepted, runs the bundled
   `widgets/noctalia/install.sh --yes` from the extracted core tree.
10. **Config** — writes `~/.config/utter/config.toml` from the shipped
    default if absent; if it already exists it **asks before overwriting**
    (recommended: keep). When a non-English language was chosen, the language
    values are written into `config.toml` here.

After the walk the installer prints a **plan review** (what installs, what is
skipped, whether sudo is involved), asks for a final confirm, then executes with
per-step progress and a final summary with next steps.

## Flags

| Flag | Effect |
|---|---|
| `--appimage` | install the AppImage (no sudo; default) |
| `--package` | install the native `.deb`/`.rpm` via the package manager (sudo) |
| `--only <csv>` | only offer these components (`deps,core,lang,units,models,gui,stt,perception,noctalia,config`) |
| `--skip <csv>` | never offer these components |
| `--with-noctalia` | mark the optional Noctalia widget as recommended |
| `--dry-run` | run the walk, print the plan, change nothing |
| `--uninstall` | interactive menu of installed components (per-component install-state) |
| `--yes`, `-y` | accept all recommended defaults, no prompts |
| `-h`, `--help` | show usage |

## Environment overrides

| Variable | Default | Purpose |
|---|---|---|
| `UTTER_REPO` | `sujaisubbanna/utter-assistant` | GitHub `owner/name` to fetch releases from |
| `UTTER_VERSION` | `latest` | release tag (e.g. `v0.1.1` or `0.1.0`) |
| `UTTER_BASE_URL` | GitHub Releases | override the download base (e.g. `http://127.0.0.1:8000` for testing) |
| `PREFIX` | `$HOME/.local` | install prefix |
| `UTTER_UI` | `auto` | terminal UI style: `auto` (use `gum` when present), `gum`, or `plain` |
| `UTTER_PYTHON` | auto-detected | interpreter baked into the `assistant` wrapper |
| `UTTER_MODEL_STT` | — | source to pull if the STT tier is accepted (`hf:org/repo[:file]`, `https://…`, `file://…`) |
| `UTTER_MODEL_DECISION` | — | source to pull if the decision-head tier is accepted |
| `UTTER_MODEL_VISION` | — | source to pull if the vision tier is accepted |
| `UTTER_MODEL_STT_<LANG>` | — | per-language multilingual STT source offered by the language step (e.g. `UTTER_MODEL_STT_DE_DE`); falls back to `UTTER_MODEL_STT` |
| `UTTER_MODEL_TTS` / `UTTER_MODEL_TTS_<LANG>` | — | TTS voice model/path offered by the language step |
| `UTTER_TTS_VOICE` / `UTTER_TTS_VOICE_<LANG>` | — | voice written to `[tts] voice` for the chosen language (default: the language code) |
| `UTTER_LOCALE_PACK` / `UTTER_LOCALE_PACK_<LANG>` | — | UI localization pack source; only offered when configured |

Example — install a specific version into a custom prefix, non-interactively:

```bash
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh \
  | UTTER_VERSION=v0.1.1 PREFIX="$HOME/opt/utter" bash -s -- --yes
```

## What it installs

| Component | Location |
|---|---|
| GUI (AppImage) | `$PREFIX/bin/utter-gui` |
| GUI desktop entry | `~/.local/share/applications/utter-gui.desktop` |
| Python core | `$PREFIX/share/utter/` |
| `assistant` wrapper | `$PREFIX/bin/assistant` |
| Runner user unit | `~/.config/systemd/user/utter-runner.service` |
| Config | `~/.config/utter/config.toml` (created if absent; kept on uninstall) |
| Noctalia widget (optional) | `~/.local/share/noctalia/plugins/utter` |
| Install state | `~/.local/state/utter/install.json` (+ per-component records) |

The `assistant` wrapper runs `python -m assistant` from the extracted core tree
(with `PYTHONPATH` set), so `assistant doctor --json`, `assistant recommend
--json`, etc. work from any directory without activating a virtualenv.

## `--package` vs AppImage

- **AppImage (default, no sudo)** — a single self-contained binary at
  `$PREFIX/bin/utter-gui` plus a `.desktop` entry. Best for locked-down
  machines and per-user installs.
- **`--package` (sudo)** — installs the native `.deb` (apt) or `.rpm`
  (dnf/zypper) through the system package manager. If there is no passwordless
  sudo, the installer prints the exact command instead of failing.

The Python core is always installed per-user (no sudo) regardless of mode.

## Uninstall

```bash
# interactive menu of installed components
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --uninstall

# remove everything that was installed (keeps your config and models)
curl -fsSL https://sujaisubbanna.github.io/utter-assistant/install.sh | bash -s -- --uninstall --yes
```

`--uninstall` lists the components recorded in the per-component install-state
and lets you pick which to remove (Enter = all except those marked *kept*,
numbers/commas, `a` = all, `q` = quit). It removes the GUI binary, the
`assistant` wrapper, the desktop entry, the runner unit, the extracted core
tree and the optional Noctalia widget. Your config
(`~/.config/utter`) and downloaded models are **kept** by default.

## After installing

```bash
systemctl --user enable --now utter-runner.service   # start the runner
assistant doctor --json                                  # verify deps + plugins
utter-gui                                            # open the settings window
```

If `$PREFIX/bin` is not on your `PATH`, add it:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Notes

- **x86_64 only for now.** aarch64 assets are not published yet.
- **Checksums are verified** against `sha256sums.txt`; a mismatch aborts the
  install.
- **No sudo is used** unless you accept the system-dependency or `--package`
  steps.
- The **Noctalia widget is optional** and never installed by default; use
  `--with-noctalia` or accept step 8.
- For a source checkout and the developer installer, see
  [`INSTALL.md`](INSTALL.md) and `install/README.md`.
