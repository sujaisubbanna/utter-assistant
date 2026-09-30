# utter-gui (Tauri)

A modern, native-feeling **settings app for the utter assistant**, built with
**Tauri v2 + React + Tailwind CSS v4**. It replaces the GTK4 window with a clean
web-tech UI while staying a pure *client*: it reads/writes
`~/.config/utter/config.toml`, shells out to the `assistant` CLI and drives
systemd user units. No assistant logic lives here.

![General](screenshots/light-general.png)

## What it covers

Sidebar sections mirror the GTK4 app one-for-one:

| Page | What it does |
|------|--------------|
| **General** | Autostart toggle, trigger mode, live start/stop/restart of the five user units, runner connection |
| **Voice** | Push-to-talk key capture (dictation + assistant), STT backend/model/language/device, input device, live mic level |
| **Models** | Installed models, pull with **live NDJSON progress**, remove, prune, hardware recommendations (one-click apply) |
| **LLM** | Provider, base URL, model, decision-head toggle, confidence threshold, endpoint test |
| **Speech** | TTS enable, engine (marked when missing), voice, test |
| **Perception** | Vision on/off, model, endpoint, screenshot width, GPU devices, accessibility toggle, provenance notes |
| **Plugins** | Runner negotiation, plugin enable/disable, permissions (enforced vs advisory), dependency health, run doctor, restart runner |
| **Safety** | Confirmation policy, dangerous-operation toggles behind a warning, allow/block lists |
| **Diagnostics** | Live journalctl tail, doctor report + raw JSON, export support bundle |
| **About** | App/runtime versions, paths, palette source |

## Requirements

- Rust 1.90+, Node 22+ with `pnpm` (npm/bun work too)
- `webkit2gtk-4.1`, `libsoup-3.0` (installed on most GNOME/KDE systems)
- The utter checkout, with `.venv-agent/bin/python` able to run `python -m assistant`

## Build

```bash
cd gui-tauri
pnpm install
pnpm tauri build          # release binary + .deb in src-tauri/target/release[/bundle]
```

For a quick binary without bundling:

```bash
pnpm build                # frontend -> dist/
cd src-tauri
cargo build --release --features custom-protocol
```

> The `custom-protocol` feature is what makes a build embed the frontend from
> `dist/`. Without it (a plain `cargo build`), Tauri treats the build as *dev*
> and expects the Vite server on `http://localhost:1420`.

## Run

```bash
# dev (hot reload): starts Vite, then the app
cd gui-tauri && pnpm tauri dev

# run a built binary directly
WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  ./src-tauri/target/release/utter
```

`gui-tauri/utter-gui` is a launcher wrapper — it finds the built binary,
sets `UTTER_REPO` to this checkout and applies the WebKit workaround. Point
the Noctalia widget's left-click at it (the widget already calls `utter-gui`).

### Why `WEBKIT_DISABLE_DMABUF_RENDERER=1`

On Wayland with dual NVIDIA GPUs, WebKitGTK's DMABUF renderer can produce a
blank/black surface. Disabling it makes the webview render through shared
memory. The launcher and the dev scripts set it for you; an installed `.desktop`
entry may need it in `Exec=` too.

## Theme system

A three-state control (**Light / Dark / System**, default **System**) lives at
the bottom of the sidebar:

- The choice is persisted in `localStorage` (`utter.theme`).
- `System` follows `prefers-color-scheme` live via `matchMedia`.
- Colours are CSS custom properties; a `.dark` class on `<html>` swaps the
  built-in light/dark palette. An inline script in `index.html` sets the class
  before first paint, so there is no flash.

### matugen (optional)

If `~/.local/share/utter/colors.css` exists (matugen output), its colours
drive the semantic tokens — `--background/--foreground/--card/--primary/
--primary-foreground/--secondary/--muted/--accent/--destructive/--border/
--ring`. A Rust `notify` watcher (debounced ~300 ms) re-reads the file and emits
`theme-changed`, and the palette hot-swaps with a short transition.

The GTK/libadwaita `@define-color` names and the `:root` custom properties are
both mapped. A matugen palette only overrides the tokens when **its lightness
matches the selected mode** (a dark palette is ignored in Light mode), so the
toggle keeps working on a dark desktop. When no palette is present, a clean
built-in palette is used.

## Architecture

```
gui-tauri/
  src/                     React UI
    lib/                   api (invoke wrappers), config, theme, status, keys, hooks
    components/            shell (Titlebar, Sidebar, ThemeControl) + ui/ primitives
    pages/                 one file per settings page
    styles.css             tokens, Tailwind theme bridge, base + motion
  src-tauri/               Rust backend
    src/commands.rs        all #[tauri::command]s (subprocess + streaming)
    src/process.rs         list-argument command builder (never a shell string)
    src/config.rs          comment-preserving TOML line editor
    src/theme.rs           matugen palette parser + debounced watcher
    src/zip.rs             tiny dependency-free support-bundle writer
```

Design rules honoured here:

- **Off the UI thread**: blocking work runs in `spawn_blocking`; streams are
  forwarded with `emit` (`models://progress`, `log://line`, `mic://level`,
  `theme-changed`).
- **List arguments only**: `std::process::Command` is always built from an array
  — no shell, no injection from config or UI values.
- **Small dependency tree**: React + Vite + Tailwind on the frontend; `tauri`,
  `serde`, `toml`, `notify` on the backend. Icons and UI primitives are local.

### Interpreter resolution

Same order as the Noctalia poller: `UTTER_PYTHON` → repo
`.venv-agent/bin/python` → `.venv/bin/python` → `python3`. The repo root comes
from `UTTER_REPO`, else the dev checkout path.

### Screenshot / dev affordances

`UTTER_GUI_ROUTE` (e.g. `voice`) and `UTTER_GUI_THEME`
(`light|dark|system`) force the initial page and theme — handy for
screenshots and testing.

## Development notes

- The frontend talks to Tauri only through `src/lib/api.ts`. Opening the Vite
  page in a plain browser mostly works; Tauri calls reject and are caught.
- `src-tauri/src/commands.rs` is the whole backend contract; add a command there
  and register it in `lib.rs`.
- Accessibility: interactive elements use visible `:focus-visible` rings, ARIA
  roles/labels, and keyboard navigation. `prefers-reduced-motion` disables
  animation.

## Known gaps

- The `Light`/`Dark` toggle does not force a dark matugen palette into light
  mode (by design — see above); a light matugen palette would need a light-aware
  template.
- Model pulls can't be cancelled from the UI yet (the backend command exists:
  `cancel_models_pull`).
- Reordering/exporting config is not exposed; only the fields the pages use.
- AppImage bundling is disabled (`bundle.targets = ["deb"]`) to avoid downloading
  bundle tooling at build time.
