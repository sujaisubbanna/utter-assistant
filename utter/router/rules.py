"""Deterministic rule engine (tier T0/T2).

Given an utterance + cheap context + app profiles, produce a Plan WITHOUT any
perception. Returns None when the command needs accessibility/vision, so the
daemon can escalate. Keep this fast and predictable.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from ..types import Action, Context, Plan, Step, Tier

# --- well-known sites -------------------------------------------------------
SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "google": "https://www.google.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "wikipedia": "https://en.wikipedia.org",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "netflix": "https://www.netflix.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "spotify": "https://open.spotify.com",
    "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "hacker news": "https://news.ycombinator.com",
    "hn": "https://news.ycombinator.com",
    "amazon": "https://www.amazon.in",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
}

SITE_SEARCH: dict[str, str] = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "google": "https://www.google.com/search?q={q}",
    "github": "https://github.com/search?q={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "spotify": "https://open.spotify.com/search/{q}",
}

BROWSERS = {
    "zen", "zen-browser", "zen-browser-bin", "firefox", "google-chrome",
    "chrome", "com.google.Chrome", "chromium", "brave", "brave-browser",
    "org.mozilla.firefox", "vivaldi", "opera",
}

URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.I)
DOMAIN_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(\/\S*)?$", re.I)

_COMMON_KEYS = {
    "enter": "Return",
    "return": "Return",
    "escape": "Escape",
    "esc": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}

# niri compositor actions: phrase -> (niri action, args)
NIRI_MAP: dict[str, tuple[str, list]] = {
    "focus left": ("focus-column-left", []),
    "focus right": ("focus-column-right", []),
    "focus up": ("focus-window-up", []),
    "focus down": ("focus-window-down", []),
    "next column": ("focus-column-right", []),
    "previous column": ("focus-column-left", []),
    "first column": ("focus-column-first", []),
    "last column": ("focus-column-last", []),
    "move window left": ("move-column-left", []),
    "move window right": ("move-column-right", []),
    "move window up": ("move-window-up", []),
    "move window down": ("move-window-down", []),
    "move column left": ("move-column-left", []),
    "move column right": ("move-column-right", []),
    "close window": ("close-window", []),
    "fullscreen": ("fullscreen-window", []),
    "toggle fullscreen": ("fullscreen-window", []),
    "maximize column": ("maximize-column", []),
    "expand column": ("expand-column-to-available-width", []),
    "center column": ("center-column", []),
    "center window": ("center-window", []),
    "toggle floating": ("toggle-window-floating", []),
    "float window": ("toggle-window-floating", []),
    "minimize window": ("minimize-window", []),
    "next workspace": ("focus-workspace-down", []),
    "previous workspace": ("focus-workspace-up", []),
    "next monitor": ("focus-monitor-next", []),
    "previous monitor": ("focus-monitor-previous", []),
    "focus monitor left": ("focus-monitor-left", []),
    "focus monitor right": ("focus-monitor-right", []),
    "move to next monitor": ("move-window-to-monitor-next", []),
    "move to previous monitor": ("move-window-to-monitor-previous", []),
    "overview": ("toggle-overview", []),
    "open overview": ("open-overview", []),
    "close overview": ("close-overview", []),
    "take screenshot": ("screenshot-screen", []),
    "screenshot": ("screenshot-screen", []),
    "toggle tabbed": ("toggle-column-tabbed-display", []),
    "tabbed column": ("toggle-column-tabbed-display", []),
}

# MPRIS media control (app-agnostic: Cine/Plezy/mpv/browser)
MEDIA_MAP: dict[str, str] = {
    "play": "play", "pause": "pause", "resume": "play",
    "play pause": "play-pause", "toggle play": "play-pause", "play/pause": "play-pause",
    "next": "next", "next track": "next", "next song": "next", "next episode": "next",
    "skip": "next", "skip track": "next", "skip forward": "next",
    "previous": "previous", "previous track": "previous", "previous song": "previous",
    "previous episode": "previous", "skip back": "previous",
    "stop": "stop", "stop playback": "stop",
}

# CLI agents launched inside a terminal (data/cli_agents.json overrides defaults)
def _load_cli_agents() -> tuple[dict[str, list[str]], list[str]]:
    defaults = {
        "claude code": ["claude"],
        "claude code cli": ["claude"],
        "codex": ["codex"],
        "cursor agent": ["cursor-agent"],
        "cursor-agent": ["cursor-agent"],
        "opencode": ["opencode"],
        "grok": ["grok"],
        "grok bot": ["grok"],
    }
    terminal = ["foot", "-e"]
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cli_agents.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        terminal = data.pop("terminal", terminal)
        agents = {str(k): v for k, v in data.items() if isinstance(v, list)}
        return (agents or defaults), terminal
    except Exception:
        return defaults, terminal


CLI_AGENTS, TERMINAL_LAUNCH = _load_cli_agents()

TERMINALS = {"foot", "alacritty", "kitty", "wezterm", "ghostty", "konsole",
             "gnome-terminal", "xterm", "alacritty"}
COMFY_URL = "http://127.0.0.1:8188"

# ComfyUI startup script that mirrors the user's shell workflow.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMFY_LAUNCH = os.path.join(_REPO_ROOT, "scripts", "start-comfyui.sh")


def _load_niri_phrases() -> dict:
    """Voice phrases -> niri action, generated from the user's config.kdl binds."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "niri_phrases.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh).get("phrases", {})
        out: dict = {}
        for phrase, spec in (data or {}).items():
            if isinstance(spec, dict) and spec.get("command"):
                out[str(phrase).lower()] = (spec["command"], list(spec.get("args", []) or []))
        return out
    except Exception:
        return {}


