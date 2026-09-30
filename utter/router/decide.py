"""Jev-style constrained decision head.

Instead of free-form planner generation, enumerate a small set of *fully
resolved* candidate actions and let the local tiny LLM **choose** one. The
server's first-token logprobs over the lettered choices yield a calibrated
probability distribution.

Local vLLM is expected at ``cfg.llm_base_url`` (default
``http://127.0.0.1:8001/v1``) serving ``cfg.llm_model`` (default ``qwen3-4b``).
All network use is lazy: importing this module never touches the network.

Public API::

    build_candidates(utterance, ctx, profiles) -> list[Candidate]
    decide(utterance, ctx, profiles, cfg=None) -> Decision | None
    decide_debug(utterance, ctx, profiles, cfg=None) -> Decision | None
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..types import Context
from . import profiles as profiles_mod
from .rules import (
    CLI_AGENTS,
    DOMAIN_RE,
    MEDIA_MAP,
    NIRI_MAP,
    SITE_SEARCH,
    SITES,
    TERMINAL_LAUNCH,
    URL_RE,
    normalize,
)
from .rules import _resolve as _rules_resolve

# Max candidates the letter alphabet (A..N -> 14) can address. We keep 12
# plausible candidates plus the always-present "none".
MAX_CANDIDATES = 13

_LETTERS = "ABCDEFGHIJKLMN"
_NONE_LABEL = "do nothing / not a command"

_DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL = "qwen3-4b"
_TIMEOUT = 6.0

_SYSTEM = (
    "You route spoken desktop commands. Output ONLY one letter. A candidate "
    "is actionable ONLY if the utterance explicitly issues a command. A search "
    "action requires the user to say search, google, or look up. For a lone "
    "noun like \"banana\" or a vague phrase, the answer is none."
)


# --------------------------------------------------------------------------- #
# data contracts
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    """One fully-specified competing interpretation of an utterance."""

    op: str
    args: dict = field(default_factory=dict)
    label: str = ""
    tier: str = "app"


@dataclass
class Decision:
    """The model's constrained choice over the candidate set."""

    candidate: Candidate
    confidence: float
    distribution: dict = field(default_factory=dict)  # label -> probability
    source: str = "decide"
    raw: str = ""


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _freeze(args: Any) -> str:
    return json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)


class _CandSet:
    """Ordered, de-duplicated candidate accumulator with unique labels."""

    def __init__(self) -> None:
        self._items: list[Candidate] = []
        self._keys: set[tuple[str, str]] = set()
        self._labels: set[str] = set()

    def add(self, cand: Optional[Candidate]) -> None:
        if cand is None or not cand.op:
            return
        key = (cand.op, _freeze(cand.args))
        if key in self._keys:
            return
        label = (cand.label or cand.op).strip() or cand.op
        if label in self._labels:
            i = 2
            while f"{label} ({i})" in self._labels:
                i += 1
            label = f"{label} ({i})"
        cand.label = label
        self._keys.add(key)
        self._labels.add(label)
        self._items.append(cand)

    def candidates(self) -> list[Candidate]:
        return list(self._items)

    def count_non_none(self) -> int:
        return sum(1 for c in self._items if c.op != "none")

    def __len__(self) -> int:
        return len(self._items)


def _launch_argv(prof) -> Any:
    launch = getattr(prof, "launch", None)
    return list(launch) if isinstance(launch, (list, tuple)) else launch


def _step_to_candidate(step) -> Candidate:
    action = getattr(step, "action", "")
    op = getattr(action, "value", None) or str(action)
    tier = getattr(step, "tier", "app")
    tier_s = getattr(tier, "value", None) or str(tier)
    label = getattr(step, "description", "") or op
    return Candidate(op=op, args=dict(getattr(step, "args", {}) or {}), label=label, tier=tier_s or "app")


# --------------------------------------------------------------------------- #
# candidate construction (pure / cheap; no network)
# --------------------------------------------------------------------------- #
_OPEN_RE = re.compile(
    r"^(?:open|launch|start|spawn|run|visit|navigate to|navigate|go to|"
    r"pull up|bring up|show me|display|load|show)\s+(.+)$",
    re.I,
)
_SEARCH_RE = re.compile(
    r"^(?:search(?:\s+the\s+web)?|google|look up|look)\s+(?:for\s+|about\s+)?(.+)$",
    re.I,
)
_RUN_RE = re.compile(r"^(?:run|execute|terminal run)\s+(?:command\s+)?(.+)$", re.I | re.S)
_TYPE_RE = re.compile(r"^(?:type|write|enter)\s+(.+)$", re.I | re.S)


