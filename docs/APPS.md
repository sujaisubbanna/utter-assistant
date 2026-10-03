# Apps, steps & the Zen case study

How a spoken command becomes desktop actions, how app knowledge is organised, how to
add a new application, and how browser (Zen) tab control was added with WebDriver BiDi.

## Table of contents

1. [The layered model](#1-the-layered-model)
2. [App profiles & the generated catalog](#2-app-profiles--the-generated-catalog)
3. [The contextual resolver: `ensure_url` / `ensure_app`](#3-the-contextual-resolver-ensure_url--ensure_app)
4. [niri compositor actions](#4-niri-compositor-actions)
5. [Terminal / CLI agents / media](#5-terminal--cli-agents--media)
6. [Adding a new application](#6-adding-a-new-application)
7. [The Zen case study: browser control via WebDriver BiDi](#7-the-zen-case-study-browser-control-via-webdriver-bidi)
8. [Replicating for another browser](#8-replicating-for-another-browser)
9. [Verifying a routing change](#9-verifying-a-routing-change)

---

## 1. The layered model

```text
utterance ─▶ router ─▶ Plan(steps) ─▶ executor ─▶ Action handlers ─▶ desktop
             (rules + constrained decision head)        (T0..T3)
```

### Router — rules first, then a constrained decision head

`Utter.route()` (in `utter/daemon.py`) resolves an utterance as:

1. **Deterministic rules** — `plan()` in `utter/router/rules.py`.
   Multi-step plans (e.g. "close youtube" → focus then close-window) are returned
   directly.
2. **Constrained decision head (Jev)** — `decide()` in `utter/router/decide.py`.
   It enumerates a small set of *fully-resolved* candidate
   actions (`build_candidates` in `utter/router/decide_candidates.py`) and asks the
   local tiny LLM to **choose one** by letter. Candidates are capped at 12 plus a
   mandatory `"none"` (`MAX_CANDIDATES = 13`, `decide_candidates.py`). A choice below
   `cfg.decide_threshold` is treated as an abstention.
3. **Free-form planner** — `utter/router/planner.py::plan()` is the last-resort
   JSON planner, consulted only when the decision head is unavailable.
4. **Perception** (a11y T1 → vision T3) is reached only for `click_element` /
   `click_point` steps (see the executor below).

The key safety property: the decision head **chooses among precomputed candidates**;
it never authors free-form `args` (see [`docs/TRUST.md`](TRUST.md)).

### Steps — the `Action` vocabulary

A plan is a list of `Step(action, args, tier, description, confirm)`
(`utter/types.py`). The `Action` enum (`types.py`) is the Python
reference vocabulary:

| `Action` | Typical args |
|---|---|
| `open_url` | `{url, new_tab?}` |
| `ensure_url` | `{url, site?}` — context-aware |
| `launch_app` | `{app}` or `{argv}` |
| `ensure_app` | `{app, argv?}` — context-aware |
| `focus_app` | `{app}` |
| `search` | `{query}` |
| `key` | `{chord}` e.g. `ctrl+t`, `Return` |
| `type_text` | `{text}` |
| `terminal` | `{command, enter?}` |
| `niri` | `{command, args[]}` |
| `media` | `{command}` (`play`/`pause`/`play-pause`/`next`/`previous`/`stop`) |
| `click_element` | `{description}` — needs perception |
| `click_point` | `{x, y}` |
| `scroll` | `{direction, amount}` |
| `wait` / `speak` / `done` | — |

> In the modular protocol these are **strings + JSON Schema**, not this enum
> (`docs/ARCHITECTURE.md` §4). `utter_py` exposes the same ops as strings
> (`plugins/utter_py/plugin.py`).

### Executor — `utter/executor.py`

`Executor.execute_step()` dispatches `_do_<action>` (`executor.py`) and re-reads
context between steps; the plan aborts on the first failed step
(`executor.py`). `click_element` escalates **T1 accessibility → T3 vision**
(`_do_click_element`, `executor.py`). Tiers are defined in `utter/types.py`:
`APP` (T0) → `A11Y` (T1) → `KEYBOARD` (T2) → `VISION` (T3).

---

## 2. App profiles & the generated catalog

App knowledge has three layers, all under `utter/`:

| Artefact | Path | Role |
|---|---|---|
| Curated profiles | `utter/profiles/*.yaml` | hand-written per-app rules |
| Preselected set | `utter/profiles/_preselected.yaml` | the curated apps enabled by default |
| Per-kind defaults | `utter/profiles/_defaults.yaml` | shortcuts/search_url inherited by kind |
| Your profiles | `~/.config/utter/profiles/*.yaml` | your own apps and edits (the settings app writes here); they win |
| Installed-app catalogue | `~/.local/share/utter/generated.yaml` | a minimal profile for every installed `.desktop`, generated per machine |
| Raw catalog | `~/.local/share/utter/apps.json` | parsed `.desktop` entries (json) |

The repo ships only a handful of common apps (Firefox, Chrome, VS Code, Files,
Spotify) plus the generic per-kind fallbacks. Anything specific to one machine
belongs in your profiles folder, and the catalogue is generated on each machine.

The loader is `utter/router/profiles.py`:

- `AppProfile` (`profiles.py`) — fields: `id`, `name`, `aliases`, `launch`,
  `terminal`, `new_window`, `search_url` (must contain `{q}`), `shortcuts`
  (name → chord), `app_ids` (compositor app_ids), `mime_types`, `kind`,
  `enabled` (the opt-in gate) and `preselected` (id is in the shipped set).
- `load()` reads `_defaults.yaml`, the machine's catalogue (`GENERATED_PATH`), every
  curated `*.yaml`, then your profiles (`USER_PROFILES_DIR`), which are merged on top
  and ordered first (the reserved names `_defaults.yaml` / `generated.yaml` /
  `_preselected.yaml` are skipped as per-app files, in `load`). It merges curated
  overrides onto generated entries (`merge_profiles`, `profiles.py`) and orders
  curated profiles ahead of generated-only ones, with `generic-*` last.
- Merge semantics (`_merge_entry`, `profiles.py`): **shortcuts are merged**;
  a curated `aliases` list **replaces** the generated keyword-derived aliases (it is
  not unioned); other fields are replaced.
- Kind defaults fill missing shortcuts and a missing `search_url`
  (`_apply_defaults`, `profiles.py`).
- `resolve(name, profiles)` (`profiles.py`) is case-insensitive by `id`,
  then `name`, then `alias`, then a token-subset fallback. `rules._resolve`
  (`rules.py`) is a defensive id/name/alias variant.

### Per-app opt-in gate

Every profile has an `enabled` flag. **A disabled app is invisible to Utter**:
no launch/ensure, focus, close, shortcut, custom command, media target, or
typed/keystroke target. Still allowed regardless of the gate: sites/URLs
(`open youtube`), generic media transport keys (`media next`), compositor/niri
actions, dictation into the focused field, and CLI agents (`codex`), whose
dangerous part is the runner's `terminal`/`input` gate.

- `enabled` is computed by `load()`: an explicit `enabled` in a merged override
  wins; otherwise the id is enabled iff it is in `_preselected.yaml`; otherwise
  `False`. On a fresh install only that curated set (`spotify`, `firefox`,
  `google-chrome`, `code`, `org.gnome.Nautilus`) is live; user-customised apps
  are **not** auto-enabled.
- A one-time marker `$XDG_STATE_HOME/utter/apps-state.json`
  (`{"policy_version": 1}`) records the hard cut. It is a version record only —
  it never re-seeds a user's later choices.
- `scripts/gen_app_catalog.py` deliberately never writes `enabled`: the gate is
  policy, not per-machine catalogue data.
- Routing consumes `profiles.enabled_profiles(...)` (the enabled subset); the
  executor keeps the **full** dict so a direct RPC call still refuses a
  known-disabled app but an unknown argv launch and an explicit `window_id`
  capability keep working.
- Toggling writes `~/.config/utter/profiles/<id>.yaml` `{id, enabled: bool}`.
  Custom commands for a disabled app are kept (inert) and resurface when it is
  re-enabled; resetting the override returns to the `preselected` default.

### Building the catalog

`scripts/gen_app_catalog.py` scans `.desktop` files and writes both
`~/.local/share/utter/apps.json` and `~/.local/share/utter/generated.yaml`:

```bash
# scan and write both artefacts
scripts/gen_app_catalog.py

# preview counts only
scripts/gen_app_catalog.py --dry-run
```

- Scan order (highest precedence first): `~/.local/share/applications`,
  flatpak exports, `/usr/local/share/applications`, `/usr/share/applications`
  (`_desktop_dirs`, `scripts/gen_app_catalog.py`).
- Field codes (`%u`, `%f`, …) are stripped from `Exec` (`clean_exec`, `gen_app_catalog.py`).
- `kind` is inferred from `Categories` (`KIND_CATEGORIES` / `infer_kind`,
  `gen_app_catalog.py`).
- `app_ids` candidates come from `StartupWMClass`, flatpak ids, the binary basename
  and the desktop-file id (`derive_app_ids`, `gen_app_catalog.py`).

---

## 3. The contextual resolver: `ensure_url` / `ensure_app`

`ensure_url` decides whether to reuse an already-open tab/window or open/launch
(`_do_ensure_url`, `executor.py`), in order:

0. **BiDi exact tab match** (Zen only, best-effort) — `zen.activate_match()` across
   all tabs including background ones, then ask niri to raise the window. See
   [§7](#7-the-zen-case-study-browser-control-via-webdriver-bidi).
1. Focused browser already showing the site (window-title keyword).
2. Another browser window whose title matches → focus it.
3. A browser is open → `open_url`, then focus that window.
4. No browser → `launch_app`/`xdg-open`.

Browser detection uses `_BROWSERS` (`executor.py`) and the profile-kind check.
Window title matching uses the site keyword from `step.args["site"]` or
`_host_keyword(url)` (`executor.py`).

`ensure_app` is simpler (`_do_ensure_app`, `executor.py`): focus a window whose `app_id`
matches, else `launch_app(argv or app)`.

Both read live window state from `utter/context/niri.py`:
`build_context()` → `list_windows()`/`find_windows()` → `focus_window()` /
`focus_window_on_workspace()` (`utter/context/niri.py`). niri's
`focus-window` does **not** cross workspaces, so `focus_window_on_workspace` first
resolves the window's workspace **index** and focuses it (`niri.py`).

---

## 4. niri compositor actions

The router maps phrases to niri actions via `NIRI_MAP` (`rules.py`) plus
workspace/monitor regexes in `_niri_action` (`rules.py`). Additional phrases
are loaded from `utter/data/niri_phrases.json` and merged without clobbering the
curated map (`_load_niri_phrases`, `rules.py`).

The executor runs `niri msg action <command> [args...]`
(`_do_niri`, `executor.py`). Example phrases: `"focus right"` → `focus-column-right`,
`"fullscreen"` → `fullscreen-window`, `"workspace 3"` → `focus-workspace 3`.

Regenerate the phrase map from your real niri config and the live action list:

```bash
scripts/gen_niri_phrases.py
```

It reads `~/.config/niri/config.kdl` (override with `NIRI_CONFIG`),
`utter/data/niri_actions.json`, and optionally `niri msg action`
(`read_kdl_text` / `query_live_actions`, `scripts/gen_niri_phrases.py`). Every niri action gets an auto phrase (dashes → spaces)
and curated aliases win (`CURATED` / `build_curated`, `gen_niri_phrases.py`).

---

## 5. Terminal / CLI agents / media

- **CLI agents**: `CLI_AGENTS` and `TERMINAL_LAUNCH` are loaded from
  `utter/data/cli_agents.json` by `_load_cli_agents()` (`rules.py`).
  Spoken names map to argv (e.g. `"opencode"` → `["opencode"]`). If a terminal is
  focused, the agent runs via `Action.TERMINAL`; otherwise it is launched as
  `foot -e <agent>` (`_cli_agent`, `rules.py`).
- **Terminal commands**: `"run <cmd>"` types into a focused terminal
  (`_do_terminal`, `executor.py`); the terminal app-id set is
  `TERMINALS` (`rules.py`) and `_is_terminal` (`rules.py`).
- **Media (MPRIS)**: `MEDIA_MAP` (`rules.py`) maps phrases to
  `play|pause|play-pause|next|previous|stop`; `_mpris()` drives the active
  `org.mpris.MediaPlayer2.*` player over DBus via `gio` (`executor.py`).
  This is app-agnostic (Cine/Plezy/mpv/browser).
- **ComfyUI** has special-cased phrases in `_comfy` (`rules.py`).

---

## 6. Adding a new application

**Recipe**

1. **Create a curated profile** `utter/profiles/<kind>_<id>.yaml` with the
   required `id` (other fields are optional; defaults fill in). Do not name it
   `_defaults.yaml` or `generated.yaml` — those are reserved (`load`, `profiles.py`).
2. **Add aliases** (how you'll say it) and **`app_ids`** (the compositor app_id /
   `StartupWMClass`; find it with `niri msg --json windows`).
3. *(Optional)* Add a known site to `SITES` in `utter/router/rules.py`.
4. *(Optional)* Add a terminal CLI preset to `utter/data/cli_agents.json`.
5. *(Optional)* Add niri bind phrases to `scripts/gen_niri_phrases.py` `CURATED`,
   then regenerate.
6. **Regenerate catalogs** so the new app and phrases are picked up:
   ```bash
   scripts/gen_app_catalog.py
   scripts/gen_niri_phrases.py   # only if you touched niri phrases
   ```
7. **Verify** with a routing test (see [§9](#9-verifying-a-routing-change)).

**Full example profile** — a hypothetical `signal` app
(`utter/profiles/chat_signal.yaml`):

```yaml
id: signal
name: Signal
aliases: [signal, signal messenger, signal app]
launch: ["/usr/bin/signal-desktop", "--use-tray-icon"]
terminal: false
new_window: ["/usr/bin/signal-desktop", "--new-window"]
search_url: null
shortcuts:
  new_window: ctrl+n
  find: ctrl+f
app_ids: [signal, Signal]        # niri app_id / StartupWMClass
mime_types: []                   # e.g. x-scheme-handler/sgnl
kind: other                      # browser | terminal | filemanager | editor |
                                 # media | game | office | utility | other
```

Notes:

- Prefer **`launch` as a list** of argv tokens; field codes are not needed here — the
  launcher spawns the list directly with no shell (`launch_app`, `utter/actions/launch.py`).
- `kind` selects which `_defaults.yaml` shortcuts/search_url apply
  (`_apply_defaults`, `profiles.py`). `browser`, `terminal`, `filemanager`, `editor`, `media`,
  `game`, `office`, `utility`, `other` are the recognised kinds.
- `search_url` should contain `{q}` (`AppProfile.search_url`, `profiles.py`).

---

## 7. The Zen case study: browser control via WebDriver BiDi

The goal: "open youtube" should **activate an already-open YouTube tab** (even in a
background window) instead of opening a duplicate. Window-title matching alone can't
see background tabs, so Zen is driven over the **WebDriver BiDi Remote Agent**.

### 7a. Desktop override — start Zen with a debugging port

Zen only exposes BiDi when launched with `--remote-debugging-port=9222`.
`scripts/install-zen-bidi-desktop.sh` writes a user override that shadows the system
entry:

```bash
scripts/install-zen-bidi-desktop.sh            # writes ~/.local/share/applications/zen-browser.desktop
scripts/install-zen-bidi-desktop.sh --uninstall
```

It rewrites only the **first** `Exec=` line to
`Exec="<zen-bin>" --remote-debugging-port=9222 %u`
(`install-zen-bidi-desktop.sh:44-53`), and verifies the injection before installing.
`ZEN_BIDI_PORT` overrides the port.

### 7b. Helper — `scripts/zen_bidi.py`

A stdlib + `websockets` CLI (run inside `.venv-agent`). Commands
(`zen_bidi.py`):

| Command | Behaviour |
|---|---|
| `ping` | exit 0 if the agent answers, else 2 |
| `list` | JSON array of top-level tabs |
| `find <substr>` | JSON of the best matching tab, else `null` |
| `activate <context>` | `browsingContext.activate` for a context id |
| `activate-match <substr>` | **find + activate in ONE session** |

Internals: `Agent` opens a single BiDi session via
`ws://127.0.0.1:<port>/session` with `proxy=None` (`zen_bidi.py`), calls
`browsingContext.getTree`, flattens top-level tabs (`_flatten_top_level`), and scores
matches by hostname/path, deprioritising `accounts.`/`login.`/`consent.` subdomains
(`_find`, `zen_bidi.py`).

**Why find + activate must be one session:** BiDi **context ids are not stable across
sessions**. If you `find` (session A), close it, then `activate` (session B), the
context id may be gone. `activate-match` therefore finds and activates inside the
same `with Agent(...)` block (`cmd_activate_match`, `zen_bidi.py`).

### 7c. Wrapper — `utter/browser/zen.py`

A thin, importable wrapper that shells out to the helper so the main assistant needs
no `websockets` dependency (`zen.py`):

- `is_up()` — a fast TCP probe of `127.0.0.1:9222` (no subprocess, `zen.py`).
- `list_tabs()` / `find_tab(substr)` / `activate(context)` / `activate_match(substr)`
  — run the helper via `_agent_python()` (default `<repo>/.venv-agent/bin/python`,
  override `UTTER_AGENT_PY`) with an 8 s timeout (`zen.py`).
- Port from `ZEN_BIDI_PORT` (default `9222`, `PORT` in `zen.py`).

### 7d. Executor tier-0 path

In `_do_ensure_url`, **before** any window-title logic
(`executor.py`):

```python
from .browser import zen
if zen.is_up():
    tab = zen.activate_match(kw or url)
    if tab:
        cand = (niri.find_windows(app_id="zen", title_contains=kw)
                or niri.find_windows(app_id="zen"))
        if cand:
            fn = getattr(niri, "focus_window_on_workspace", None) or niri.focus_window
            fn(cand[0].id)
        return ActionResult(True, Action.ENSURE_URL, Tier.APP,
                            f"activated existing '{kw}' tab via BiDi: {tab.get('url','')}")
```

The niri step exists because **BiDi selects the tab but does not raise the window on
Wayland** — the compositor must be asked. The whole block is best-effort: any failure
falls through to the window-title paths.

### 7e. Caveats

- **One session per operation.** Context ids are not stable across sessions, so never
  split find/activate (use `activate-match`).
- **Loopback only.** The helper connects to `ws://127.0.0.1` with `proxy=None`; remote
  access is not supported.
- **The port must be set at browser start.** Without
  `--remote-debugging-port=9222`, `is_up()` is false and the BiDi path is skipped.
- **WebDriver signal.** Attaching a WebDriver BiDi session is the standard WebDriver
  mode of operation; pages can detect it via `navigator.webdriver`. This code does not
  attempt to spoof that signal.
- **Firefox-family semantics.** BiDi + `--remote-debugging-port` is a
  Firefox/Gecko feature, not Chromium's debugging protocol (see below).

---

## 8. Replicating for another browser

- **Mozilla-family (Firefox, LibreWolf, Waterfox, …):** the same mechanism works —
  start it with `--remote-debugging-port=<port>`, set `ZEN_BIDI_PORT` to match, and
  adapt the niri `app_id` filter in the executor's BiDi block
  (`executor.py`, currently `app_id="zen"`) to the new compositor app_id. The
  helper itself is browser-agnostic.
- **Chromium-family (Chrome, Chromium, Brave, Edge, …):** these use the **Chrome
  DevTools Protocol (CDP)**, not WebDriver BiDi. `scripts/zen_bidi.py` will not work
  as-is; you would need a CDP client (HTTP `/json/list` + WebSocket) with equivalent
  find/activate semantics. Window-title fallback already recognises these browsers via
  `_BROWSERS` (`executor.py`), so `ensure_url` still works without CDP — just
  without background-tab awareness.

---

## 9. Verifying a routing change

Fastest checks are dry-run and the real-plugin verification:

```bash
# route without executing (prints the plan)
.venv-agent/bin/python -m utter.daemon --text "open youtube" --dry-run

# the real assistant wrapped as a plugin through the runner
.venv-agent/bin/python tests/m3/verify_m3.py
```

`tests/m3/verify_m3.py` asserts the vertical slice through the runner (dry-run on):
`"open youtube"` → `ensure_url` `https://www.youtube.com`; `"pull up youtube"` → the
decision-head path; `"tile right"` → niri `move-column-right`; plus policy
(`screen` `terminal` → `-32006`, `user` `terminal` → `-32003`). It also runs one real
(non-dry-run) safe action and reports the result (`tests/m3/verify_m3.py`).

After changing profiles or catalogs, re-run `scripts/gen_app_catalog.py` and re-check
that the app resolves (a curated profile beats a generated one). The full runner
protocol suite is `scripts/verify.sh`.