# merge generated phrases without clobbering the curated map
for _p, _spec in _load_niri_phrases().items():
    NIRI_MAP.setdefault(_p, _spec)



def normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[.!?,]+$", "", text)
    return re.sub(r"\s+", " ", text)


def _is_browser(ctx: Context, profiles: dict) -> bool:
    app = ctx.focused_app
    if not app:
        return False
    if app in BROWSERS:
        return True
    prof = profiles.get(app)
    return bool(prof and getattr(prof, "kind", "") == "browser")


def _default_browser_id(profiles: dict) -> Optional[str]:
    for pid, prof in profiles.items():
        if getattr(prof, "kind", "") == "browser":
            return pid
    return None


def _is_terminal(ctx: Context, profiles: dict) -> bool:
    app = ctx.focused_app
    if app in TERMINALS:
        return True
    prof = profiles.get(app)
    return bool(prof and getattr(prof, "kind", "") == "terminal")


def _niri_action(t: str) -> Optional[dict]:
    if t in NIRI_MAP:
        cmd, args = NIRI_MAP[t]
        return {"command": cmd, "args": args}
    m = re.match(r"^(?:go to |switch to )?workspace (\d+)$", t)
    if m:
        return {"command": "focus-workspace", "args": [int(m.group(1))]}
    m = re.match(r"^move (?:window|column) to workspace (\d+)$", t)
    if m:
        return {"command": "move-window-to-workspace", "args": [int(m.group(1))]}
    m = re.match(r"^move to (?:monitor )?(left|right|up|down)$", t)
    if m:
        return {"command": f"move-window-to-monitor-{m.group(1)}", "args": []}
    return None


# --- fast command-like classifier (used for prefix-free activation) ---------
_COMMAND_FIRST_WORDS = {
    "open", "launch", "start", "run", "execute", "spawn", "close", "focus",
    "switch", "go", "navigate", "visit", "search", "google", "look", "click",
    "press", "hit", "tap", "type", "write", "enter", "scroll", "page", "play",
    "pause", "resume", "stop", "next", "previous", "skip", "take", "screenshot",
    "fullscreen", "maximize", "minimize", "center", "expand", "float", "move",
    "workspace", "reload", "refresh", "back", "forward", "copy", "paste", "cut",
    "undo", "redo", "select", "save", "clear", "queue", "generate", "show",
    "hide", "mute", "volume", "quit",
}

_SHORTCUT_PHRASES = {
    "new tab", "close tab", "reload", "refresh", "go back", "back",
    "go forward", "forward", "address bar", "url bar", "reopen tab",
    "restore tab", "find on page", "next tab", "previous tab", "copy", "paste",
    "cut", "undo", "redo", "select all", "save", "clear", "clear terminal",
    "clear screen", "queue prompt", "generate image", "run workflow",
}


def is_command_like(text: str) -> bool:
    """Instant (no model) test for whether an utterance should be treated as a
    command instead of dictated text. Used by the prefix-free voice lane."""
    t = normalize(text or "")
    if not t:
        return False
    if t in MEDIA_MAP or t in NIRI_MAP or t in _SHORTCUT_PHRASES or t in CLI_AGENTS:
        return True
    if re.match(r"^(?:go to |switch to )?workspace \d+$", t):
        return True
    if re.match(r"^move (?:window|column) to workspace \d+$", t):
        return True
    if re.match(r"^move to (?:monitor )?(?:left|right|up|down)$", t):
        return True
    first = t.split(" ", 1)[0]
    return first in _COMMAND_FIRST_WORDS


