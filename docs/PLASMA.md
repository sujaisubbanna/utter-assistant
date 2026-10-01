# Utter on KDE Plasma (KWin)

Utter was built on niri. This document describes the KDE Plasma backend: what it
needs, how it talks to KWin, what works, what is missing, and how to verify it.

> **Status: implemented and unit-tested, not yet exercised on a live Plasma
> session.** Every D-Bus interface, shortcut name and command below is the
> documented Plasma API, and the whole backend runs in dry-run on any Linux box,
> but nothing here has been run against a real KWin yet. The "Untested" section
> lists exactly what needs a Plasma desktop to confirm. Please report what breaks.

## Design

All compositor-specific behaviour sits behind one module,
`utter/context/compositor.py`, and one package, `utter/context/backends/`:

| Module | Role |
|---|---|
| `compositor.py` | detection rules, backend selection (`auto` / `niri` / `kwin`), capability names, the structured `Outcome` result, the `--print-plan` probe |
| `backends/niri.py` | thin wrapper over the unchanged `utter/context/niri.py` (grim screenshots, `niri msg action`) |
| `backends/kwin.py` | the Plasma backend: D-Bus calls, the niri → KWin action table, kdotool / KWin-script window access, Spectacle / portal screenshots |
| `backends/dbus.py` | argv builders and reply parsers for `gdbus`, `qdbus6`/`qdbus`, `dbus-send`; a tiny stdlib D-Bus receiver (`LiteBus`) for KWin script results |
| `backends/fallback.py` | unknown compositors: everything returns "unsupported", `grim` is still tried for screenshots |

Every backend exposes the same module-level functions (see
`backends/__init__.py`), so the executor, the router, the vision tier and the
`utter_py` plugin are written once against `compositor.active()`.

**niri is untouched.** `utter/context/niri.py` was not modified; on niri
`utter.context.desktop.provider()` still returns that very module, the executor
still runs `niri msg action <command> [args...]` byte-for-byte, and the vision
tier still uses `grim` with niri's logical geometry. The niri backend only adds
the uniform extras (close/minimize/maximize by id, dry-run planning).

### Detection

`compositor.detect()` reads the session environment; the first rule that matches wins
and the evidence is recorded:

| Rule | Backend |
|---|---|
| `XDG_CURRENT_DESKTOP` contains `niri` | niri |
| `XDG_CURRENT_DESKTOP` contains `KDE` (colon lists like `KDE:ubuntu` count) | kwin |
| `KDE_FULL_SESSION=true` or `KDE_SESSION_VERSION` set | kwin |
| `XDG_SESSION_DESKTOP` / `DESKTOP_SESSION` is `plasma*`, `kde`, `kde-plasma` | kwin |
| `XDG_SESSION_DESKTOP` / `DESKTOP_SESSION` contains `niri` | niri |
| `NIRI_SOCKET` set | niri |
| anything else | unknown → fallback backend |

`XDG_CURRENT_DESKTOP` is checked first so a stale `NIRI_SOCKET` inherited by a
Plasma session does not win. `XDG_SESSION_TYPE` (wayland/x11) and
`KDE_SESSION_VERSION` (5/6) are recorded for diagnostics.

### Selection

1. `UTTER_COMPOSITOR=niri|kwin` (environment; tests and one-off probes)
2. `[general] compositor = "auto" | "niri" | "kwin"` in `~/.config/utter/config.toml`
3. detection (above)

An unknown name falls back to detection and says so in the probe's `reason`.

## Requirements

| Need | Package (Arch / Fedora names) | Why |
|---|---|---|
| Plasma 6 on Wayland | `plasma-desktop` | primary target; Plasma 5 and X11 sessions are best-effort |
| a D-Bus CLI: `gdbus` **or** `qdbus6`/`qdbus` **or** `dbus-send` | `glib2` / `qt6-tools` / `dbus` | every KWin call; `gdbus` is preferred (it can pass `a{sv}` for the portal) |
| `spectacle` | `spectacle` | screenshots for the vision tier (`grim` does not work on KWin) |
| `ydotool` + `ydotoold` | `ydotool` | typing and key chords (`wtype` has no virtual-keyboard protocol on KWin) |
| `kdotool` (optional, recommended) | AUR `kdotool`, Fedora `kdotool` | window list and per-window actions without loading KWin scripts |
| `kscreen-doctor` (optional) | `libkscreen` | monitor geometry for screenshots; the PNG size is used otherwise |
| `wl-clipboard` (optional) | `wl-clipboard` | clipboard fallback when klipper is unavailable |

