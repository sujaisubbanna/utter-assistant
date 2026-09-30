//! matugen theme bridge.
//!
//! If `~/.local/share/utter/colors.css` exists (written by matugen from the
//! wallpaper), its colours drive the app's semantic tokens. A debounced file
//! watcher re-reads it and emits `theme-changed` so the palette hot-swaps.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;

use serde::Serialize;
use notify::Watcher;
use tauri::{AppHandle, Emitter, Manager};

use crate::state::AppState;

const DEBOUNCE: Duration = Duration::from_millis(300);

#[derive(Clone, Debug, Default, Serialize)]
pub struct Palette {
    /// Semantic token -> colour string.
    pub tokens: BTreeMap<String, String>,
    /// Whether the palette reads as dark (drives the effective mode).
    pub dark: bool,
    /// The file it came from (empty when the built-in palette is in use).
    pub source: String,
    /// True once at least a background colour was found.
    pub available: bool,
}

fn parse_color(input: &str) -> Option<(f64, f64, f64)> {
    let value = input.trim();
    if let Some(hex) = value.strip_prefix('#') {
        let hex = hex.trim();
        let byte = |slice: &str| u8::from_str_radix(slice, 16).ok();
        return match hex.len() {
            3 => {
                let r = byte(&hex[0..1])? as f64 * 17.0;
                let g = byte(&hex[1..2])? as f64 * 17.0;
                let b = byte(&hex[2..3])? as f64 * 17.0;
                Some((r, g, b))
            }
            6 | 8 => {
                let r = byte(&hex[0..2])? as f64;
                let g = byte(&hex[2..4])? as f64;
                let b = byte(&hex[4..6])? as f64;
                Some((r, g, b))
            }
            _ => None,
        };
    }
    if value.starts_with("rgb") {
        let inner = value
            .trim_start_matches("rgba")
            .trim_start_matches("rgb")
            .trim_start_matches('(')
            .trim_end_matches(')');
        let nums: Vec<f64> = inner
            .split(|c| c == ',' || c == '/' || c == ' ')
            .filter_map(|part| part.trim().parse::<f64>().ok())
            .collect();
        if nums.len() >= 3 {
            return Some((nums[0], nums[1], nums[2]));
        }
    }
    None
}

fn is_dark(color: &str) -> bool {
    parse_color(color)
        .map(|(r, g, b)| (0.2126 * r + 0.7152 * g + 0.0722 * b) < 128.0)
        .unwrap_or(false)
}