def _niri_add(cs: _CandSet, command: str, args: Optional[list] = None) -> None:
    cs.add(Candidate("niri", {"command": command, "args": list(args or [])}, f"niri {command}"))


def _looks_niri(t: str) -> bool:
    if t in NIRI_MAP:
        return True
    if re.match(r"^(?:go to |switch to )?workspace \d+$", t):
        return True
    if re.match(r"^move (?:window|column) to workspace \d+$", t):
        return True
    if re.match(r"^move to (?:monitor )?(?:left|right|up|down)$", t):
        return True
    words = set(t.split())
    if words & {"left", "right", "up", "down"} and words & {
        "focus", "move", "tile", "column", "window", "switch", "go"
    }:
        return True
    if words & {"maximize", "expand", "minimize", "fullscreen", "center",
                "float", "screenshot", "overview", "tabbed", "tile"}:
        return True
    if "close" in words and ("window" in words or "column" in words):
        return True
    return False


def _add_target(cs: _CandSet, target: str, ctx: Context, profiles: dict) -> None:
    target = (target or "").strip()
    if not target:
        return
    tl = target.lower()
    if URL_RE.match(target):
        url = target if tl.startswith("http") else "https://" + target
        cs.add(Candidate("ensure_url", {"url": url}, f"open {url}"))
        cs.add(Candidate("open_url", {"url": url, "new_tab": True}, f"open {url} in a new tab"))
        return
    if DOMAIN_RE.match(target) and "." in target:
        url = "https://" + target
        cs.add(Candidate("ensure_url", {"url": url}, f"open {url}"))
        cs.add(Candidate("open_url", {"url": url, "new_tab": True}, f"open {url} in a new tab"))
        return
    if tl in SITES:
        url = SITES[tl]
        cs.add(Candidate("ensure_url", {"url": url, "site": tl}, f"open {tl}"))
        cs.add(Candidate("open_url", {"url": url, "new_tab": True}, f"open {tl} in a new tab"))
        return
    if tl in SITE_SEARCH:
        cs.add(Candidate("open_url", {"url": SITE_SEARCH[tl].format(q=tl.replace(' ', '+'))},
                         f"open {tl}"))
        return
    prof = profiles_mod.resolve(target, profiles) or _rules_resolve(profiles, target)
    if prof is not None:
        cs.add(Candidate("ensure_app", {"app": prof.id, "argv": _launch_argv(prof)},
                         f"open {prof.name}"))
        cs.add(Candidate("focus_app", {"app": prof.id}, f"focus {prof.name}"))
        return
    # unknown noun phrase: nothing target-specific; search handles it


# Category words that appear as profile aliases but are never a spoken app
# name; matching them gives nonsense candidates ("make the text bigger" ->
# "open Micro/KWrite").
_GENERIC_ALIASES = {
    "text", "editor", "terminal", "shell", "code", "app", "application",
    "browser", "file", "files", "folder", "folders", "note", "notes",
    "settings", "system", "video", "video player", "media", "music", "screen",
    "display", "volume", "command", "commandline", "prompt", "console",
    "monitoring", "desktop", "control", "utility", "game", "games", "chat",
    "mail", "email", "image", "images", "photo", "photos", "document",
    "documents", "reader", "viewer", "manager", "tool", "tools", "ide",
    "syntax", "notepad", "txt", "office", "web", "internet", "network",
    "sound", "audio", "player", "recording", "stream", "clipboard", "calendar",
    "contacts", "calculator", "archive", "backup", "monitor",
}


def _generic_aliases(profiles: dict) -> set[str]:
    """Aliases too generic to treat as a spoken app name.

    A name is generic when it is a known category word, or when many profiles
    share it ("editor", "shell", "java", ...).
    """
    counts: dict[str, int] = {}
    for prof in profiles.values():
        seen: set[str] = set()
        for alias in getattr(prof, "aliases", []) or []:
            a = (alias or "").strip().lower()
            if a and a not in seen:
                seen.add(a)
                counts[a] = counts.get(a, 0) + 1
    frequent = {a for a, c in counts.items() if c >= 3}
    return frequent | _GENERIC_ALIASES


