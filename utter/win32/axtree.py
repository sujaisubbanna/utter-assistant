"""Bounded Windows UI Automation tree via optional ``uiautomation``.

Same ``UIElement`` shape as :func:`utter.context.atspi.dump_tree`, so the
platform-neutral predicate/ranking in :mod:`utter.context.textfields` is shared.
Only the focused (or named) top-level window is walked; enumeration is bounded
by node count and a wall-clock deadline.

``uiautomation`` is imported lazily and only on Windows. When it is missing —
or the host is not Windows — :func:`available` reports why and
:func:`dump_tree` returns ``None``. Nothing here raises.
"""
from __future__ import annotations

import time
from typing import Optional

from utter import platform
from utter.types import Rect, UIElement

_MAX_VALUE_CHARS = 200

# UIA ControlTypeName -> AT-SPI-ish role name, so ``is_text_input`` (which knows
# "text field", "document text", "combo box", ...) works unchanged.
_UIA_ROLE_MAP = {
    "EditControl": "text field",
    "DocumentControl": "document text",
    "ComboBoxControl": "combo box",
    "TextControl": "text",
    "ButtonControl": "push button",
    "CheckBoxControl": "check box",
    "RadioButtonControl": "radio button",
    "ListControl": "list",
    "ListItemControl": "list item",
    "WindowControl": "frame",
    "PaneControl": "panel",
    "MenuControl": "menu",
    "MenuItemControl": "menu item",
    "TabControl": "page tab",
    "TabItemControl": "page tab",
    "HyperlinkControl": "link",
    "ImageControl": "image",
    "TreeControl": "tree",
    "TreeItemControl": "tree item",
    "TableControl": "table",
    "DataGridControl": "table",
}

# Roles whose value is user-editable (mirrors the AT-SPI/macOS state contract).
_EDITABLE_ROLES = frozenset({"text field", "document text", "combo box"})


def _uia():
    """The optional ``uiautomation`` module, or None (lazy; Windows only)."""
    if not platform.is_windows():
        return None
    try:
        import uiautomation as auto  # type: ignore[import-not-found]

        return auto
    except Exception:  # noqa: BLE001 - optional dependency
        return None


def available() -> tuple[bool, str]:
    """``(can_run, reason)`` — reason is ``""`` when the UIA backend is usable."""
    if not platform.is_windows():
        return False, "win-unavailable"
    if _uia() is None:
        return False, "uiautomation-unavailable"
    return True, ""


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - one bad node must not abort the dump
        return default


def _role(control) -> str:
    name = str(_safe(lambda: control.ControlTypeName, "") or "")
    if name in _UIA_ROLE_MAP:
        return _UIA_ROLE_MAP[name]
    if name.endswith("Control"):
        name = name[: -len("Control")]
    return name.casefold()


def _rect(control) -> Optional[Rect]:
    box = _safe(lambda: control.BoundingRectangle, None)
    if box is None:
        return None
    try:
        left, top = int(box.left), int(box.top)
        w = int(box.right) - left
        h = int(box.bottom) - top
    except Exception:  # noqa: BLE001
        return None
    if w <= 0 or h <= 0:
        return None
    return Rect(x=left, y=top, w=w, h=h)


def _value(control, role: str) -> str:
    text = ""
    value = _safe(lambda: control.GetValuePattern().Value, None)
    if value:
        text = str(value)
    if not text:
        text = str(_safe(lambda: control.Name, "") or "")
    return text[:_MAX_VALUE_CHARS]


def _states(control, role: str) -> list[str]:
    states: list[str] = []
    if role in _EDITABLE_ROLES:
        states.append("editable")
    if _safe(lambda: bool(control.IsKeyboardFocusable), False):
        states.append("focusable")
    if _safe(lambda: bool(control.IsEnabled), False):
        states.append("enabled")
    else:
        states.append("disabled")
    if _safe(lambda: bool(control.IsOffscreen), False):
        states.append("hidden")
    if _safe(lambda: bool(control.HasKeyboardFocus()), False):
        states.append("focused")
    return list(dict.fromkeys(states))


