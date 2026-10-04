# Router / plan-accuracy evaluation corpus.
"""Scored corpus of spoken phrase -> expected deterministic Plan.

This is the data half of the router evaluation harness (see
``tests/eval/run_eval.py``). It mirrors the normalisation used by the golden
order test ``tests/router/test_rules_order.py``: each case names an utterance,
a *category* and a *context key* (mapped into the fixed contexts below), and
the exact :func:`utter.router.rules.plan` snapshot it should produce.

Everything here is hermetic: a fixed in-memory profile set, fixed contexts, no
desktop, no network, no user config. The profile set is fully enabled so the
app-gate-aware paths (custom commands, per-app shortcuts, targeted input,
media targeting) are reachable; the gate itself is covered by
``tests/router/test_app_enabled.py``.

Design notes:
- ``Context`` keys are deliberately small so a case reads as behaviour, not
  setup. Add a key only when a matcher genuinely depends on that context.
- Expected plans are *current real behaviour*, reconciled against
  ``utter/router/rules.py``. When the intended behaviour and the code disagree,
  the case is listed in :data:`KNOWN_GAPS` (scored separately, never fudged).
- Do not invent app ids: only ids in :data:`PROFILES` (or the CLI-agent names
  in ``utter/data/cli_agents.json``) appear as targets.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from utter.router.profiles import AppProfile  # noqa: E402
from utter.types import Context, FocusedWindow  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parents[2]
COMFY_LAUNCH = str(_REPO / "scripts" / "start-comfyui.sh")
COMFY_URL = "http://127.0.0.1:8188"


# --- fixed profiles ---------------------------------------------------------
# All enabled: routing consumes this dict directly; the opt-in gate is applied
# by callers (``enabled_profiles``) before ``plan`` and is tested elsewhere.
FIREFOX = AppProfile(
    id="firefox",
    name="Firefox",
    kind="browser",
    aliases=["browser"],
    shortcuts={
        "new_tab": "ctrl+t",
        "close_tab": "ctrl+w",
        "reload": "F5",
        "back": "alt+Left",
        "forward": "alt+Right",
        "address_bar": "ctrl+l",
        "reopen_tab": "ctrl+shift+t",
        "find": "ctrl+f",
        "next_tab": "ctrl+Tab",
        "prev_tab": "ctrl+shift+Tab",
    },
    commands={"open youtube": "ctrl+y"},
    search_url="https://duckduckgo.com/?q={q}",
    enabled=True,
)
ZEN = AppProfile(
    id="zen",
    name="Zen",
    kind="browser",
    aliases=["zen"],
    shortcuts={
        "new_tab": "ctrl+t",
        "close_tab": "ctrl+w",
        "reload": "F5",
        "back": "alt+Left",
    },
    search_url="https://search.brave.com/search?q={q}",
    enabled=True,
)
FOOT = AppProfile(id="foot", name="Foot", kind="terminal", enabled=True)
CODE = AppProfile(id="code", name="Code", kind="editor", aliases=["vscode"],
                  enabled=True)
SPOTIFY = AppProfile(id="spotify", name="Spotify", aliases=["spotify"],
                     enabled=True)
STEAM = AppProfile(id="steam", name="Steam", aliases=["steam"],
                   app_ids=["steam", "Steam"], enabled=True)

PROFILES = {
    "firefox": FIREFOX,
    "zen": ZEN,
    "foot": FOOT,
    "code": CODE,
    "spotify": SPOTIFY,
    "steam": STEAM,
}


# --- fixed contexts ---------------------------------------------------------
CONTEXTS = {
    "none": Context(focused=None),
    "browser": Context(focused=FocusedWindow(app_id="firefox", title="GitHub")),
    "zen": Context(focused=FocusedWindow(app_id="zen", title="Start Page")),
    "terminal": Context(focused=FocusedWindow(app_id="foot", title="~")),
    "code": Context(focused=FocusedWindow(app_id="code", title="main.py")),
    "spotify": Context(focused=FocusedWindow(app_id="spotify", title="Spotify")),
    "comfy": Context(focused=FocusedWindow(app_id="zen", title="ComfyUI - workflow")),
}


# --- normalisation (identical to tests/router/test_rules_order.py) ----------
def snapshot(plan):
    """Normalise a Plan to plain data for exact comparison."""
    if plan is None:
        return None
    return {
        "source": plan.source,
        "confidence": plan.confidence,
        "needs_perception": plan.needs_perception,
        "steps": [
            {"action": s.action.value, "args": s.args, "tier": s.tier.value,
             "description": s.description}
            for s in plan.steps
        ],
    }


def step(action, args, tier, description):
    return {"action": action, "args": args, "tier": tier, "description": description}


def plan_of(*steps, source="rules", confidence=1.0, needs=False):
    return {"source": source, "confidence": confidence, "needs_perception": needs,
            "steps": list(steps)}


def niri(command, phrase, args=None):
    return step("niri", {"command": command, "args": list(args or [])}, "app", phrase)


def url(target, site, desc):
    return step("ensure_url", {"url": target, "site": site}, "app", desc)


def app(target, desc, argv=None):
    return step("ensure_app", {"app": target, "argv": list(argv or [])}, "app", desc)


def key(chord, desc=None):
    return step("key", {"chord": chord}, "keyboard", desc or f"press {chord}")


# (name, category, utterance, context_key, expected snapshot)
CASES = [
    # ===================================================================== #
    # custom_commands: per-app command phrases run first and beat built-ins
    # ===================================================================== #
    ("custom_beats_open", "custom_commands", "Open YouTube!", "browser",
     plan_of(key("ctrl+y", "custom command: open youtube"))),
    ("custom_normalises_punctuation", "custom_commands", "open youtube.", "browser",
     plan_of(key("ctrl+y", "custom command: open youtube"))),
    ("custom_upper_case", "custom_commands", "OPEN YOUTUBE", "browser",
     plan_of(key("ctrl+y", "custom command: open youtube"))),
    ("custom_only_when_focused", "custom_commands", "open youtube", "code",
     plan_of(url("https://www.youtube.com", "youtube", "open youtube"))),
    ("custom_absent_when_unfocused", "custom_commands", "open youtube", "none",
     plan_of(url("https://www.youtube.com", "youtube", "open youtube"))),

    # ===================================================================== #
    # niri: compositor actions (curated + generated phrases)
    # ===================================================================== #
    ("niri_focus_left", "niri", "focus left", "browser", plan_of(niri("focus-column-left", "focus left"))),
    ("niri_focus_right", "niri", "focus right", "browser", plan_of(niri("focus-column-right", "focus right"))),
    ("niri_focus_up", "niri", "focus up", "browser", plan_of(niri("focus-window-up", "focus up"))),
    ("niri_focus_down", "niri", "focus down", "browser", plan_of(niri("focus-window-down", "focus down"))),
    ("niri_next_column", "niri", "next column", "browser", plan_of(niri("focus-column-right", "next column"))),
    ("niri_previous_column", "niri", "previous column", "browser", plan_of(niri("focus-column-left", "previous column"))),
    ("niri_first_column", "niri", "first column", "browser", plan_of(niri("focus-column-first", "first column"))),
    ("niri_last_column", "niri", "last column", "browser", plan_of(niri("focus-column-last", "last column"))),
    ("niri_move_window_left", "niri", "move window left", "browser", plan_of(niri("move-column-left", "move window left"))),
    ("niri_move_window_right", "niri", "move window right", "browser", plan_of(niri("move-column-right", "move window right"))),
    ("niri_move_window_up", "niri", "move window up", "browser", plan_of(niri("move-window-up", "move window up"))),
    ("niri_move_window_down", "niri", "move window down", "browser", plan_of(niri("move-window-down", "move window down"))),
    ("niri_close_window", "niri", "close window", "browser", plan_of(niri("close-window", "close window"))),
    ("niri_fullscreen", "niri", "fullscreen", "browser", plan_of(niri("fullscreen-window", "fullscreen"))),
    ("niri_toggle_fullscreen", "niri", "toggle fullscreen", "browser", plan_of(niri("fullscreen-window", "toggle fullscreen"))),
    ("niri_maximize_column", "niri", "maximize column", "browser", plan_of(niri("maximize-column", "maximize column"))),
    ("niri_expand_column", "niri", "expand column", "browser", plan_of(niri("expand-column-to-available-width", "expand column"))),
    ("niri_center_column", "niri", "center column", "browser", plan_of(niri("center-column", "center column"))),
    ("niri_center_window", "niri", "center window", "browser", plan_of(niri("center-window", "center window"))),
    ("niri_toggle_floating", "niri", "toggle floating", "browser", plan_of(niri("toggle-window-floating", "toggle floating"))),
    ("niri_float_window", "niri", "float window", "browser", plan_of(niri("toggle-window-floating", "float window"))),
    ("niri_minimize_window", "niri", "minimize window", "browser", plan_of(niri("minimize-window", "minimize window"))),
    ("niri_next_workspace", "niri", "next workspace", "browser", plan_of(niri("focus-workspace-down", "next workspace"))),
    ("niri_previous_workspace", "niri", "previous workspace", "browser", plan_of(niri("focus-workspace-up", "previous workspace"))),
    ("niri_next_monitor", "niri", "next monitor", "browser", plan_of(niri("focus-monitor-next", "next monitor"))),
    ("niri_previous_monitor", "niri", "previous monitor", "browser", plan_of(niri("focus-monitor-previous", "previous monitor"))),
    ("niri_focus_monitor_left", "niri", "focus monitor left", "browser", plan_of(niri("focus-monitor-left", "focus monitor left"))),
    ("niri_focus_monitor_right", "niri", "focus monitor right", "browser", plan_of(niri("focus-monitor-right", "focus monitor right"))),
    ("niri_move_next_monitor", "niri", "move to next monitor", "browser", plan_of(niri("move-window-to-monitor-next", "move to next monitor"))),
    ("niri_move_previous_monitor", "niri", "move to previous monitor", "browser", plan_of(niri("move-window-to-monitor-previous", "move to previous monitor"))),
    ("niri_overview", "niri", "overview", "browser", plan_of(niri("toggle-overview", "overview"))),
    ("niri_open_overview", "niri", "open overview", "browser", plan_of(niri("open-overview", "open overview"))),
    ("niri_close_overview", "niri", "close overview", "browser", plan_of(niri("close-overview", "close overview"))),
    ("niri_take_screenshot", "niri", "take screenshot", "browser", plan_of(niri("screenshot-screen", "take screenshot"))),
    ("niri_screenshot", "niri", "screenshot", "browser", plan_of(niri("screenshot-screen", "screenshot"))),
    ("niri_toggle_tabbed", "niri", "toggle tabbed", "browser", plan_of(niri("toggle-column-tabbed-display", "toggle tabbed"))),
    ("niri_tabbed_column", "niri", "tabbed column", "browser", plan_of(niri("toggle-column-tabbed-display", "tabbed column"))),
    ("niri_workspace_3", "niri", "workspace 3", "browser", plan_of(niri("focus-workspace", "workspace 3", [3]))),
    ("niri_go_to_workspace_2", "niri", "go to workspace 2", "browser", plan_of(niri("focus-workspace", "go to workspace 2", [2]))),
    ("niri_switch_to_workspace_5", "niri", "switch to workspace 5", "browser", plan_of(niri("focus-workspace", "switch to workspace 5", [5]))),
    ("niri_move_window_to_workspace_2", "niri", "move window to workspace 2", "browser", plan_of(niri("move-window-to-workspace", "move window to workspace 2", [2]))),
    ("niri_move_column_to_workspace_4", "niri", "move column to workspace 4", "browser", plan_of(niri("move-window-to-workspace", "move column to workspace 4", [4]))),
    ("niri_move_to_left", "niri", "move to left", "browser", plan_of(niri("move-window-to-monitor-left", "move to left"))),
    ("niri_move_to_monitor_right", "niri", "move to monitor right", "browser", plan_of(niri("move-column-to-monitor-right", "move to monitor right"))),
    ("niri_generated_focus_column_left", "niri", "focus column left", "browser", plan_of(niri("focus-column-left", "focus column left"))),
    ("niri_generated_go_left", "niri", "go left", "browser", plan_of(niri("focus-column-left", "go left"))),
    ("niri_generated_shift_left", "niri", "shift left", "browser", plan_of(niri("move-column-left", "shift left"))),
    ("niri_generated_next_window", "niri", "next window", "browser", plan_of(niri("next-window", "next window"))),
    ("niri_generated_screenshot_window", "niri", "screenshot window", "browser", plan_of(niri("screenshot-window", "screenshot window"))),
    ("niri_generated_capture_window", "niri", "capture window", "browser", plan_of(niri("screenshot-window", "capture window"))),
    ("niri_generated_screenshot_region", "niri", "screenshot region", "browser", plan_of(niri("screenshot", "screenshot region"))),
    ("niri_generated_focus_monitor", "niri", "focus monitor", "browser", plan_of(niri("focus-monitor", "focus monitor"))),
    ("niri_generated_spawn", "niri", "spawn", "browser", plan_of(niri("spawn", "spawn"))),
    ("niri_generated_quit", "niri", "quit", "browser", plan_of(niri("quit", "quit"))),
    ("niri_generated_close", "niri", "close", "browser", plan_of(niri("close-window", "close"))),

    # ===================================================================== #
    # media: MPRIS transport (app-agnostic) and per-app targeting
    # ===================================================================== #
    ("media_play", "media", "play", "none", plan_of(step("media", {"command": "play"}, "app", "play"))),
    ("media_pause", "media", "pause", "none", plan_of(step("media", {"command": "pause"}, "app", "pause"))),
    ("media_resume", "media", "resume", "none", plan_of(step("media", {"command": "play"}, "app", "resume"))),
    ("media_play_pause", "media", "play pause", "none", plan_of(step("media", {"command": "play-pause"}, "app", "play pause"))),
    ("media_toggle_play", "media", "toggle play", "none", plan_of(step("media", {"command": "play-pause"}, "app", "toggle play"))),
    ("media_next", "media", "next", "none", plan_of(step("media", {"command": "next"}, "app", "next"))),
    ("media_next_track", "media", "next track", "none", plan_of(step("media", {"command": "next"}, "app", "next track"))),
    ("media_next_song", "media", "next song", "none", plan_of(step("media", {"command": "next"}, "app", "next song"))),
    ("media_next_episode", "media", "next episode", "none", plan_of(step("media", {"command": "next"}, "app", "next episode"))),
    ("media_skip", "media", "skip", "none", plan_of(step("media", {"command": "next"}, "app", "skip"))),
    ("media_previous", "media", "previous", "none", plan_of(step("media", {"command": "previous"}, "app", "previous"))),
    ("media_previous_track", "media", "previous track", "none", plan_of(step("media", {"command": "previous"}, "app", "previous track"))),
    ("media_skip_back", "media", "skip back", "none", plan_of(step("media", {"command": "previous"}, "app", "skip back"))),
    ("media_stop", "media", "stop", "none", plan_of(step("media", {"command": "stop"}, "app", "stop"))),
    ("media_stop_playback", "media", "stop playback", "none", plan_of(step("media", {"command": "stop"}, "app", "stop playback"))),
    ("media_target_spotify_pause", "media", "spotify pause", "none",
     plan_of(step("media", {"command": "pause", "app": "spotify"}, "app", "pause in Spotify"))),
    ("media_target_spotify_next", "media", "spotify next", "none",
     plan_of(step("media", {"command": "next", "app": "spotify"}, "app", "next in Spotify"))),
    ("media_target_spotify_stop", "media", "spotify stop", "none",
     plan_of(step("media", {"command": "stop", "app": "spotify"}, "app", "stop in Spotify"))),
    ("media_target_steam_play", "media", "steam play", "none",
     plan_of(step("media", {"command": "play", "app": "steam"}, "app", "play in Steam"))),

    # ===================================================================== #
    # cli_agents: launch/run known coding agents
    # ===================================================================== #
    ("cli_claude_in_terminal", "cli_agents", "open claude code", "terminal",
     plan_of(step("terminal", {"command": "claude"}, "app", "run claude"))),
    ("cli_claude_launches", "cli_agents", "open claude code", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "claude"]}, "app", "launch claude"))),
    ("cli_codex_launch", "cli_agents", "launch codex", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "codex"]}, "app", "launch codex"))),
    ("cli_codex_in_terminal", "cli_agents", "launch codex", "terminal",
     plan_of(step("terminal", {"command": "codex"}, "app", "run codex"))),
    ("cli_opencode_launch", "cli_agents", "start opencode", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "opencode"]}, "app", "launch opencode"))),
    ("cli_opencode_in_terminal", "cli_agents", "run opencode", "terminal",
     plan_of(step("terminal", {"command": "opencode"}, "app", "run opencode"))),
    ("cli_grok_launch", "cli_agents", "open grok", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "grok"]}, "app", "launch grok"))),
    ("cli_grok_bot_launch", "cli_agents", "launch grok bot", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "grok"]}, "app", "launch grok"))),
    ("cli_cursor_agent_launch", "cli_agents", "open cursor agent", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "cursor-agent"]}, "app", "launch cursor-agent"))),
    ("cli_spawn_opencode", "cli_agents", "spawn opencode", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "opencode"]}, "app", "launch opencode"))),
    ("cli_claude_browser_launches", "cli_agents", "open claude code", "browser",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", "claude"]}, "app", "launch claude"))),

    # ===================================================================== #
    # terminal: run/clear only inside a focused terminal
    # ===================================================================== #
    ("terminal_run", "terminal", "run echo hello", "terminal",
     plan_of(step("terminal", {"command": "echo hello"}, "app", "run echo hello"))),
    ("terminal_execute", "terminal", "execute ls -la", "terminal",
     plan_of(step("terminal", {"command": "ls -la"}, "app", "run ls -la"))),
    ("terminal_run_prefix", "terminal", "terminal run uptime", "terminal",
     plan_of(step("terminal", {"command": "uptime"}, "app", "run uptime"))),
    ("terminal_run_command_word", "terminal", "run command git status", "terminal",
     plan_of(step("terminal", {"command": "git status"}, "app", "run git status"))),
    ("terminal_run_double_quotes", "terminal", "run \"npm test\"", "terminal",
     plan_of(step("terminal", {"command": "npm test"}, "app", "run npm test"))),
    ("terminal_run_single_quotes", "terminal", "run 'pwd'", "terminal",
     plan_of(step("terminal", {"command": "pwd"}, "app", "run pwd"))),
    ("terminal_clear", "terminal", "clear terminal", "terminal",
     plan_of(step("terminal", {"command": "clear"}, "app", "clear"))),
    ("terminal_clear_bare", "terminal", "clear", "terminal",
     plan_of(step("terminal", {"command": "clear"}, "app", "clear"))),
    ("terminal_clear_screen", "terminal", "clear screen", "terminal",
     plan_of(step("terminal", {"command": "clear"}, "app", "clear"))),
    ("terminal_run_needs_terminal", "terminal", "run echo hello", "none", None),
    ("terminal_run_in_browser", "terminal", "run echo hello", "browser", None),
    ("terminal_clear_needs_terminal", "terminal", "clear terminal", "browser", None),
    ("terminal_clear_needs_terminal_none", "terminal", "clear terminal", "none", None),

    # ===================================================================== #
    # open_url_site_app: explicit open + switch/focus + comfy + escalation
    # ===================================================================== #
    ("open_url", "open_url_site_app", "open https://example.com/x", "none",
     plan_of(url("https://example.com/x", "example", "open https://example.com/x"))),
    ("open_domain", "open_url_site_app", "open example.com/path", "none",
     plan_of(url("https://example.com/path", "example", "open example.com/path"))),
    ("open_domain_plain", "open_url_site_app", "open test.dev", "none",
     plan_of(url("https://test.dev", "test", "open test.dev"))),
    ("open_domain_youtube_com", "open_url_site_app", "open youtube.com", "none",
     plan_of(url("https://youtube.com", "youtube", "open youtube.com"))),
    # A short SITES key ("x") must not match inside another host or path; the
    # URL/domain's own host label wins, and standalone short keys still resolve.
    ("open_domain_x_com", "open_url_site_app", "open x.com", "none",
     plan_of(url("https://x.com", "x", "open x.com"))),
    ("open_domain_netflix", "open_url_site_app", "open netflix.com", "none",
     plan_of(url("https://netflix.com", "netflix", "open netflix.com"))),
    ("open_site_yt", "open_url_site_app", "open yt", "none",
     plan_of(url("https://www.youtube.com", "yt", "open yt"))),
    ("open_site_youtube", "open_url_site_app", "open youtube", "none",
     plan_of(url("https://www.youtube.com", "youtube", "open youtube"))),
    ("open_site_github", "open_url_site_app", "open github", "none",
     plan_of(url("https://github.com", "github", "open github"))),
    ("open_site_gmail", "open_url_site_app", "open gmail", "none",
     plan_of(url("https://mail.google.com", "gmail", "open gmail"))),
    ("open_site_google", "open_url_site_app", "open google", "none",
     plan_of(url("https://www.google.com", "google", "open google"))),
    ("open_site_wikipedia", "open_url_site_app", "open wikipedia", "none",
     plan_of(url("https://en.wikipedia.org", "wikipedia", "open wikipedia"))),
    ("open_site_reddit", "open_url_site_app", "open reddit", "none",
     plan_of(url("https://www.reddit.com", "reddit", "open reddit"))),
    ("open_site_twitter", "open_url_site_app", "open twitter", "none",
     plan_of(url("https://x.com", "twitter", "open twitter"))),
    ("open_site_x", "open_url_site_app", "open x", "none",
     plan_of(url("https://x.com", "x", "open x"))),
    ("open_site_hn", "open_url_site_app", "open hn", "none",
     plan_of(url("https://news.ycombinator.com", "hn", "open hn"))),
    ("open_site_hacker_news", "open_url_site_app", "open hacker news", "none",
     plan_of(url("https://news.ycombinator.com", "hacker news", "open hacker news"))),
    ("open_site_chatgpt", "open_url_site_app", "open chatgpt", "none",
     plan_of(url("https://chatgpt.com", "chatgpt", "open chatgpt"))),
    ("open_site_maps", "open_url_site_app", "open maps", "none",
     plan_of(url("https://maps.google.com", "maps", "open maps"))),
    ("open_site_google_maps", "open_url_site_app", "open google maps", "none",
     plan_of(url("https://maps.google.com", "google maps", "open google maps"))),
    ("open_site_stackoverflow", "open_url_site_app", "open stackoverflow", "none",
     plan_of(url("https://stackoverflow.com", "stackoverflow", "open stackoverflow"))),
    ("open_site_spotify_beats_app", "open_url_site_app", "open spotify", "none",
     plan_of(url("https://open.spotify.com", "spotify", "open spotify"))),
    ("open_site_claude_beats_app", "open_url_site_app", "open claude", "none",
     plan_of(url("https://claude.ai", "claude", "open claude"))),
    ("open_site_new_tab_suffix", "open_url_site_app", "open youtube in a new tab", "none",
     plan_of(url("https://www.youtube.com", "youtube", "open youtube"))),
    ("open_app_firefox", "open_url_site_app", "open firefox", "none",
     plan_of(app("firefox", "open Firefox"))),
    ("open_app_code", "open_url_site_app", "open code", "none",
     plan_of(app("code", "open Code"))),
    ("open_app_vscode_alias", "open_url_site_app", "open vscode", "none",
     plan_of(app("code", "open Code"))),
    ("open_app_zen", "open_url_site_app", "open zen", "none",
     plan_of(app("zen", "open Zen"))),
    ("open_app_steam", "open_url_site_app", "open steam", "none",
     plan_of(app("steam", "open Steam"))),
    ("go_to_is_open", "open_url_site_app", "go to github", "none",
     plan_of(url("https://github.com", "github", "open github"))),
    ("navigate_to_is_open", "open_url_site_app", "navigate to reddit", "none",
     plan_of(url("https://www.reddit.com", "reddit", "open reddit"))),
    ("visit_domain", "open_url_site_app", "visit test.dev", "none",
     plan_of(url("https://test.dev", "test", "open test.dev"))),
    ("switch_to_app", "open_url_site_app", "switch to code", "none",
     plan_of(app("code", "focus Code"))),
    ("switch_to_site", "open_url_site_app", "switch to github", "none",
     plan_of(url("https://github.com", "github", "switch to github"))),
    ("show_is_site", "open_url_site_app", "show github", "none",
     plan_of(url("https://github.com", "github", "switch to github"))),
    ("close_site_focus_then_close", "open_url_site_app", "close github", "none",
     plan_of(url("https://github.com", "github", "focus github"),
             niri("close-window", "close window"))),
    ("close_app_steam", "open_url_site_app", "close steam", "none",
     plan_of(step("close_app", {"app": "steam"}, "app", "close Steam"))),
    ("open_unknown_escalates", "open_url_site_app", "open nonexistentapp", "none", None),
    ("open_unknown_scroll_word_still_escalates", "open_url_site_app", "open scroll down", "none", None),
    ("open_unknown_escalates_when_focused", "open_url_site_app", "open nonexistentapp", "browser", None),
    ("comfy_open", "open_url_site_app", "open comfyui", "none",
     plan_of(url(COMFY_URL, "comfyui", "open ComfyUI"))),
    ("comfy_launch", "open_url_site_app", "launch comfyui", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", COMFY_LAUNCH]},
                  "app", "start ComfyUI (git pull, deps, start.sh)"))),
    ("comfy_launch_short", "open_url_site_app", "launch comfy", "none",
     plan_of(step("launch_app", {"app": "foot", "argv": ["foot", "-e", COMFY_LAUNCH]},
                  "app", "start ComfyUI (git pull, deps, start.sh)"))),

    # ===================================================================== #
    # search: site-specific then generic; browser template when focused
    # ===================================================================== #
    ("search_site_youtube", "search", "search youtube for lofi beats", "none",
     plan_of(step("open_url", {"url": "https://www.youtube.com/results?search_query=lofi+beats"},
                  "app", "search youtube for lofi beats"))),
    ("search_site_youtube_trailing_dot", "search", "search youtube for lofi beats.", "none",
     plan_of(step("open_url", {"url": "https://www.youtube.com/results?search_query=lofi+beats"},
                  "app", "search youtube for lofi beats"))),
    ("search_site_github", "search", "search github for python", "none",
     plan_of(step("open_url", {"url": "https://github.com/search?q=python"},
                  "app", "search github for python"))),
    ("search_site_wikipedia", "search", "search wikipedia for larvaceans", "none",
     plan_of(step("open_url", {"url": "https://en.wikipedia.org/w/index.php?search=larvaceans"},
                  "app", "search wikipedia for larvaceans"))),
    ("search_site_reddit", "search", "search reddit for python", "none",
     plan_of(step("open_url", {"url": "https://www.reddit.com/search/?q=python"},
                  "app", "search reddit for python"))),
    ("search_site_amazon", "search", "search amazon for usb cable", "none",
     plan_of(step("open_url", {"url": "https://www.amazon.in/s?k=usb+cable"},
                  "app", "search amazon for usb cable"))),
    ("search_site_spotify", "search", "search spotify for lofi", "none",
     plan_of(step("open_url", {"url": "https://open.spotify.com/search/lofi"},
                  "app", "search spotify for lofi"))),
    ("search_generic", "search", "search for cats", "none",
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),
    ("search_browser_template", "search", "search for cats", "browser",
     plan_of(step("open_url", {"url": "https://duckduckgo.com/?q=cats"},
                  "app", "search cats"))),
    ("search_browser_zen_template", "search", "search for cats", "zen",
     plan_of(step("open_url", {"url": "https://search.brave.com/search?q=cats"},
                  "app", "search cats"))),
    ("search_google_verb", "search", "google cats", "none",
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),
    ("search_google_for", "search", "google for cats", "none",
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),
    ("search_look_up", "search", "look up cats", "none",
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),
    ("search_the_web", "search", "search the web for cats", "none",
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),
    ("search_implicit", "search", "search cats", "none",
     plan_of(step("open_url", {"url": "https://www.google.com/search?q=cats"},
                  "app", "search cats"))),

    # ===================================================================== #
    # shortcuts: per-app browser keyboard shortcuts (T2)
    # ===================================================================== #
    ("shortcut_new_tab", "shortcuts", "new tab", "browser",
     plan_of(key("ctrl+t", "new_tab in firefox"))),
    ("shortcut_reload", "shortcuts", "reload", "browser",
     plan_of(key("F5", "reload in firefox"))),
    ("shortcut_refresh", "shortcuts", "refresh", "browser",
     plan_of(key("F5", "reload in firefox"))),
    ("shortcut_go_back", "shortcuts", "go back", "browser",
     plan_of(key("alt+Left", "back in firefox"))),
    ("shortcut_back", "shortcuts", "back", "browser",
     plan_of(key("alt+Left", "back in firefox"))),
    ("shortcut_go_forward", "shortcuts", "go forward", "browser",
     plan_of(key("alt+Right", "forward in firefox"))),
    ("shortcut_forward", "shortcuts", "forward", "browser",
     plan_of(key("alt+Right", "forward in firefox"))),
    ("shortcut_address_bar", "shortcuts", "address bar", "browser",
     plan_of(key("ctrl+l", "address_bar in firefox"))),
    ("shortcut_url_bar", "shortcuts", "url bar", "browser",
     plan_of(key("ctrl+l", "address_bar in firefox"))),
    ("shortcut_focus_address_bar", "shortcuts", "focus address bar", "browser",
     plan_of(key("ctrl+l", "address_bar in firefox"))),
    ("shortcut_reopen_tab", "shortcuts", "reopen tab", "browser",
     plan_of(key("ctrl+shift+t", "reopen_tab in firefox"))),
    ("shortcut_restore_tab", "shortcuts", "restore tab", "browser",
     plan_of(key("ctrl+shift+t", "reopen_tab in firefox"))),
    ("shortcut_find_on_page", "shortcuts", "find on page", "browser",
     plan_of(key("ctrl+f", "find in firefox"))),
    ("shortcut_next_tab", "shortcuts", "next tab", "browser",
     plan_of(key("ctrl+Tab", "next_tab in firefox"))),
    ("shortcut_previous_tab", "shortcuts", "previous tab", "browser",
     plan_of(key("ctrl+shift+Tab", "prev_tab in firefox"))),
    ("shortcut_new_tab_zen", "shortcuts", "new tab", "zen",
     plan_of(key("ctrl+t", "new_tab in zen"))),
    ("shortcut_close_tab", "shortcuts", "close tab", "browser",
     plan_of(key("ctrl+w", "close_tab in firefox"))),
    ("shortcut_close_tab_zen", "shortcuts", "close tab", "zen",
     plan_of(key("ctrl+w", "close_tab in zen"))),
    ("shortcut_needs_browser", "shortcuts", "new tab", "none", None),
    ("shortcut_needs_browser_terminal", "shortcuts", "new tab", "terminal", None),

    # ===================================================================== #
    # keys_editing: generic keys + editing chords
    # ===================================================================== #
    ("key_enter", "keys_editing", "press enter", "none", plan_of(key("Return"))),
    ("key_return", "keys_editing", "press return", "none", plan_of(key("Return"))),
    ("key_escape", "keys_editing", "press escape", "none", plan_of(key("Escape"))),
    ("key_esc", "keys_editing", "press esc", "none", plan_of(key("Escape"))),
    ("key_tab", "keys_editing", "press tab", "none", plan_of(key("Tab"))),
    ("key_space", "keys_editing", "press space", "none", plan_of(key("space"))),
    ("key_backspace", "keys_editing", "press backspace", "none", plan_of(key("BackSpace"))),
    ("key_delete", "keys_editing", "press delete", "none", plan_of(key("Delete"))),
    ("key_up", "keys_editing", "press up", "none", plan_of(key("Up"))),
    ("key_down", "keys_editing", "press down", "none", plan_of(key("Down"))),
    ("key_left", "keys_editing", "press left", "none", plan_of(key("Left"))),
    ("key_right", "keys_editing", "press right", "none", plan_of(key("Right"))),
    ("key_f5", "keys_editing", "press f5", "none", plan_of(key("f5"))),
    ("key_letter", "keys_editing", "press a", "none", plan_of(key("a"))),
    ("key_hit_enter", "keys_editing", "hit enter", "none", plan_of(key("Return"))),
    ("key_type_key_enter", "keys_editing", "type key enter", "none", plan_of(key("Return"))),
    ("editing_copy", "keys_editing", "copy", "none", plan_of(key("ctrl+c", "copy"))),
    ("editing_paste", "keys_editing", "paste", "none", plan_of(key("ctrl+v", "paste"))),
    ("editing_cut", "keys_editing", "cut", "none", plan_of(key("ctrl+x", "cut"))),
    ("editing_undo", "keys_editing", "undo", "none", plan_of(key("ctrl+z", "undo"))),
    ("editing_redo", "keys_editing", "redo", "none", plan_of(key("ctrl+shift+z", "redo"))),
    ("editing_select_all", "keys_editing", "select all", "none", plan_of(key("ctrl+a", "select all"))),
    ("editing_save", "keys_editing", "save", "none", plan_of(key("ctrl+s", "save"))),

    # ===================================================================== #
    # typing_scroll: dictated text, app-targeted input, scroll/page
    # ===================================================================== #
    ("type_text", "typing_scroll", "type hello world", "none",
     plan_of(step("type_text", {"text": "hello world"}, "app", "type 'hello world'"))),
    ("write_text", "typing_scroll", "write hello world", "none",
     plan_of(step("type_text", {"text": "hello world"}, "app", "type 'hello world'"))),
    ("enter_text", "typing_scroll", "enter hello world", "none",
     plan_of(step("type_text", {"text": "hello world"}, "app", "type 'hello world'"))),
    ("type_double_quoted", "typing_scroll", "type \"hello world\"", "none",
     plan_of(step("type_text", {"text": "hello world"}, "app", "type 'hello world'"))),
    ("type_single_quoted", "typing_scroll", "type 'hello world'", "none",
     plan_of(step("type_text", {"text": "hello world"}, "app", "type 'hello world'"))),
    ("type_symbols", "typing_scroll", "type 2 + 2", "none",
     plan_of(step("type_text", {"text": "2 + 2"}, "app", "type '2 + 2'"))),
    ("type_stays_focused", "typing_scroll", "type ok", "code",
     plan_of(step("type_text", {"text": "ok"}, "app", "type 'ok'"))),
    ("app_target_type_codex", "typing_scroll", "codex type ok", "none",
     plan_of(step("type_text", {"text": "ok", "app": "codex"}, "app", "type 'ok' in codex"))),
    ("app_target_write_codex", "typing_scroll", "codex write hello", "none",
     plan_of(step("type_text", {"text": "hello", "app": "codex"}, "app", "type 'hello' in codex"))),
    ("app_target_press_codex", "typing_scroll", "codex press enter", "none",
     plan_of(step("key", {"chord": "Return", "app": "codex"}, "keyboard", "press Return in codex"))),
    ("app_target_press_codex_raw", "typing_scroll", "codex press f5", "none",
     plan_of(step("key", {"chord": "f5", "app": "codex"}, "keyboard", "press f5 in codex"))),
    ("app_target_press_steam", "typing_scroll", "steam press enter", "none",
     plan_of(step("key", {"chord": "Return", "app": "steam"}, "keyboard", "press Return in Steam"))),
    ("scroll_down", "typing_scroll", "scroll down", "none",
     plan_of(step("scroll", {"direction": "down", "amount": 5}, "keyboard", "scroll down"))),
    ("scroll_up", "typing_scroll", "scroll up", "none",
     plan_of(step("scroll", {"direction": "up", "amount": 5}, "keyboard", "scroll up"))),
    ("page_down", "typing_scroll", "page down", "none",
     plan_of(step("scroll", {"direction": "down", "amount": 5}, "keyboard", "scroll down"))),
    ("page_up", "typing_scroll", "page up", "none",
     plan_of(step("scroll", {"direction": "up", "amount": 5}, "keyboard", "scroll up"))),
    ("scroll_down_please", "typing_scroll", "scroll down please", "none",
     plan_of(step("scroll", {"direction": "down", "amount": 5}, "keyboard", "scroll down"))),

    # ===================================================================== #
    # perception: plans that deliberately escalate to accessibility/vision
    # ===================================================================== #
    ("click_element", "perception", "click the submit button", "none",
     plan_of(step("click_element", {"description": "the submit button"}, "vision",
                  "click the submit button"), confidence=0.6, needs=True)),
    ("click_submit", "perception", "click submit", "none",
     plan_of(step("click_element", {"description": "submit"}, "vision", "click submit"),
             confidence=0.6, needs=True)),
    ("click_on_the", "perception", "click on the red button", "none",
     plan_of(step("click_element", {"description": "the red button"}, "vision",
                  "click the red button"), confidence=0.6, needs=True)),
    ("tap_link", "perception", "tap the login link", "none",
     plan_of(step("click_element", {"description": "the login link"}, "vision",
                  "click the login link"), confidence=0.6, needs=True)),
    ("click_in_browser", "perception", "click the submit button", "browser",
     plan_of(step("click_element", {"description": "the submit button"}, "vision",
                  "click the submit button"), confidence=0.6, needs=True)),
    ("comfy_queue_prompt", "perception", "queue prompt", "comfy",
     plan_of(step("click_element", {"description": "Queue Prompt"}, "vision", "queue prompt"),
             confidence=0.7, needs=True)),
    ("comfy_generate_image", "perception", "generate image", "comfy",
     plan_of(step("click_element", {"description": "Queue Prompt"}, "vision", "queue prompt"),
             confidence=0.7, needs=True)),
    ("comfy_run_workflow", "perception", "run workflow", "comfy",
     plan_of(step("click_element", {"description": "Queue Prompt"}, "vision", "queue prompt"),
             confidence=0.7, needs=True)),

    # ===================================================================== #
    # negatives: must not route (None) — false positives count against score
    # ===================================================================== #
    ("negative_empty", "negatives", "", "none", None),
    ("negative_banana", "negatives", "banana", "none", None),
    ("negative_sentence", "negatives", "the quick brown fox", "none", None),
    ("negative_please_type", "negatives", "please type hello", "none", None),
    ("negative_terminal_run_needs_terminal", "negatives", "run echo hello", "none", None),
    ("negative_shortcut_needs_browser", "negatives", "new tab", "none", None),
    # "close tab" must never fall back to closing the whole window.
    ("negative_close_tab_no_browser", "negatives", "close tab", "none", None),
    ("negative_generic_alias_music_pause", "negatives", "music pause", "none", None),
    ("negative_generic_alias_close_music", "negatives", "close music", "none", None),
    ("negative_close_code_generic_alias", "negatives", "close code", "none", None),
    ("negative_open_unknown_escalates", "negatives", "open nonexistentapp", "none", None),
    ("negative_open_unknown_scroll_word", "negatives", "open scroll down", "none", None),
    ("negative_switch_unknown", "negatives", "switch to nonexistentapp", "none", None),
    ("negative_weather", "negatives", "what is the weather today", "none", None),
    ("negative_volume", "negatives", "turn up the volume", "none", None),
    ("negative_press_alone", "negatives", "press", "none", None),
    ("negative_type_alone", "negatives", "type", "none", None),
    ("negative_scroll_alone", "negatives", "scroll", "none", None),
    ("negative_search_alone", "negatives", "search", "none", None),
    ("negative_go_to_alone", "negatives", "go to", "none", None),
    ("negative_open_alone", "negatives", "open", "none", None),
    ("negative_playback", "negatives", "playback", "none", None),
    ("negative_clear_needs_terminal", "negatives", "clear", "none", None),
    ("negative_click_word_in_middle", "negatives",
     "make the text bigger", "none", None),
]

# Cases whose *current* behaviour diverges from the intended behaviour. They are
# excluded from the accuracy threshold and reported separately. Do not delete a
# gap entry silently: if it starts passing, the harness will flag it as stale.
KNOWN_GAPS: dict[str, str] = {
    # `_open` only accepts open|go to|navigate to|visit; "launch"/"start" are
    # handled solely for CLI agents, so "launch firefox" escalates (None).
    "gap_launch_app_verb": "launch <app> is not recognised by _open",
    # _app_target tries the longest *app* prefix first and breaks after the
    # first media tail it recognises; a single-word app followed by a multi-word
    # media command ("steam play pause") therefore escalates instead of
    # targeting the app.
    "gap_app_target_multiwind_media": "app-targeted multi-word media tail escalates",
}


def gap_cases():
    """Return the known-gap cases (name, category, utterance, ctx, expected)."""
    # Kept beside KNOWN_GAPS so the desired-vs-actual split is easy to read.
    return [
        ("gap_launch_app_verb", "open_url_site_app", "launch firefox", "none",
         plan_of(app("firefox", "open Firefox"))),
        ("gap_app_target_multiwind_media", "media", "steam play pause", "none",
         plan_of(step("media", {"command": "play-pause", "app": "steam"}, "app",
                      "play pause in Steam"))),
    ]


if __name__ == "__main__":
    cats: dict[str, int] = {}
    for _n, _c, *_ in CASES:
        cats[_c] = cats.get(_c, 0) + 1
    for _name, _count in sorted(cats.items()):
        print(f"{_name}: {_count}")
    print(f"total: {len(CASES)} (+{len(gap_cases())} known gaps)")