def _mention_candidates(cs: _CandSet, t: str, ctx: Context, profiles: dict) -> None:
    """Add candidates for any site / CLI agent / installed app named in `t`."""
    for key in sorted(SITES, key=len, reverse=True):
        if len(key) >= 2 and re.search(r"\b" + re.escape(key) + r"\b", t):
            url = SITES[key]
            cs.add(Candidate("ensure_url", {"url": url, "site": key}, f"open {key}"))
            cs.add(Candidate("open_url", {"url": url, "new_tab": True}, f"open {key} in a new tab"))
            return
    for key, argv in CLI_AGENTS.items():
        if len(key) >= 3 and re.search(r"\b" + re.escape(key) + r"\b", t):
            cs.add(Candidate("launch_app", {"app": "foot", "argv": [*TERMINAL_LAUNCH, *argv]},
                             f"launch {argv[0]}"))
            return
    generic = _generic_aliases(profiles)
    matched = 0
    for pid, prof in profiles.items():
        names = [getattr(prof, "name", "") or "", pid, *(getattr(prof, "aliases", []) or [])]
        hit = False
        for name in names:
            n = (name or "").strip().lower()
            if len(n) < 3 or n in generic:
                continue
            if re.search(r"\b" + re.escape(n) + r"\b", t):
                cs.add(Candidate("ensure_app", {"app": prof.id, "argv": _launch_argv(prof)},
                                 f"open {prof.name}"))
                cs.add(Candidate("focus_app", {"app": prof.id}, f"focus {prof.name}"))
                hit = True
                break
        if hit:
            matched += 1
            if matched >= 2:
                break


def _generic_extras(cs: _CandSet, t: str, rest: str) -> None:
    arg = (rest or "").strip() or t.strip()
    if not arg:
        return
    cs.add(Candidate("search", {"query": arg}, f"search the web for {arg!r}"))
    cs.add(Candidate("click_element", {"description": arg}, f"click {arg!r}"))
    cs.add(Candidate("type_text", {"text": arg}, f"type {arg!r}"))


def _open_target(raw: str, t: str) -> str:
    m = _OPEN_RE.match(raw.strip()) or _OPEN_RE.match(t)
    if not m:
        return ""
    target = m.group(1).strip()
    target = re.sub(r"^(?:a|an|the|me)\s+", "", target, flags=re.I)
    target = re.sub(r"\s+in a (?:new tab|new window)$", "", target, flags=re.I)
    target = re.sub(r"\s+(?:new tab|new window)$", "", target, flags=re.I)
    return target.strip()


def _search_url(q: str, ctx: Context, profiles: dict) -> str:
    template = None
    if ctx is not None and getattr(ctx, "focused", None):
        prof = profiles.get(ctx.focused_app)
        template = getattr(prof, "search_url", None) if prof else None
    return (template or "https://duckduckgo.com/?q={q}").format(q=q.replace(" ", "+"))


def _open_family(cs: _CandSet, t: str, raw: str, rest: str, ctx: Context, profiles: dict) -> None:
    target = _open_target(raw, t)
    if target:
        _add_target(cs, target, ctx, profiles)
        cs.add(Candidate("search", {"query": target}, f"search the web for {target!r}"))
    _mention_candidates(cs, t, ctx, profiles)


def _run_family(cs: _CandSet, t: str, raw: str) -> None:
    m = _RUN_RE.match(raw.strip())
    cmd = m.group(1).strip().strip("\"'") if m else ""
    if cmd:
        cs.add(Candidate("terminal", {"command": cmd}, f"run `{cmd}` in terminal"))
    _generic_extras(cs, t, cmd or t)


def _search_family(cs: _CandSet, t: str, raw: str, rest: str, ctx: Context, profiles: dict) -> None:
    m = _SEARCH_RE.match(raw.strip())
    q = ""
    if m:
        q = re.sub(r"^(?:for|about)\s+", "", m.group(1).strip(), flags=re.I)
    q = q or rest or t
    if q:
        cs.add(Candidate("search", {"query": q}, f"search the web for {q!r}"))
        url = _search_url(q, ctx, profiles)
        cs.add(Candidate("open_url", {"url": url}, f"open search results for {q!r}"))
        cs.add(Candidate("ensure_url", {"url": url}, f"show search results for {q!r}"))
    _mention_candidates(cs, t, ctx, profiles)


