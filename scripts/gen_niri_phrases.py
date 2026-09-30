#!/usr/bin/env python3
"""Generate utter/data/niri_phrases.json from the user's real niri setup.

Sources (read-only):
  * ~/.config/niri/config.kdl   -- the user's actual keybinds
  * `niri msg action`           -- the full action list (live, optional)
  * utter/data/niri_actions.json -- cached actions/binds (fallback/merge)

The result maps normalised, punctuation-free spoken phrases to a niri action
and its arguments:

    {"phrases": {"focus right": {"command": "focus-column-right", "args": []}}}

Curated aliases mirror the user's keybinds.  For every action reported by
`niri msg action`, a phrase equal to the action name with dashes turned into
spaces is added automatically unless a curated phrase already claims that
exact key (curated wins).

Stdlib only.  No shell=True.  Deterministic (sorted keys).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "utter" / "data"
ACTIONS_FILE = DATA_DIR / "niri_actions.json"
OUT_FILE = DATA_DIR / "niri_phrases.json"
CONFIG_FILE = Path(
    os.environ.get("NIRI_CONFIG", "~/.config/niri/config.kdl")
).expanduser()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def normalise(phrase: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    phrase = phrase.lower()
    phrase = re.sub(r"[^a-z0-9]+", " ", phrase)
    return re.sub(r"\s+", " ", phrase).strip()


def phrases_for_action(action: str) -> str:
    return action.replace("-", " ")


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #
def read_kdl_text() -> str:
    try:
        return CONFIG_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def extract_binds_blocks(text: str) -> list[str]:
    """Return the bodies of every top-level `binds { ... }` block."""
    blocks: list[str] = []
    for match in re.finditer(r"(?m)^[ \t]*(?<![/-])binds[ \t]*\{", text):
        start = match.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        blocks.append(text[start : i - 1])
    return blocks


def parse_binds(text: str) -> list[dict]:
    """Parse `KEY { action ARGS; }` nodes out of the binds blocks.

    Only single-line bind nodes are needed here, which is what niri configs
    practically use.  Commented-out (`/-`) binds are skipped.
    """
    binds: list[dict] = []
    node_re = re.compile(
        r"(?m)^[ \t]*([A-Za-z0-9+_]+)\b[^{;]*\{\s*"
        r"([a-z][a-z0-9-]*)\b([^;]*);\s*\}"
    )
    for block in extract_binds_blocks(text):
        for key, action, raw_args in node_re.findall(block):
            binds.append(
                {
                    "key": key,
                    "action": action,
                    "args": raw_args.strip(),
                }
            )
    return binds


def read_cached_actions() -> tuple[list[str], list[dict]]:
    try:
        data = json.loads(ACTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    actions = [a for a in data.get("actions", []) if isinstance(a, str)]
    binds = [b for b in data.get("binds", []) if isinstance(b, dict)]
    return actions, binds


def query_live_actions() -> list[str]:
    """Ask niri for its action list.  Optional: absence is not an error."""
    try:
        proc = subprocess.run(
            ["niri", "msg", "action"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    # `niri msg action` prints its action list on stderr (clap usage); merge
    # both streams so it works whether or not a compositor is reachable.
    actions = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        m = re.match(r"^  ([a-z][a-z0-9-]*)$", line)
        if m:
            actions.append(m.group(1))
    return actions


# --------------------------------------------------------------------------- #
# curated phrases (mirror the user's keybinds)
# --------------------------------------------------------------------------- #
# Each entry: (phrase or list of phrases, action).
CURATED: list[tuple[str | list[str], str]] = [
    # ---- focus (Mod+arrows / Mod+HJKL) ----
    (["focus left", "go left", "focus column left"], "focus-column-left"),
    (["focus right", "go right", "focus column right"], "focus-column-right"),
    (["focus up", "go up", "focus window up"], "focus-window-up"),
    (["focus down", "go down", "focus window down"], "focus-window-down"),
    (
        ["first column", "focus first column", "go to first column"],
        "focus-column-first",
    ),
    (
        ["last column", "focus last column", "go to last column"],
        "focus-column-last",
    ),
    (["previous window", "focus previous window"], "focus-window-previous"),
    # ---- move / tile (Mod+Ctrl+arrows / HJKL) ----
    (["move left", "tile left", "shift left", "move column left"], "move-column-left"),
    (
        ["move right", "tile right", "shift right", "move column right"],
        "move-column-right",
    ),
    (["move up", "tile up", "shift up", "move window up"], "move-window-up"),
    (["move down", "tile down", "shift down", "move window down"], "move-window-down"),
    (
        ["move to first column", "send to first column"],
        "move-column-to-first",
    ),
    (
        ["move to last column", "send to last column"],
        "move-column-to-last",
    ),
    # ---- layout ----
    (["maximize", "maximize column", "maximize window"], "maximize-column"),
    (
        ["fullscreen", "full screen", "fullscreen window", "toggle fullscreen"],
        "fullscreen-window",
    ),
    (["center", "center column", "center window"], "center-column"),
    (
        ["float", "float window", "floating", "toggle floating", "toggle window floating"],
        "toggle-window-floating",
    ),
    (
        [
            "tabbed",
            "tabbed column",
            "toggle tabbed",
            "toggle column tabbed",
            "tab display",
        ],
        "toggle-column-tabbed-display",
    ),
    (
        ["consume", "consume window", "tab into column", "consume into column"],
        "consume-window-into-column",
    ),
    (
        ["expel", "expel window", "untab", "expel from column"],
        "expel-window-from-column",
    ),
    # ---- workspaces ----
    (
        ["next workspace", "workspace down", "go to next workspace"],
        "focus-workspace-down",
    ),
    (
        ["previous workspace", "workspace up", "go to previous workspace"],
        "focus-workspace-up",
    ),
    (["last used workspace"], "focus-workspace-previous"),
    (
        ["move to next workspace", "move to workspace down", "move column to next workspace"],
        "move-column-to-workspace-down",
    ),
    (
        ["move to previous workspace", "move to workspace up", "move column to previous workspace"],
        "move-column-to-workspace-up",
    ),
    (
        ["move window to next workspace", "move window to workspace down"],
        "move-window-to-workspace-down",
    ),
    (
        ["move window to previous workspace", "move window to workspace up"],
        "move-window-to-workspace-up",
    ),
    # ---- column width presets (Mod+R / Mod+Shift+R) ----
    (
        ["preset width", "cycle width", "next width", "switch width"],
        "switch-preset-column-width",
    ),
    (
        ["preset width back", "previous width", "cycle width back", "switch width back"],
        "switch-preset-column-width-back",
    ),
    (["preset height", "cycle height", "next height"], "switch-preset-window-height"),
    (
        ["preset height back", "previous height", "cycle height back"],
        "switch-preset-window-height-back",
    ),
    # ---- window / overview / screenshot ----
    (["close window", "close", "close active window"], "close-window"),
    (["overview", "toggle overview", "show overview"], "toggle-overview"),
    (
        ["screenshot", "screenshot screen", "take screenshot", "screenshot display"],
        "screenshot-screen",
    ),
    (["screenshot window", "capture window"], "screenshot-window"),
    (["screenshot area", "screenshot region", "screenshot ui"], "screenshot"),
    # ---- monitors ----
    (["focus monitor left"], "focus-monitor-left"),
    (["focus monitor right"], "focus-monitor-right"),
    (["focus monitor up"], "focus-monitor-up"),
    (["focus monitor down"], "focus-monitor-down"),
    (["next monitor", "focus next monitor"], "focus-monitor-next"),
    (["previous monitor", "focus previous monitor"], "focus-monitor-previous"),
    (["move to monitor left"], "move-column-to-monitor-left"),
    (["move to monitor right"], "move-column-to-monitor-right"),
    (["move to monitor up"], "move-column-to-monitor-up"),
    (["move to monitor down"], "move-column-to-monitor-down"),
    (["move window to monitor left"], "move-window-to-monitor-left"),
    (["move window to monitor right"], "move-window-to-monitor-right"),
    (["move window to monitor up"], "move-window-to-monitor-up"),
    (["move window to monitor down"], "move-window-to-monitor-down"),
    (["move to next monitor"], "move-column-to-monitor-next"),
    (["move to previous monitor"], "move-column-to-monitor-previous"),
    # ---- misc ----
    (["power off monitors", "screen off"], "power-off-monitors"),
    (["power on monitors", "screen on"], "power-on-monitors"),
    (["quit niri", "exit niri"], "quit"),
]


def build_curated() -> dict[str, str]:
    curated: dict[str, str] = {}
    for phrases, action in CURATED:
        if isinstance(phrases, str):
            phrases = [phrases]
        for phrase in phrases:
            curated[normalise(phrase)] = action
    return curated


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    kdl_text = read_kdl_text()
    binds = parse_binds(kdl_text)
    cached_actions, cached_binds = read_cached_actions()
    live_actions = query_live_actions()

    actions: set[str] = set()
    actions.update(a for a in live_actions)
    actions.update(a for a in cached_actions)
    actions.update(b.get("action", "") for b in binds)
    actions.update(b.get("action", "") for b in cached_binds)
    actions.discard("")

    phrases: dict[str, dict] = {}

    # 1) auto-add one phrase per action ("focus-column-right" -> "focus column right")
    for action in sorted(actions):
        phrases[normalise(phrases_for_action(action))] = {
            "command": action,
            "args": [],
        }

    # 2) curated aliases win on collision
    curated = build_curated()
    for phrase, command in curated.items():
        phrases[phrase] = {"command": command, "args": []}

    output = {"phrases": dict(sorted(phrases.items()))}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {len(phrases)} phrases to {OUT_FILE}")
    print(
        f"  actions: {len(actions)} "
        f"(live={len(live_actions)}, cached={len(cached_actions)}, "
        f"bound={len(binds)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
