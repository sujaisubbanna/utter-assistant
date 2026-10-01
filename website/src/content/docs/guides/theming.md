---
title: "Theming"
description: "How the settings app and the Noctalia widgets pick up your matugen (Material You) palette, with a Light, Dark and System toggle."
---

The settings app is themed from the same **matugen** palette (Material You colours generated
from your wallpaper) as the rest of your desktop, with a **Light / Dark / System** toggle. The
design direction is clean and modern: generous whitespace, few colours (one accent plus status
colours), simple rows, no gradients.

## The theme toggle

A three-state control (**Light / Dark / System**, default **System**) sits at the bottom of the
sidebar.

- The choice is persisted in `localStorage` under `utter.theme`.
- **System** follows `prefers-color-scheme` live.
- Colours are CSS custom properties. A `.dark` class on `<html>` swaps the built-in light and
  dark palettes, and an inline script sets the class before first paint, so there is no flash.

Without a matugen palette the app uses a clean built-in palette: warm neutrals with the Utter
yellow (`#f2c230` in light, `#f7c948` in dark) as the single accent.

## matugen integration

If `~/.local/share/utter/colors.css` exists (matugen output), its colours drive the semantic
tokens:

```text
matugen → ~/.local/share/utter/colors.css → gui-tauri/src-tauri/src/theme.rs
                                                 (notify watcher → "theme-changed")
```

- The Rust side parses both GTK-style `@define-color <name> <hex>;` lines and `:root { --x: ... }`
  custom properties, and maps them onto the semantic tokens `--background`, `--foreground`,
  `--card`, `--primary`, `--primary-foreground`, `--secondary`, `--muted`, `--accent`,
  `--destructive`, `--border` and `--ring`.
- A debounced (about 300 ms) file watcher re-reads the palette on change and emits
  `theme-changed`; the frontend swaps the tokens live with a short transition. Change your
  wallpaper and the app follows without a restart.
- A matugen palette only overrides the tokens when **its lightness matches the selected mode**.
  A dark palette is ignored in Light mode, so the toggle keeps working on a dark desktop.
- Set `UTTER_THEME_CSS` to point at a different palette file (handy for tests).

## Installing the matugen template

```bash
scripts/install-matugen-utter.sh          # --dry-run supported
```

The script is idempotent. It copies the template to
`~/.config/matugen/templates/utter-colors.css`, safely adds a `[templates.utter]` block to
`~/.config/matugen/config.toml` (backing it up first), and creates `~/.local/share/utter/`.
Re-run your normal matugen command to regenerate the colours.

The block it adds looks like this. The installer writes absolute paths because matugen does not
reliably expand `~`:

```toml
[templates.utter]
input_path  = "~/.config/matugen/templates/utter-colors.css"
output_path = "~/.local/share/utter/colors.css"
```

## Accessibility

matugen's Material 3 roles pair every `x` colour with an `on_x`; text and icons always use the
`on_*` role, which keeps contrast correct in both schemes. `matugen --contrast -1..1` tunes the
whole scheme; match the value you use for the rest of the desktop. Both light and dark are
emitted and follow the system.

## Widgets

The optional Noctalia widget and on-screen display use Noctalia's own theming, so they match the
shell they live in. See [Noctalia widget and OSD](/guides/noctalia/).