def _media_family(cs: _CandSet, t: str) -> None:
    primary = MEDIA_MAP.get(t)
    if not primary:
        for key in sorted(MEDIA_MAP, key=len, reverse=True):
            if re.search(r"\b" + re.escape(key) + r"\b", t):
                primary = MEDIA_MAP[key]
                break
    if primary:
        cs.add(Candidate("media", {"command": primary}, f"media {primary}"))
    extras = {
        "play": ["play-pause", "pause"],
        "resume": ["play", "play-pause"],
        "pause": ["play-pause", "play"],
        "next": ["play-pause", "previous"],
        "previous": ["play-pause", "next"],
        "skip": ["previous"],
        "stop": ["pause", "play-pause"],
    }.get(primary or "", [])
    for cmd in extras:
        cs.add(Candidate("media", {"command": cmd}, f"media {cmd}"))
    if primary in ("play", "pause") or (primary is None and "play" in t):
        cs.add(Candidate("key", {"chord": "space"}, "press space (play/pause)"))


def _type_family(cs: _CandSet, t: str, raw: str, rest: str) -> None:
    m = _TYPE_RE.match(raw.strip())
    text = m.group(1).strip().strip("\"'") if m else (rest or t)
    if text:
        cs.add(Candidate("type_text", {"text": text}, f"type {text!r}"))
    _generic_extras(cs, t, text or rest)


def _click_family(cs: _CandSet, t: str, rest: str) -> None:
    m = re.match(r"^(?:press|hit|tap|type key)\s+(.+)$", t)
    if m and m.group(1).strip() in {"enter", "return", "escape", "esc", "tab", "space",
                                     "backspace", "delete", "up", "down", "left", "right"}:
        token = m.group(1).strip()
        chord = {"enter": "Return", "return": "Return", "esc": "Escape",
                 "space": "space", "left": "Left", "right": "Right",
                 "up": "Up", "down": "Down"}.get(token, token)
        cs.add(Candidate("key", {"chord": chord}, f"press {chord}"))
        return
    desc = re.sub(r"^(?:on|the)\s+", "", rest.strip(), flags=re.I) or t
    cs.add(Candidate("click_element", {"description": desc}, f"click {desc!r}"))
    cs.add(Candidate("key", {"chord": "Return"}, "press Return"))
    _generic_extras(cs, t, desc)


def _niri_family(cs: _CandSet, t: str) -> None:
    if t in NIRI_MAP:
        cmd, args = NIRI_MAP[t]
        _niri_add(cs, cmd, args)
    m = re.match(r"^(?:go to |switch to )?workspace (\d+)$", t)
    if m:
        _niri_add(cs, "focus-workspace", [int(m.group(1))])
    m = re.match(r"^move (?:window|column) to workspace (\d+)$", t)
    if m:
        _niri_add(cs, "move-window-to-workspace", [int(m.group(1))])
    m = re.match(r"^move to (?:monitor )?(left|right|up|down)$", t)
    if m:
        _niri_add(cs, f"move-window-to-monitor-{m.group(1)}", [])

    words = set(t.split())
    for d in ("left", "right", "up", "down"):
        if d not in words:
            continue
        _niri_add(cs, f"focus-column-{d}")
        _niri_add(cs, f"move-column-{d}")
        _niri_add(cs, f"focus-monitor-{d}")
        _niri_add(cs, f"move-window-to-monitor-{d}")
    keyword_cmds = {
        "maximize": ["maximize-column"],
        "expand": ["expand-column-to-available-width"],
        "center": ["center-column", "center-window"],
        "fullscreen": ["fullscreen-window"],
        "minimize": ["minimize-window"],
        "float": ["toggle-window-floating"],
        "tabbed": ["toggle-column-tabbed-display"],
        "overview": ["toggle-overview"],
        "screenshot": ["screenshot-screen"],
        "tile": ["maximize-column"],
    }
    for kw, cmds in keyword_cmds.items():
        if kw in words:
            for cmd in cmds:
                _niri_add(cs, cmd)
    if "close" in words and ("window" in words or "column" in words):
        _niri_add(cs, "close-window")


def _generic_family(cs: _CandSet, t: str, rest: str, ctx: Context, profiles: dict) -> None:
    _mention_candidates(cs, t, ctx, profiles)
    _generic_extras(cs, t, rest)


