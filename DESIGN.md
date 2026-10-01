# utter — design

A local, always-on **voice → desktop-action** sidecar. Context-aware first; **vision is the last resort**.
Utter is standalone: its own evdev hotkey and local whisper STT. (The old optional vocalinux
bridge was removed; the mentions below are historical.)

## Tiers (cheapest that can satisfy the intent wins)

| Tier | Name | Uses | Example |
|------|------|------|---------|
| T0 | APP | focused app/window (`niri msg --json`), app profiles, URL handlers | Zen focused + "open youtube" → open URL in new tab. No model, no screenshot. |
| T1 | A11Y | AT-SPI tree (role/name/actions) | "press the Play button" → find+invoke node. No pixels. |
| T2 | KEYBOARD | per-app shortcuts | "new tab" → `ctrl+t` via wtype/ydotool. |
| T3 | VISION | screenshot (`grim`) → UI-TARS-2B grounding → click | Only when T0–T2 cannot resolve. |

A tiny local text LLM (Qwen3-4B class) is consulted **only** when no rule matches, to produce a plan.
Routing order: `rules → llm planner → vision grounding`.

## Runtime split

- **inference** (`models/`, `.venv`, a CUDA GPU): vLLM serving `UI-TARS-2B-SFT` on `:8000`.
  Client is HTTP-only, so it runs anywhere. Resize screenshots to **1344px wide** before sending.
- **agent** (`.venv-agent`, Python 3.14 `--system-site-packages` for `gi`/AT-SPI): daemon, context,
  actions, router, voice. Runs on the 5090 or CPU (idle unless invoked).

## Modules & ownership

```
utter/
  types.py, config.py          interfaces + config (orchestrator)
  context/niri.py              focused window / monitors / workspaces / focus window
  context/clipboard.py         wl-paste
  context/atspi.py             accessibility tree dump (helper: scripts/a11y_dump.py)
  actions/launch.py            launch app (gtk-launch/.desktop Exec), open URL (xdg-open)
  actions/keyboard.py          wtype / ydotool key + type
  actions/mouse.py             ydotool move/click/scroll (needs ydotoold)
  actions/a11y_action.py       invoke AT-SPI action on a node path
  vision/screenshot.py         grim capture + multi-monitor geometry
  vision/client.py             HTTP client to the vLLM UI-TARS server
  router/profiles.py           load app profiles
  router/rules.py              deterministic rule engine -> Plan
  router/planner.py            tiny-LLM fallback -> Plan
  voice/hotkey.py              evdev push-to-talk global hotkey
  voice/stt.py                 faster-whisper / whisper.cpp transcription
  daemon.py                    ties it together; systemd user service
  profiles/*.yaml              per-app rules
  data/apps.json               generated catalog of installed apps
```

## Interface contracts (do not change without updating this file)

- `context.niri.focused_window() -> FocusedWindow | None`
- `context.niri.list_monitors() -> list[Monitor]`
- `context.niri.focus_window(window_id) -> bool`
- `context.niri.build_context(with_a11y=False) -> Context`
- `context.clipboard.get_clipboard() -> str`
- `context.atspi.dump_tree(app_id: str | None, max_nodes: int) -> UIElement | None`
- `context.atspi.find_elements(root, role=None, name=None) -> list[UIElement]`
- `actions.launch.open_url(url: str) -> ActionResult`
- `actions.launch.launch_app(app_id: str) -> ActionResult`
- `actions.keyboard.send_key(chord: str) -> ActionResult`   # "ctrl+t", "super+Return"
- `actions.keyboard.type_text(text: str) -> ActionResult`
- `actions.mouse.click_point(x: int, y: int, button: str = "left") -> ActionResult`
- `actions.mouse.scroll(direction: str, amount: int) -> ActionResult`
- `actions.a11y_action.invoke(path: str, action: str = "click") -> ActionResult`
- `vision.screenshot.capture() -> (path, Rect total_geometry)`
- `vision.client.ground(image_path: str, instruction: str, screen_w, screen_h) -> list[Point] | dict`
- `router.profiles.load() -> dict[str, AppProfile]`
- `router.rules.plan(utterance: str, ctx: Context, profiles) -> Plan | None`
- `router.planner.plan(utterance, ctx, profiles) -> Plan | None`
- `voice.hotkey.listen(on_press, on_release)`  # evdev PTT
- `voice.stt.transcribe(pcm) -> str`

All actions return `types.ActionResult`. All executors must be safe: no `shell=True`, list args only.

## Compositor / terminal / media actions (added)

Beyond app/URL/keyboard, the router can emit:

- `Action.NIRI`   args `{command, args[]}` -> `niri msg action <command> [args]` (window/column/workspace/monitor
  management: focus/move/close/fullscreen/maximize/center/float/minimize/overview/screenshot/tabbed).
  Full action list is in `utter/data/niri_actions.json`; user binds parsed from `~/.config/niri/config.kdl`.
- `Action.TERMINAL` args `{command, enter=True}` -> types the command into the focused terminal + Return.
- `Action.MEDIA`  args `{command}` (`play|pause|play-pause|next|previous|stop`) -> MPRIS over DBus via `gio`
  (no `playerctl` dependency); app-agnostic across Cine/Plezy/mpv/browser.

Coverage added for: **foot/terminals**, **Orca** (app_id `orca`), **CLI agents** (`claude`, `codex`,
`cursor-agent`, `opencode`, `grok`; launched in `foot -e` when no terminal is focused), **ComfyUI**
(`http://127.0.0.1:8188`; `queue prompt`/`generate image` escalate to a11y/vision on the Queue button),
**niri** shortcuts, **Cine**, **Plezy**. `utter/data/cli_agents.json` holds agent argv.


## Safety

- Consequential actions (send/submit/delete/purchase) require explicit user confirmation.
- Never act on a stale target: re-read context after any mutation before the next step.
- Vision-derived clicks are logged with the bounding box and confidence.