def _children(control) -> list:
    kids = _safe(lambda: control.GetChildren(), [])
    try:
        return [c for c in (kids or []) if c is not None]
    except Exception:  # noqa: BLE001
        return []


def _same(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return a is b


def _build(node, indices: list[int], app_id: str, focused_el, deadline: float,
           max_nodes: int, budget: dict, _depth: int = 0) -> Optional[UIElement]:
    if budget["count"] >= max_nodes or time.monotonic() > deadline or _depth > 64:
        return None
    budget["count"] += 1

    role = _role(node)
    name = str(_safe(lambda: node.Name, "") or "")
    description = str(_safe(lambda: node.HelpText, "") or "")
    value = _value(node, role)
    rect = _rect(node)
    is_focused = _same(node, focused_el)

    path = f"{app_id}#{'.'.join(str(i) for i in indices)}" if indices else f"{app_id}#"

    children: list[UIElement] = []
    for i, child in enumerate(_children(node)):
        if budget["count"] >= max_nodes or time.monotonic() > deadline:
            break
        built = _build(child, indices + [i], app_id, focused_el, deadline,
                       max_nodes, budget, _depth + 1)
        if built is not None:
            children.append(built)

    states = _states(node, role)
    if is_focused and "focused" not in states:
        states.append("focused")

    meaningful = bool(children) or bool(name) or bool(description) or rect is not None or bool(states)
    if not meaningful:
        return None
    return UIElement(
        id=path, role=role, name=name, description=description, value=value,
        rect=rect, states=states, actions=[], app_id=app_id, path=path,
        children=children,
    )


def _window_for_app(auto, app_id: str):
    """A top-level UIA control for ``app_id`` (or the foreground window)."""
    root = _safe(lambda: auto.GetRootControl(), None)
    if root is None:
        return None
    wanted = (app_id or "").strip().casefold()
    if wanted:
        for child in _children(root):
            name = str(_safe(lambda c=child: c.Name, "") or "").casefold()
            if name == wanted or wanted in name:
                return child
        # Fall back to matching the owning process's exe stem.
        for child in _children(root):
            pid = int(_safe(lambda c=child: c.ProcessId, 0) or 0)
            if pid and app_id_from_pid(pid) == wanted:
                return child
        return None
    foreground = _safe(lambda: auto.GetForegroundControl(), None)
    return foreground if foreground is not None else root


def app_id_from_pid(pid: int) -> str:
    """``app_id`` of a process, reusing the ctypes desktop resolver (pure seam)."""
    try:
        from utter.win32 import desktop
        return desktop.app_id_from_exe(desktop._exe_path(int(pid)))  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return ""


def dump_tree(app_id: Optional[str] = None, max_nodes: int = 400,
              timeout_s: float = 8.0) -> Optional[UIElement]:
    """Bounded UI Automation tree for ``app_id`` (foreground app when None).

    Same contract as :func:`utter.context.atspi.dump_tree`: returns ``None`` when
    UIA is unavailable or no root can be produced, otherwise a possibly-partial
    tree bounded by ``max_nodes``/``timeout_s``. Never raises.
    """
    auto = _uia()
    if auto is None:
        return None
    try:
        window = _window_for_app(auto, app_id or "")
        if window is None:
            return None
        focused_el = _safe(lambda: auto.GetFocusedControl(), None)
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        budget = {"count": 0}
        root_label = (app_id or str(_safe(lambda: window.Name, "") or "")).casefold()
        return _build(window, [], root_label, focused_el, deadline,
                      max(1, int(max_nodes)), budget)
    except Exception:  # noqa: BLE001 - never raise into the daemon
        return None


__all__ = ["available", "dump_tree", "app_id_from_pid"]