def _pad(cs: _CandSet, t: str, rest: str) -> None:
    """Ensure at least three plausible alternatives before adding "none"."""
    arg = (rest or "").strip() or t.strip()
    if not arg:
        return
    pool = [
        Candidate("search", {"query": arg}, f"search the web for {arg!r}"),
        Candidate("click_element", {"description": arg}, f"click {arg!r}"),
        Candidate("type_text", {"text": arg}, f"type {arg!r}"),
        Candidate("key", {"chord": "Return"}, "press Return"),
    ]
    for cand in pool:
        if cs.count_non_none() >= 3:
            break
        cs.add(cand)


def build_candidates(utterance: str, ctx: Context, profiles: dict) -> list[Candidate]:
    """Enumerate 3..12 plausible, fully-specified actions + final ``none``.

    Pure and cheap: no network, no subprocess. Deduped by ``(op, args)``.
    """
    cs = _CandSet()
    raw = (utterance or "").strip()
    t = normalize(utterance or "")
    if not t:
        cs.add(Candidate("none", {}, _NONE_LABEL))
        return cs.candidates()

    # 1) deterministic rules provide the primary interpretation.
    try:
        from .rules import plan as _rules_plan

        rules_plan = _rules_plan(utterance, ctx, profiles)
    except Exception:
        rules_plan = None
    if rules_plan and getattr(rules_plan, "steps", None):
        cs.add(_step_to_candidate(rules_plan.steps[0]))

    first = t.split(" ", 1)[0]
    rest = t.split(" ", 1)[1].strip() if " " in t else ""

    # 2) competing interpretations for the leading verb / phrase.
    if _looks_niri(t):
        _niri_family(cs, t)
    if first in {"run", "execute"} or t.startswith("terminal run"):
        _run_family(cs, t, raw)
    elif _OPEN_RE.match(raw) or _OPEN_RE.match(t):
        _open_family(cs, t, raw, rest, ctx, profiles)
    elif first in {"search", "google", "look"}:
        _search_family(cs, t, raw, rest, ctx, profiles)
    elif first in {"play", "pause", "resume", "stop", "next", "previous", "skip"}:
        _media_family(cs, t)
        _mention_candidates(cs, t, ctx, profiles)
    elif first in {"type", "write", "enter"}:
        _type_family(cs, t, raw, rest)
    elif first in {"click", "press", "tap", "hit"}:
        _click_family(cs, t, rest)
    elif _looks_niri(t):
        pass  # already handled above
    else:
        _generic_family(cs, t, rest, ctx, profiles)

    _pad(cs, t, rest)

    # 3) cap non-none candidates, then always append the escape hatch.
    items = cs.candidates()
    non_none = [c for c in items if c.op != "none"][:MAX_CANDIDATES - 1]
    non_none.append(Candidate("none", {}, _NONE_LABEL))
    return non_none


# --------------------------------------------------------------------------- #
# constrained LLM call
# --------------------------------------------------------------------------- #
def _ctx_summary(ctx: Context) -> str:
    lines: list[str] = []
    focused = getattr(ctx, "focused", None) if ctx is not None else None
    if focused is not None:
        lines.append(f"Focused: {focused.app_id} \u2014 {focused.title!r}")
    else:
        lines.append("Focused: (none)")
    wins = getattr(ctx, "windows", None) or []
    if wins:
        lines.append("Windows: " + "; ".join(f"{w.app_id}:{w.title!r}" for w in wins[:8]))
    return "\n".join(lines)


def _build_prompt(utterance: str, ctx: Context, candidates: list[Candidate]) -> tuple[list[str], str]:
    letters = [chr(ord("A") + i) for i in range(len(candidates))]
    rows = [f"{letter}. {c.op} {json.dumps(c.args, ensure_ascii=False)}  # {c.label}"
            for letter, c in zip(letters, candidates)]
    user = (
        f"Utterance: {utterance!r}\n"
        f"{_ctx_summary(ctx)}\n"
        "Candidates:\n"
        + "\n".join(rows)
        + "\nAnswer with the single best letter."
    )
    return letters, user