Not needed on Plasma: `niri`, `grim`, `wtype`.

## How it talks to Plasma

Everything is a subprocess with an **argv list** (never `shell=True`), or a
direct socket to the session bus for the receiver. The probe prints every argv
without running it:

```bash
python -m utter.context.compositor --print-plan
python -m utter.context.compositor --json
```

### D-Bus interfaces

| Service / path / interface | Methods used | Purpose |
|---|---|---|
| `org.kde.KWin` `/KWin` `org.kde.KWin` | `currentDesktop()`, `setCurrentDesktop(i)`, `nextDesktop()`, `previousDesktop()` | virtual desktop switching |
| `org.kde.KWin` `/VirtualDesktopManager` `org.kde.KWin.VirtualDesktopManager` | properties `count`, `current`, `desktops` (`a(uss)` position, id, name) via `org.freedesktop.DBus.Properties.Get` | desktop list / ids |
| `org.kde.KWin` `/Scripting` `org.kde.kwin.Scripting` | `loadScript(path, pluginName)` → id, `unloadScript(pluginName)` | load the window-query / window-action scripts |
| `org.kde.KWin` `/Scripting/Script<id>` (Plasma 6) or `/<id>` (Plasma 5) `org.kde.kwin.Script` | `run()` | execute a loaded script |
| `org.kde.kglobalaccel` `/component/kwin` `org.kde.kglobalaccel.Component` | `invokeShortcut(name)` | actions on the focused window and desktop navigation (works on Plasma 5 and 6) |
| `org.kde.kglobalaccel` `/component/org_kde_spectacle_desktop` | `invokeShortcut("FullScreenScreenShot" …)` | the user-facing "take a screenshot" phrases |
| `org.kde.kglobalaccel` `/component/org_kde_powerdevil` | `invokeShortcut("Turn Off Screen")` | "screen off" |
| `org.kde.klipper` `/klipper` `org.kde.klipper.klipper` | `getClipboardContents()` | clipboard read (first choice; `wl-paste` fallback) |
| `org.freedesktop.portal.Desktop` `/org/freedesktop/portal/desktop` `org.freedesktop.portal.Screenshot` | `Screenshot("", {interactive: false, handle_token})` + `Response` signal via `gdbus monitor` | screenshot fallback when Spectacle is missing |

### Window queries and per-window actions

KWin on Wayland has no public "list windows" D-Bus API, so two sources exist:

1. **`kdotool`** when installed: `kdotool search ""` → UUIDs, then
   `getactivewindow`, `getwindowname`, `getwindowclassname`, `getwindowpid`,
   `get_desktop_for_window`; actions `windowactivate`, `windowclose`,
   `windowminimize`, `set_desktop_for_window`.
2. **A tiny KWin script** otherwise (`[kwin] use_scripts`): utter writes a `.js`
   file under `$XDG_RUNTIME_DIR/utter/`, loads it through `org.kde.kwin.Scripting`,
   runs it and unloads it. The query script walks `workspace.windowList()`
   (Plasma 6) or `workspace.clientList()` (Plasma 5) and reports JSON back with
   `callDBus("org.utter.kwin.p<pid>", "/", "org.utter.kwin", "result", json)`.
   That bus name is owned by `dbus.LiteBus`, a ~250-line stdlib D-Bus client that
   does `Hello` + `RequestName` and waits for the one method call. Action scripts
   (`workspace.activeWindow = w`, `w.closeWindow()`, `w.minimized = true`,
   `w.desktops = [desktop]`) are fire-and-forget and need no receiver.

KWin window ids are UUIDs; utter uses ints everywhere, so the backend maps UUIDs to
stable per-process ints (`window_int` / `window_uuid`).

