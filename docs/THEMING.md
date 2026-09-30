# Theming with matugen

The settings GUI is the **Tauri v2 app** (`gui-tauri/`), themed from the same **matugen** palette
(Material You from your wallpaper) as the rest of your desktop, with a **Light/Dark/System**
toggle. Design direction: clean and modern — generous whitespace, few colors (accent + status),
simple rows, no gradients. (The earlier GTK4 + libadwaita app in `gui/` is **superseded**.)

## How it gets its colors (legacy GTK4 app)
libadwaita reads `~/.config/gtk-4.0/gtk.css`; your matugen setup already writes the named
colours (`@define-color accent_bg_color …`) that `gtk.css` imports. On top of that, the app
loads a utter-specific palette file with its own `Gtk.CssProvider`:

```
matugen  →  ~/.local/share/utter/colors.css  →  gui/utter_gui/theme.py
                                                      (CssProvider + Gio.FileMonitor)
```
This is deterministic live reload: when matugen regenerates the palette (wallpaper change), the
app reapplies it without a restart.

## Install (idempotent)
```bash
scripts/install-matugen-utter.sh          # --dry-run supported
```
Copies the template to `~/.config/matugen/templates/utter-colors.css`, safely adds a
`[templates.utter]` block to `~/.config/matugen/config.toml` (backing it up first), and
creates `~/.local/share/utter/`. Re-run your normal matugen to regenerate colors.

## Added config
```toml
[templates.utter]
# the installer writes absolute paths (matugen does not reliably expand ~)
input_path  = "/home/<user>/.config/matugen/templates/utter-colors.css"
output_path = "/home/<user>/.local/share/utter/colors.css"
```

## Accessibility
matugen's M3 roles pair every `x` with an `on_x`; text/icons use the `on_*` role for contrast.
`matugen --contrast -1..1` tunes the whole scheme — match the value used for the rest of the
desktop. Both light and dark are emitted and follow the system.

See also: `docs/CUSTOMISING.md`, `docs/ARCHITECTURE.md` (UI section).

## Tauri settings app (`gui-tauri/`)

The modern Tauri v2 settings app reads the **same** matugen palette. Instead of
libadwaita named colours it drives CSS custom properties:

```
matugen → ~/.local/share/utter/colors.css → gui-tauri/src-tauri/src/theme.rs
                                                 (notify watcher → `theme-changed`)
```

- The Rust side parses both `@define-color <name> <hex>;` and `:root { --x: … }`
  and maps them onto semantic tokens (`--background`, `--foreground`, `--card`,
  `--primary`, `--primary-foreground`, `--secondary`, `--muted`, `--accent`,
  `--destructive`, `--border`, `--ring`).
- A debounced (~300 ms) `notify` watcher re-reads the file on change and emits
  `theme-changed`; the frontend swaps the tokens live with a short transition.
- A matugen palette only overrides the tokens when its lightness matches the
  selected mode (Light/Dark/System), so the toggle keeps working on a dark
  desktop. Without the file, a built-in palette is used.
- Set `UTTER_THEME_CSS` to point at a different palette (tests).

See `gui-tauri/README.md` for the build/run/theme details.