def _parse_decision(data: dict, candidates: list[Candidate], letters: list[str],
                    strict: bool) -> Optional[Decision]:
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        return None
    content = ((choice.get("message") or {}).get("content") or "").strip()
    logprobs = choice.get("logprobs") or {}
    entries = logprobs.get("content") or []

    dist: dict[str, float] = {}
    token = ""
    if entries:
        first = entries[0] or {}
        token = (first.get("token") or "").strip().upper()
        for entry in first.get("top_logprobs") or []:
            tok = (entry.get("token") or "").strip().upper()
            if tok in letters:
                try:
                    dist[tok] = math.exp(float(entry.get("logprob", -9999.0)))
                except (TypeError, ValueError):
                    pass
        if token in letters and token not in dist:
            try:
                dist[token] = math.exp(float(first.get("logprob", -9999.0)))
            except (TypeError, ValueError):
                pass

    chosen = ""
    if content and content[:1].upper() in letters and len(content.strip()) <= 2:
        chosen = content[:1].upper()
    if chosen not in letters and token in letters:
        chosen = token
    if chosen not in letters:
        if strict:
            return None
        m = re.search(r"[A-N]", content.upper())
        if not m or m.group(0) not in letters:
            return None
        chosen = m.group(0)

    # Plain request with no logprobs: a degenerate but honest distribution.
    if not dist:
        if strict:
            return None
        dist = {chosen: 1.0}

    total = sum(dist.values())
    if total <= 0:
        dist = {chosen: 1.0}
        total = 1.0
    dist = {k: v / total for k, v in dist.items()}
    if chosen not in dist and dist:
        chosen = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[0][0]

    distribution = {
        candidates[letters.index(k)].label: round(v, 6)
        for k, v in sorted(dist.items(), key=lambda kv: kv[1], reverse=True)
        if k in letters
    }
    confidence = float(dist.get(chosen, 0.0))
    return Decision(
        candidate=candidates[letters.index(chosen)],
        confidence=confidence,
        distribution=distribution,
        source="decide",
        raw=chosen,
    )


def _query(utterance: str, ctx: Context, candidates: list[Candidate],
           cfg=None) -> Optional[Decision]:
    base_url = getattr(cfg, "llm_base_url", None) or _DEFAULT_BASE_URL
    model = getattr(cfg, "llm_model", None) or _DEFAULT_MODEL
    try:
        import requests  # lazy: module import must work offline
    except Exception:
        return None

    letters, user = _build_prompt(utterance, ctx, candidates)
    if not letters:
        return None

    common = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 1,
        "logprobs": True,
        "top_logprobs": len(candidates),
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    # (extra body, strict parse). vLLM >=0.6 accepts `structured_outputs.choice`;
    # older builds accept the legacy `guided_choice`; last resort is a plain call.
    attempts = [
        ({"structured_outputs": {"choice": letters}}, True),
        ({"guided_choice": letters}, True),
        ({}, False),
    ]
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    for extra, strict in attempts:
        payload = dict(common)
        payload.update(extra)
        try:
            resp = requests.post(endpoint, json=payload, timeout=_TIMEOUT)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        decision = _parse_decision(data, candidates, letters, strict)
        if decision is not None:
            return decision
    return None


def _should_skip(candidates: list[Candidate]) -> bool:
    return not any(c.op != "none" for c in candidates)


def decide(utterance: str, ctx: Context, profiles: dict, cfg=None) -> Optional[Decision]:
    """Return the model's chosen action, or None when it fails/abstains.

    Fails open (returns None) on any server/parse error so the caller can fall
    back to rules. If ``cfg.decide_threshold`` is set, a choice below it is
    treated as an abstention *by this function only*; use :func:`decide_debug`
    to always see the raw decision.
    """
    candidates = build_candidates(utterance, ctx, profiles)
    if _should_skip(candidates):
        return None
    decision = _query(utterance, ctx, candidates, cfg)
    if decision is None:
        return None
    threshold = getattr(cfg, "decide_threshold", None) if cfg is not None else None
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = None
        if threshold is not None and decision.confidence < threshold:
            return None
    return decision


def decide_debug(utterance: str, ctx: Context, profiles: dict, cfg=None) -> Optional[Decision]:
    """Like :func:`decide` but never applies ``cfg.decide_threshold``."""
    candidates = build_candidates(utterance, ctx, profiles)
    if _should_skip(candidates):
        return None
    return _query(utterance, ctx, candidates, cfg)


__all__ = [
    "Candidate",
    "Decision",
    "build_candidates",
    "decide",
    "decide_debug",
]