Actions on **the focused window** (no id) do not need either source: they go
through `kglobalaccel` shortcuts (`Window Close`, `Window Minimize`,
`Window Maximize`, `Window to Desktop N`). "Maximize window *X*" activates X
first and then invokes `Window Maximize`.

### niri action names on KWin

The router keeps producing niri action names (`close-window`,
`focus-workspace 3`, `move-window-to-workspace 2`, `focus-column-left` …); the
KWin backend maps them in `kwin.ACTION_MAP`:

| niri action | KWin |
|---|---|
| `close-window` / `fullscreen-window` / `maximize-column` / `minimize-window` | `Window Close` / `Window Fullscreen` / `Window Maximize` / `Window Minimize` |
| `focus-column-left|right`, `focus-window-up|down` | `Switch Window Left|Right|Up|Down` |
| `move-column-left|right`, `move-window-up|down` | `Window Quick Tile Left|Right|Top|Bottom` |
| `focus-workspace N` | `setCurrentDesktop(N)` |
| `focus-workspace-down|up` | `Switch to Next|Previous Desktop` |
| `move-window-to-workspace N` | `Window to Desktop N` |
| `move-window-to-workspace-down|up` | `Window to Next|Previous Desktop` |
| `focus-monitor-*`, `move-window-to-monitor-*` | `Switch to Screen …`, `Window One Screen …`, `Window to Next|Previous Screen` |
| `toggle-overview` | `Overview` |
| `screenshot-screen|window`, `screenshot` | Spectacle shortcuts |
| `power-off-monitors` | powerdevil `Turn Off Screen` |
| `toggle-window-floating`, column/tabbed actions, `focus-workspace-previous`, `quit`, `spawn` | **unsupported** (structured result) |

An unmapped action returns `Outcome(ok=False, unsupported=True, detail="unsupported on kwin: …")`,
which the executor turns into `ActionResult(unsupported=True)`; the router can
fall back to the next tier instead of treating it as a crash.

### Screenshots

Order for `[kwin] screenshot = "auto"`: `spectacle -b -n -f -o <png>` → XDG portal
(gdbus; may show a permission dialog) → `grim` (unreliable on KWin, last resort).
The method that worked is recorded in `kwin.last_screenshot_method` and shown by
the probe. Geometry comes from `kscreen-doctor -j` (logical = size / scale) and
falls back to the PNG size; grounding uses normalized coordinates so either works.

### Clipboard

`[kwin] clipboard = "auto"`: klipper over D-Bus first, `wl-paste` second. The
source that actually answers is remembered for the rest of the process.

### Input

Key chords and typing use `ydotool` first on KWin (uinput; needs `ydotoold` and
the `input` group) and fall back to `wtype` once. Pointer moves use
`ydotool mousemove --absolute` scaled by `[kwin] pointer_abs_factor`
(default 1.0; niri keeps its measured 0.5). Override at runtime with
`UTTER_MOUSE_SCALE`.

## Configuration

```toml
[general]
compositor = "auto"        # auto | niri | kwin

[kwin]
screenshot = "auto"        # auto | spectacle | portal | grim
clipboard = "auto"         # auto | klipper | wl-clipboard
use_kdotool = true
use_scripts = true
script_timeout_s = 3.0
pointer_abs_factor = 1.0
```

## What works, what is missing

| Capability | niri | KWin |
|---|---|---|
| focused window / window list | ✅ | ✅ via kdotool or KWin script |
| focus a window (also across desktops) | ✅ | ✅ (activation switches desktop) |
| close / minimize (focused or by id) | ✅ | ✅ |
| maximize | ✅ | ✅ (activate + `Window Maximize`) |
| move window to workspace / desktop | ✅ | ✅ |
| switch workspace / desktop | ✅ | ✅ |
| screenshots for the vision tier | ✅ grim | ✅ Spectacle, portal fallback |
| clipboard | ✅ wl-paste | ✅ klipper, wl-paste fallback |
| typing / key chords | ✅ wtype → ydotool | ✅ ydotool → wtype |
| scrollable-tiling column actions, floating toggle, tabbed display | ✅ | ❌ unsupported (no KWin concept) |
| "last used workspace" | ✅ | ❌ unsupported |
| monitor geometry | ✅ niri | partial: `kscreen-doctor` or PNG size |
| OSD / Noctalia widget | ✅ | ❌ Noctalia is niri-only; Plasma notifications are a follow-up |