def _shortcut_step(ctx: Context, profiles: dict, name: str) -> Optional[Step]:
    """Map a semantic action name to a per-app shortcut key press (tier T2)."""
    app = ctx.focused_app
    prof = profiles.get(app)
    if not prof:
        return None
    key = (getattr(prof, "shortcuts", {}) or {}).get(name)
    if not key:
        return None
    return Step(Action.KEY, {"chord": key}, tier=Tier.KEYBOARD, description=f"{name} in {app}")


def _make_plan(utterance: str, steps, source: str = "rules",
               confidence: float = 1.0, needs: bool = False) -> Plan:
    return Plan(utterance=utterance, steps=steps, source=source,
                confidence=confidence, needs_perception=needs)


# Sentinel: a matcher has claimed the utterance but has no cheap plan, so the
# chain must stop and the caller should escalate. This mirrors the original
# plan()'s early ``return None`` for an explicit but unknown "open X".
_ESCALATE = object()


# --- ordered matcher chain --------------------------------------------------
# Each matcher returns a Plan when it handles the utterance, None to let the
# next matcher try, or _ESCALATE to stop with no plan. The tuple order below is
# the contract: first match wins and must not change (pinned by
# tests/router/test_rules_order.py).


def _custom(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    focused_profile = profiles.get(ctx.focused_app) if ctx.focused_app else None
    custom_chord = (getattr(focused_profile, "commands", {}) or {}).get(t) if focused_profile else None
    if custom_chord:
        return _make_plan(utterance, [Step(Action.KEY, {"chord": custom_chord}, tier=Tier.KEYBOARD,
                                           description=f"custom command: {t}")])
    return None


def _niri(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    na = _niri_action(t)
    if na is not None:
        return _make_plan(utterance, [Step(Action.NIRI, na, tier=Tier.APP, description=t)])
    return None


def _media(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    if t in MEDIA_MAP:
        return _make_plan(utterance, [Step(Action.MEDIA, {"command": MEDIA_MAP[t]},
                                          tier=Tier.APP, description=t)])
    return None


def _cli_agent(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^(?:open|launch|start|run|spawn)\s+(.+)$", t)
    if m and m.group(1).strip() in CLI_AGENTS:
        argv = CLI_AGENTS[m.group(1).strip()]
        if _is_terminal(ctx, profiles):
            return _make_plan(utterance, [Step(Action.TERMINAL, {"command": " ".join(argv)},
                                              tier=Tier.APP, description=f"run {argv[0]}")])
        return _make_plan(utterance, [Step(Action.LAUNCH_APP,
                                          {"app": "foot", "argv": [*TERMINAL_LAUNCH, *argv]},
                                          tier=Tier.APP, description=f"launch {argv[0]}")])
    return None


def _generic_app_names(profiles: dict) -> set[str]:
    """Reuse the decision head's "too generic to be an app name" guard."""
    try:
        from .decide_candidates import _generic_aliases
        return _generic_aliases(profiles)
    except Exception:  # noqa: BLE001 - never let the guard break routing
        return set()


def _claim_app_target(name: str, profiles: dict):
    """Resolve a leading ``<app>`` for a targeted command, or None.

    Generic/ambiguous aliases ("media", "editor", "music", ...) are never
    claimed, so ``type ok`` / ``press enter`` keep their focused behaviour.
    Uses the canonical :func:`profiles.resolve`, so a generated keyword alias
    cannot shadow an explicit CLI-agent name ("codex"); a CLI agent with no GUI
    profile is still an explicit target.
    """
    if not name:
        return None
    n = normalize(name)
    if not n:
        return None
    if profiles and n in _generic_app_names(profiles):
        return None
    from .profiles import AppProfile, resolve as _profiles_resolve
    prof = _profiles_resolve(n, profiles) if profiles else None
    if prof is not None:
        return prof
    if n in CLI_AGENTS:
        return AppProfile(id=n, name=n, generated=False)
    return None


def _app_target(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    """Target-first app commands: ``<app> type|write ...`` / ``<app> press|hit|send ...``.

    Runs before the generic ``_type``/``_key`` matchers so the app is captured.
    A ``window_id`` is never set at plan time: the executor resolves the target
    from the live compositor list (which may only *select* a known window).
    """
    m = re.match(r"^(.+?)\s+(type|write)\s+(.+)$", raw, re.I | re.S)
    if m:
        prof = _claim_app_target(m.group(1), profiles)
        if prof is not None:
            text = re.sub(r'^["\']|["\']$', "", m.group(3).strip())
            return _make_plan(utterance, [Step(Action.TYPE_TEXT, {"text": text, "app": prof.id},
                                              tier=Tier.APP,
                                              description=f"type {text!r} in {prof.name}")])
    m = re.match(r"^(.+?)\s+(press|hit|send)\s+(.+)$", raw, re.I | re.S)
    if m:
        prof = _claim_app_target(m.group(1), profiles)
        if prof is not None:
            token = m.group(3).strip()
            chord = _COMMON_KEYS.get(token.lower(), token)
            return _make_plan(utterance, [Step(Action.KEY, {"chord": chord, "app": prof.id},
                                              tier=Tier.KEYBOARD,
                                              description=f"press {chord} in {prof.name}")])
    # ``<app> <media command>`` (e.g. "spotify pause"). Try the longest app name
    # first so multi-word profiles still match.
    parts = t.split()
    for i in range(len(parts) - 1, 0, -1):
        rest = " ".join(parts[i:])
        if rest in MEDIA_MAP:
            prof = _claim_app_target(" ".join(parts[:i]), profiles)
            if prof is not None:
                return _make_plan(utterance, [Step(Action.MEDIA, {"command": MEDIA_MAP[rest], "app": prof.id},
                                                  tier=Tier.APP,
                                                  description=f"{rest} in {prof.name}")])
            break
    return None


def _terminal(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^(?:run|execute|terminal run)\s+(?:command\s+)?(.+)$", raw, re.I | re.S)
    if m and _is_terminal(ctx, profiles):
        cmd = re.sub(r'^["\']|["\']$', "", m.group(1).strip())
        return _make_plan(utterance, [Step(Action.TERMINAL, {"command": cmd}, tier=Tier.APP,
                                           description=f"run {cmd}")])
    if t in ("clear", "clear terminal", "clear screen") and _is_terminal(ctx, profiles):
        return _make_plan(utterance, [Step(Action.TERMINAL, {"command": "clear"}, tier=Tier.APP,
                                           description="clear")])
    return None


def _comfy(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    if t in ("launch comfy", "launch comfyui", "launch comfy ui", "start comfy",
             "start comfyui", "start comfy ui", "boot comfy"):
        return _make_plan(utterance, [Step(Action.LAUNCH_APP,
                                          {"app": "foot", "argv": ["foot", "-e", COMFY_LAUNCH]},
                                          tier=Tier.APP,
                                          description="start ComfyUI (git pull, deps, start.sh)")])
    if t in ("open comfyui", "open comfy ui", "comfyui", "comfy ui", "comfy"):
        return _make_plan(utterance, [Step(Action.ENSURE_URL, {"url": COMFY_URL, "site": "comfyui"},
                                          tier=Tier.APP, description="open ComfyUI")])
    if t in ("queue prompt", "generate image", "run workflow") and "comfy" in ctx.focused_title.lower():
        return _make_plan(utterance, [Step(Action.CLICK_ELEMENT, {"description": "Queue Prompt"},
                                           tier=Tier.VISION, description="queue prompt")],
                          confidence=0.7, needs=True)
    return None


def _open(utterance: str, t: str, raw: str, ctx: Context, profiles: dict):
    m = re.match(r"^(?:open|go to|navigate to|visit)\s+(.+)$", t)
    if not m:
        return None
    target = m.group(1).strip()
    target = re.sub(r"\s+in a (new tab|new window)$", "", target, flags=re.I)
    target = re.sub(r"\s+(new tab|new window)$", "", target, flags=re.I)
    tl = target.lower()
    if URL_RE.match(target):
        url = target if tl.startswith("http") else "https://" + target
        return _make_plan(utterance, [Step(Action.ENSURE_URL, {"url": url, "site": _site_key(target)},
                                          tier=Tier.APP, description=f"open {url}")])
    if DOMAIN_RE.match(target) and "." in target:
        return _make_plan(utterance, [Step(Action.ENSURE_URL,
                                          {"url": "https://" + target, "site": _site_key(target)},
                                          tier=Tier.APP, description=f"open {target}")])
    # known site?
    if tl in SITES:
        return _make_plan(utterance, [Step(Action.ENSURE_URL, {"url": SITES[tl], "site": tl},
                                          tier=Tier.APP, description=f"open {tl}")])
    # installed app?
    prof = profiles.get(tl) or _resolve(profiles, tl)
    if prof:
        return _make_plan(utterance, [Step(Action.ENSURE_APP, {"app": prof.id,
                                                              "argv": getattr(prof, "launch", None)},
                                          tier=Tier.APP, description=f"open {prof.name}")])
    # unknown -> nothing cheap; escalate
    return _ESCALATE


def _site(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^(?:switch to|focus|go to app|show)\s+(.+)$", t)
    if m:
        tgt = m.group(1).strip()
        if tgt in SITES:
            return _make_plan(utterance, [Step(Action.ENSURE_URL, {"url": SITES[tgt], "site": tgt},
                                              tier=Tier.APP, description=f"switch to {tgt}")])
        prof = _resolve(profiles, tgt)
        if prof:
            return _make_plan(utterance, [Step(Action.ENSURE_APP,
                                              {"app": prof.id, "argv": getattr(prof, "launch", None)},
                                              tier=Tier.APP, description=f"focus {prof.name}")])
    return None


def _close(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^close\s+(.+)$", t)
    if not m:
        return None
    tgt = m.group(1).strip()
    if tgt in SITES:
        # Sites still use the focus-then-close pair (the target is a browser tab).
        return _make_plan(utterance, [
            Step(Action.ENSURE_URL, {"url": SITES[tgt], "site": tgt}, tier=Tier.APP,
                 description=f"focus {tgt}"),
            Step(Action.NIRI, {"command": "close-window", "args": []},
                 tier=Tier.APP, description="close window"),
        ])
    prof = _claim_app_target(tgt, profiles)
    if prof is not None:
        return _make_plan(utterance, [Step(Action.CLOSE_APP, {"app": prof.id}, tier=Tier.APP,
                                          description=f"close {prof.name}")])
    if tgt in ("window", "tab"):
        return _make_plan(utterance, [Step(Action.NIRI, {"command": "close-window", "args": []},
                                          tier=Tier.APP, description="close window")])
    return None


def _search(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    browser = _is_browser(ctx, profiles)
    # site-specific first: "search youtube for lofi"
    m = re.match(r"^(?:search|look up)\s+(.+?)\s+for\s+(.+)$", raw, re.I)
    if m and m.group(1).strip().lower() in SITE_SEARCH:
        site, q = m.group(1).strip().lower(), m.group(2).strip()
        q = re.sub(r"[.!?]+$", "", q).strip()
        return _make_plan(utterance, [Step(Action.OPEN_URL,
                                          {"url": SITE_SEARCH[site].format(q=q.replace(' ', '+'))},
                                          tier=Tier.APP, description=f"search {site} for {q}")])

    # generic: "search for X" / "google X"
    m = re.match(r"^(?:search(?: the web)?|google|look up)\s+(?:for\s+)?(.+)$", raw, re.I)
    if m:
        q = re.sub(r"^(?:for|about)\s+", "", m.group(1).strip(), flags=re.I)
        q = re.sub(r"[.!?]+$", "", q).strip()
        if browser:
            prof = profiles.get(ctx.focused_app)
            search_url = getattr(prof, "search_url", None) if prof else None
            template = search_url or "https://www.google.com/search?q={q}"
            return _make_plan(utterance, [Step(Action.OPEN_URL,
                                              {"url": template.format(q=q.replace(' ', '+'))},
                                              tier=Tier.APP, description=f"search {q}")])
        return _make_plan(utterance, [Step(Action.OPEN_URL,
                                          {"url": f"https://www.google.com/search?q={q.replace(' ', '+')}"},
                                          tier=Tier.APP, description=f"search {q}")])
    return None


_APP_SHORTCUTS = {
    "new tab": "new_tab",
    "close tab": "close_tab",
    "reload": "reload",
    "refresh": "reload",
    "go back": "back",
    "back": "back",
    "go forward": "forward",
    "forward": "forward",
    "address bar": "address_bar",
    "url bar": "address_bar",
    "focus address bar": "address_bar",
    "reopen tab": "reopen_tab",
    "restore tab": "reopen_tab",
    "find on page": "find",
    "next tab": "next_tab",
    "previous tab": "prev_tab",
}

_EDITING = {
    "copy": "ctrl+c", "paste": "ctrl+v", "cut": "ctrl+x",
    "undo": "ctrl+z", "redo": "ctrl+shift+z",
    "select all": "ctrl+a", "save": "ctrl+s",
}


def _shortcut(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    browser = _is_browser(ctx, profiles)
    if t in _APP_SHORTCUTS and browser:
        step = _shortcut_step(ctx, profiles, _APP_SHORTCUTS[t])
        if step:
            return _make_plan(utterance, [step])
    return None


def _key(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^(?:press|hit|type key)\s+(.+)$", t)
    if m:
        token = m.group(1).strip()
        chord = _COMMON_KEYS.get(token, token)
        return _make_plan(utterance, [Step(Action.KEY, {"chord": chord}, tier=Tier.KEYBOARD,
                                          description=f"press {chord}")])
    return None


def _editing(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    if t in _EDITING:
        return _make_plan(utterance, [Step(Action.KEY, {"chord": _EDITING[t]}, tier=Tier.KEYBOARD,
                                          description=t)])
    return None


def _type(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^(?:type|write|enter)\s+(.+)$", raw, re.I | re.S)
    if m:
        text = m.group(1).strip()
        text = re.sub(r'^["\']|["\']$', "", text)
        return _make_plan(utterance, [Step(Action.TYPE_TEXT, {"text": text}, tier=Tier.APP,
                                          description=f"type {text!r}")])
    return None


def _scroll(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    if re.search(r"\bscroll (down|up)\b", t) or re.search(r"\bpage (down|up)\b", t):
        direction = "down" if "down" in t else "up"
        return _make_plan(utterance, [Step(Action.SCROLL, {"direction": direction, "amount": 5},
                                          tier=Tier.KEYBOARD, description=f"scroll {direction}")])
    return None


def _click(utterance: str, t: str, raw: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    m = re.match(r"^(?:click|press|tap|hit)\s+(?:on\s+)?(.+)$", t)
    if m:
        desc = m.group(1).strip()
        if desc not in _COMMON_KEYS:  # "press enter" already handled above
            return _make_plan(utterance, [Step(Action.CLICK_ELEMENT, {"description": desc},
                                              tier=Tier.VISION, description=f"click {desc}")],
                              confidence=0.6, needs=True)
    return None


_MATCHERS = (
    _custom,     # custom per-app command phrases
    _niri,       # compositor actions
    _media,      # MPRIS media control
    _cli_agent,  # CLI agents (claude/codex/...) in a terminal
    _app_target, # app-targeted type/press/media ("codex type ok")
    _terminal,   # run/clear a shell command in the focused terminal
    _comfy,      # ComfyUI launch/open/queue
    _open,       # explicit open URL / domain / site / app
    _site,       # switch/focus app or site
    _close,      # focus then close a window
    _search,     # site-specific then generic web search
    _shortcut,   # browser keyboard shortcuts
    _key,        # generic key presses
    _editing,    # copy/paste/undo/save shortcuts
    _type,       # dictated text
    _scroll,     # scroll/page
    _click,      # click by description (needs perception)
)


def plan(utterance: str, ctx: Context, profiles: dict) -> Optional[Plan]:
    """Return the deterministic Plan for an utterance, or None to escalate.

    Walks the ordered matcher chain (first match wins); returns None when the
    command needs accessibility/vision. Keep this fast and predictable.
    """
    t = normalize(utterance)
    raw = utterance.strip()
    if not t:
        return None
    for matcher in _MATCHERS:
        result = matcher(utterance, t, raw, ctx, profiles)
        if result is _ESCALATE:
            return None
        if result is not None:
            return result
    return None



def _site_key(text: str) -> str:
    """Best keyword to match a site against a browser window title."""
    t = (text or "").lower()
    for host in SITES:
        if host in t:
            return host
    from urllib.parse import urlparse
    try:
        host = urlparse(t if "://" in t else "https://" + t).netloc.split(":")[0]
    except Exception:
        return t
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


def _resolve(profiles: dict, name: str):
    """Resolve an app by id/name/alias. Mirrors router.profiles.resolve but defensive."""
    name = normalize(name)
    for pid, prof in profiles.items():
        if normalize(pid) == name:
            return prof
        if normalize(getattr(prof, "name", "")) == name:
            return prof
        if name in [normalize(a) for a in getattr(prof, "aliases", []) or []]:
            return prof
    return None
