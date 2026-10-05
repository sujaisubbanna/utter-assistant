---
title: "KDE Plasma"
description: "Running Utter on KDE Plasma (KWin, Wayland): what to install, how the KWin backend talks to Plasma over D-Bus, what works, what is missing, and how to verify it."
---

Utter started on niri. KDE Plasma is now a first-class target: a small compositor layer detects
the session and drives KWin over **D-Bus** instead of `niri msg`, with the same voice commands
on top. niri keeps its original code path; nothing changes there.

:::note[Not yet run on a live Plasma session]
The KWin backend is implemented and unit-tested, and every command it would run can be printed
in dry-run on any Linux machine, but it has not been exercised against a real KWin yet. The
[repository document](https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/PLASMA.md)
lists exactly what still needs a Plasma desktop to confirm. Please report what breaks.
:::

## What to install

| Need | Package | Why |
|---|---|---|
| Plasma 6 on Wayland | `plasma-desktop` | primary target; Plasma 5 and X11 are best-effort |
| `gdbus` **or** `qdbus6` **or** `dbus-send` | `glib2` / `qt6-tools` / `dbus` | every call to KWin; `gdbus` preferred |
| `spectacle` | `spectacle` | screenshots for the vision tier (`grim` does not work on KWin) |
| `ydotool` + `ydotoold` | `ydotool` | typing and key chords (`wtype` has no protocol on KWin) |
| `kdotool` (recommended) | AUR / Fedora `kdotool` | window list and per-window actions without KWin scripts |
| `kscreen-doctor` (optional) | `libkscreen` | monitor geometry for screenshots |

You do **not** need `niri`, `grim` or `wtype` on Plasma. The installer's dependency list and the
settings app's *System tools* adapt automatically.

Plasma is a Linux session, so the inference stack is the same as on niri: the planner is
**vLLM + 4-bit AWQ** on `http://127.0.0.1:8001/v1` (`qwen3-4b`) and vision is **vLLM UI-TARS** on
`http://127.0.0.1:8000/v1` (`uitars`). **llama.cpp + GGUF** is for macOS/Windows only. Speech
recognition uses the mandatory whisper.cpp model. The compositor backend changes only how Utter
reaches the desktop, not how the models are served.

## How it is detected

Utter reads the session environment and picks a backend. First match wins:

1. `XDG_CURRENT_DESKTOP` contains `niri` → niri; contains `KDE` → KWin
2. `KDE_FULL_SESSION=true` or `KDE_SESSION_VERSION` → KWin
3. `XDG_SESSION_DESKTOP` / `DESKTOP_SESSION` is `plasma…`, `kde`, `kde-plasma` (or contains `niri`)
4. `NIRI_SOCKET` set → niri
5. otherwise: unknown. Window actions report *unsupported*; dictation, typing and launching still work.

Force a backend in `~/.config/utter/config.toml`:

```toml
[general]
compositor = "auto"   # auto | niri | kwin
```

## What it uses

| Concern | Plasma backend |
|---|---|
| Focused window, window list | `kdotool`, or a tiny KWin script loaded via `org.kde.kwin.Scripting` that reports back over D-Bus |
| Focus / close / minimize / move to desktop | `kdotool` or the script (by window); `org.kde.kglobalaccel` shortcuts for the focused window (`Window Close`, `Window Minimize`, `Window to Desktop 3`…) |
| Maximize | activate the window, then `Window Maximize` |
| Virtual desktops | `org.kde.KWin /KWin setCurrentDesktop`, `org.kde.KWin.VirtualDesktopManager` |
| "focus left", "move window right", "next desktop"… | mapped from the niri action names to KWin shortcuts (`Switch Window Left`, `Window Quick Tile Right`, `Switch to Next Desktop`) |
| Screenshots | `spectacle -b -n -f -o <png>`, then the XDG screenshot portal, then `grim` |
| Clipboard | `org.kde.klipper getClipboardContents`, then `wl-paste` |
| Typing and key chords | `ydotool`, then `wtype` |

Phrases that only make sense on a scrollable tiler ("float window", "tabbed column",
"consume into column", "last used workspace") return a structured *unsupported* result on
Plasma instead of failing, so the assistant can fall back to the next tier.

## Configuration

```toml
[kwin]
screenshot = "auto"        # auto | spectacle | portal | grim
clipboard = "auto"         # auto | klipper | wl-clipboard
use_kdotool = true         # prefer kdotool for window queries/actions when installed
use_scripts = true         # otherwise load a tiny KWin script for window queries
script_timeout_s = 3.0
pointer_abs_factor = 1.0   # ydotool absolute-pointer multiplier (niri uses 0.5)
```

## Settings app

**Troubleshooting → Desktop** shows the detected compositor (with the environment variable that
decided it), the active backend or the config override that chose it, the session type, and one
row per capability (focused window, window list, focus, close, minimise, maximise, move to
desktop, switch desktop, screenshots, compositor commands) marked *Available* or *Not available*,
with a switch to hide the unavailable rows.

## Verify

```bash
# unit tests (no Plasma needed)
python3 tests/platform/test_compositor_detection.py

# simulate a Plasma session anywhere and print the backend + every command it would run
env -u NIRI_SOCKET XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true \
    python3 -m utter.context.compositor --print-plan
```

On a real Plasma desktop, `assistant doctor` prints
`compositor: detected kwin -> backend kwin`, and `python -m utter.context.compositor` lists which
tools were found and which capabilities are live.

## Known gaps

- Not run on a live Plasma yet (see the note above): kdotool output shapes, the KWin script
  round-trip, some Plasma 6 shortcut names on Plasma 5, the portal flow, `kscreen-doctor` fields
  and `ydotool` pointer scaling are the items to confirm first.
- Structured D-Bus replies are parsed from `gdbus` output only; `qdbus`/`dbus-send` cover the
  scalar calls.
- The Noctalia widget and on-screen display are niri-only; Plasma notifications are a follow-up.