## Settings app

The Troubleshooting page shows a **Desktop** section: detected compositor (with the
environment evidence), the active backend (or the config override that chose it), the
session type, and one row per capability marked *Available* / *Not available*, with a
switch to hide the unavailable rows. The data comes from `assistant doctor --json`
(`compositor` section), so it reflects the Python the services actually run. The
system-tools list swaps `wtype`/`grim` for `gdbus|qdbus6`, `spectacle` and `kdotool`
on Plasma.

## Verify

```bash
# unit tests: detection, selection, argv / D-Bus construction, unsupported path,
# script templates, reply parsers, the stdlib D-Bus receiver (live on the local bus)
python3 tests/platform/test_compositor_detection.py

# everything (includes the test above)
scripts/verify.sh

# simulate a Plasma session anywhere and print the resolved backend + every argv
env -u NIRI_SOCKET XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true \
    python3 -m utter.context.compositor --print-plan

# dry-run the KWin backend through the executor (nothing is executed)
env -u NIRI_SOCKET XDG_CURRENT_DESKTOP=KDE UTTER_DRY_RUN=1 python3 -c '
from utter.context import compositor
b = compositor.active(); print(b.NAME, b.close_window().argv, b.run_action("toggle-window-floating").detail)'
```

On a real Plasma session:

```bash
assistant doctor                       # "compositor: detected kwin -> backend kwin"
python -m utter.context.compositor     # capabilities + tools actually found
python -c 'from utter.context import desktop; print(desktop.list_windows()[:3])'
python -c 'from utter.vision import screenshot; print(screenshot.capture())'
```

## Untested on real Plasma (needs a live session)

- `kdotool` output shapes (`search ""` matching everything; one UUID per line).
- The KWin script path end to end: `loadScript` accepting a file under
  `$XDG_RUNTIME_DIR`, the `/Scripting/Script<id>` vs `/<id>` object path per
  Plasma version, `callDBus` from a script reaching our `LiteBus` name (the
  receiver itself is verified against a real session bus with `gdbus` as the
  caller), `window.internalId` string form matching kdotool's `{uuid}`.
- kglobalaccel shortcut **names** per Plasma version: `Move Window to the Center`,
  `Switch to Screen to the Left/Right/Above/Below`, `Window One Screen …` are
  Plasma 6 names and may not exist on Plasma 5; Spectacle's component path.
- The XDG portal screenshot flow (whether `xdg-desktop-portal-kde` prompts every
  time with `interactive: false`) and the `gdbus monitor` line format for `Response`.
- `kscreen-doctor -j` field names (`pos`, `size`, `scale`) and whether `size` is
  physical or logical pixels.
- `ydotool` absolute-pointer scaling on KWin (`pointer_abs_factor` default 1.0).
- Plasma 5 / X11 sessions in general: the same D-Bus names exist but were not run.

## Gaps and uncertainties

- **Binary / typed D-Bus payloads.** CLI tools print text; the `a(uss)` desktops
  struct is parsed from `gdbus` output only. `qdbus` and `dbus-send` are limited to
  scalars and strings, which covers every call the backend makes except `desktops`
  and the portal (gdbus-only).
- **Plasma 5 vs 6.** Script API differences are handled (`windowList`/`clientList`,
  `activeWindow`/`activeClient`, `desktops`/`desktop`, script object path). Some
  Plasma 6 shortcut names have no Plasma 5 equivalent (see above).
- **Portal availability.** Without `spectacle` and without `xdg-desktop-portal-kde`
  the vision tier has no screenshot source; the probe says so.
- **Performance.** kdotool costs ~5 subprocesses per window; the script path is
  one load/run/unload per query. Fine for a handful of windows; a persistent script
  with change signals is the obvious follow-up.