/// Read and map a matugen/libadwaita CSS palette to the app's semantic tokens.
pub fn read_palette(path: &Path) -> Palette {
    let Ok(text) = std::fs::read_to_string(path) else {
        return Palette::default();
    };

    let mut define: BTreeMap<String, String> = BTreeMap::new();
    let mut vars: BTreeMap<String, String> = BTreeMap::new();

    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("@define-color") {
            let rest = rest.trim();
            if let Some(end) = rest.find(';') {
                let mut parts = rest[..end].splitn(2, char::is_whitespace);
                if let (Some(name), Some(value)) = (parts.next(), parts.next()) {
                    define.insert(name.trim().to_string(), value.trim().to_string());
                }
            }
        } else if line.starts_with("--") {
            if let Some(end) = line.find(';') {
                let decl = &line[..end];
                if let Some(colon) = decl.find(':') {
                    let name = decl[..colon].trim().trim_start_matches("--").to_string();
                    let value = decl[colon + 1..].trim().to_string();
                    if !value.is_empty() {
                        vars.insert(name, value);
                    }
                }
            }
        }
    }

    let pick = |keys: &[&str]| -> Option<String> {
        for key in keys {
            if let Some(value) = vars.get(*key) {
                if !value.is_empty() {
                    return Some(value.clone());
                }
            }
            if let Some(value) = define.get(*key) {
                if !value.is_empty() {
                    return Some(value.clone());
                }
            }
        }
        None
    };

    let mut tokens: BTreeMap<String, String> = BTreeMap::new();
    {
        let mut set = |token: &str, value: Option<String>| {
            if let Some(value) = value {
                tokens.insert(token.to_string(), value);
            }
        };
        set("background", pick(&["background", "window-bg-color", "window_bg_color"]));
        set("foreground", pick(&["foreground", "window-fg-color", "window_fg_color"]));
        set(
            "card",
            pick(&["card", "card-bg-color", "card_bg_color", "view-bg-color", "view_bg_color"]),
        );
        set(
            "card-foreground",
            pick(&[
                "card-foreground",
                "card-fg-color",
                "card_fg_color",
                "view-fg-color",
                "view_fg_color",
            ]),
        );
        set(
            "popover",
            pick(&["popover", "popover-bg-color", "popover_bg_color", "dialog-bg-color", "dialog_bg_color"]),
        );
        set("popover-foreground", pick(&["popover-foreground", "popover-fg-color", "popover_fg_color"]));
        set("secondary", pick(&["secondary", "popover-bg-color", "popover_bg_color"]));
        set(
            "secondary-foreground",
            pick(&["secondary-foreground", "window-fg-color", "window_fg_color", "foreground"]),
        );
        set("muted", pick(&["muted", "card-bg-color", "card_bg_color"]));
        set(
            "muted-foreground",
            pick(&["muted-foreground", "borders", "outline", "border-color"]),
        );
        set(
            "primary",
            pick(&["primary", "accent-bg-color", "accent_bg_color", "accent-color", "accent_color"]),
        );
        set(
            "primary-foreground",
            pick(&["primary-foreground", "accent-fg-color", "accent_fg_color"]),
        );
        set(
            "accent",
            pick(&["accent", "accent-color", "accent_color", "accent-bg-color", "accent_bg_color"]),
        );
        set(
            "accent-foreground",
            pick(&["accent-foreground", "accent-fg-color", "accent_fg_color"]),
        );
        set(
            "destructive",
            pick(&["destructive", "destructive-bg-color", "destructive_bg_color", "error"]),
        );
        set(
            "destructive-foreground",
            pick(&["destructive-foreground", "destructive-fg-color", "destructive_fg_color"]),
        );
        set("border", pick(&["border", "borders", "border-color", "outline"]));
        set("input", pick(&["input", "borders", "border-color"]));
        set(
            "ring",
            pick(&["ring", "accent-color", "accent_color", "primary", "accent-bg-color", "accent_bg_color"]),
        );
    }

    let available = tokens.contains_key("background");
    let dark = tokens
        .get("background")
        .map(|color| is_dark(color))
        .unwrap_or(false);

    Palette {
        tokens,
        dark,
        source: path.to_string_lossy().into_owned(),
        available,
    }
}

/// Start watching the palette file. Re-reads and emits `theme-changed` on edits.
pub fn start_watcher(app: AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let (tx, rx) = mpsc::channel::<()>();
    let mut watcher = notify::recommended_watcher(move |result: Result<notify::Event, notify::Error>| {
        if result.is_ok() {
            let _ = tx.send(());
        }
    })?;

    let theme_path: PathBuf = {
        let state = app.state::<AppState>();
        state.theme_path.clone()
    };
    let dir = theme_path
        .parent()
        .map(|path| path.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));
    let _ = std::fs::create_dir_all(&dir);
    // Watch the directory so we also see the file being created or replaced.
    watcher.watch(&dir, notify::RecursiveMode::NonRecursive)?;

    {
        let state = app.state::<AppState>();
        *state.watcher.lock().unwrap() = Some(watcher);
    }

    let app_handle = app.clone();
    std::thread::spawn(move || {
        while rx.recv().is_ok() {
            // Debounce: drain any follow-up events from the same write burst.
            while rx.recv_timeout(DEBOUNCE).is_ok() {}
            let palette = read_palette(&theme_path);
            let _ = app_handle.emit("theme-changed", palette);
        }
    });

    Ok(())
}
