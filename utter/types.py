"""Shared data contracts. Every subsystem imports from here; do not duplicate."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Tier(str, Enum):
    APP = "app"            # T0: context/app rules, no perception
    A11Y = "a11y"          # T1: accessibility tree
    KEYBOARD = "keyboard"  # T2: shortcuts
    VISION = "vision"      # T3: screenshot grounding (fallback)


@dataclass
class Point:
    x: int
    y: int


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Point:
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass
class FocusedWindow:
    app_id: str
    title: str = ""
    pid: int = 0
    window_id: int = 0
    workspace_id: int = 0
    is_floating: bool = False
    is_fullscreen: bool = False


@dataclass
class WindowInfo:
    """One niri window (used for contextual decisions)."""
    id: int
    app_id: str
    title: str = ""
    workspace_id: int = 0
    pid: int = 0
    is_focused: bool = False
    is_floating: bool = False
    is_fullscreen: bool = False


@dataclass
class Monitor:
    id: int
    output: str
    active_workspace_id: int = 0
    active_window_id: Optional[int] = None
    is_focused: bool = False
    geometry: Optional[Rect] = None


@dataclass
class UIElement:
    """One accessibility node. `path` is the stable AT-SPI path used to re-find it."""
    id: str
    role: str
    name: str = ""
    description: str = ""
    value: str = ""
    rect: Optional[Rect] = None
    states: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    app_id: str = ""
    path: str = ""
    children: list["UIElement"] = field(default_factory=list)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class Context:
    """Cheap, always-on snapshot of desktop state."""
    focused: Optional[FocusedWindow] = None
    monitors: list[Monitor] = field(default_factory=list)
    windows: list["WindowInfo"] = field(default_factory=list)
    clipboard: str = ""
    a11y: Optional[UIElement] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def focused_app(self) -> str:
        return self.focused.app_id if self.focused else ""

    @property
    def focused_title(self) -> str:
        return self.focused.title if self.focused else ""


class Action(str, Enum):
    OPEN_URL = "open_url"
    ENSURE_URL = "ensure_url"
    LAUNCH_APP = "launch_app"
    ENSURE_APP = "ensure_app"
    FOCUS_APP = "focus_app"
    NEW_TAB = "new_tab"
    SEARCH = "search"
    KEY = "key"
    TYPE_TEXT = "type_text"
    TERMINAL = "terminal"
    NIRI = "niri"
    MEDIA = "media"
    CLICK_ELEMENT = "click_element"
    CLICK_POINT = "click_point"
    SCROLL = "scroll"
    WAIT = "wait"
    SPEAK = "speak"
    DONE = "done"


@dataclass
class Step:
    action: Action
    args: dict[str, Any] = field(default_factory=dict)
    tier: Tier = Tier.APP
    description: str = ""
    confirm: bool = False


@dataclass
class Plan:
    utterance: str
    steps: list[Step] = field(default_factory=list)
    source: str = "rules"   # rules | llm | vision
    confidence: float = 1.0
    needs_perception: bool = False


@dataclass
class ActionResult:
    ok: bool
    action: Action
    tier: Tier
    detail: str = ""
    latency_ms: float = 0.0
