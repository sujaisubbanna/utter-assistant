"""Minimal macOS Accessibility (AX) reader for text-field detection.

The rest of macOS desktop access (NSWorkspace app/window list) lives in
:mod:`utter.macos.desktop`; this module only adds the bounded AX tree walk that
:mod:`utter.context.textfields` needs. It emits the same ``UIElement`` tree shape
as the Linux AT-SPI dump, so the platform-neutral predicate and ranking are
shared.

Honesty notes (see ``docs/MACOS.md``):

* Requires the Accessibility permission. Without it every call is a no-op and
  :func:`available` returns ``(False, "permission-denied")``.
* Electron/Chromium apps (VS Code, Slack, ...) expose no AX children until
  ``AXManualAccessibility`` is set; :func:`enable_manual_accessibility` does that
  once and the caller re-probes.
* Only the focused window is walked. Background windows are *not* enumerated:
  macOS has no cheap per-window AX dump for a non-focused app, and this module
  does not fake one.

Everything here is best-effort and never raises; a missing PyObjC, a denied
permission, or a bad attribute all degrade to ``None``/empty results.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from utter.types import Rect, UIElement

_MAX_VALUE_CHARS = 200
_MAX_NODES = 200

_AX_TEXT_ROLES = frozenset({
    "AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField",
})

# Bundle ids / names of common Chromium/Electron apps that need the manual flag.
_ELECTRON_BUNDLES = frozenset({
    "com.microsoft.vscode", "com.tinyspeck.slackmacgap", "com.hnc.discord",
    "com.google.chrome", "org.chromium.chromium", "com.brave.browser",
    "com.microsoft.edgemac", "md.obsidian", "com.figma.desktop",
    "notion.id", "com.electron",
})
_ELECTRON_TOKENS = ("electron", "chromium", "chrome", "brave", "edgemac")


def _as():
    """ApplicationServices module, or None when PyObjC is absent."""
    try:
        import ApplicationServices as AS  # type: ignore[import-not-found]

        return AS
    except Exception:  # noqa: BLE001
        return None


def _attr(AS, name: str) -> str:
    """Real ``kAX...Attribute`` constant, else the bare attribute string."""
    return getattr(AS, name, name[1:])


def _copy(el, attr, default=None):
    """Read one AX attribute; any failure returns ``default``."""
    AS = _as()
    if AS is None or el is None:
        return default
    try:
        err, value = AS.AXUIElementCopyAttributeValue(el, attr, None)
        if err == 0 and value is not None:
            return value
    except Exception:  # noqa: BLE001
        pass
    return default


def _same(a, b) -> bool:
    """Best-effort AX element identity (CFEqual, then ``==``/``is``)."""
    if a is None or b is None:
        return False
    try:
        import CoreFoundation as CF  # type: ignore[import-not-found]

        equal = getattr(CF, "CFEqual", None)
        if callable(equal):
            return bool(equal(a, b))
    except Exception:  # noqa: BLE001
        pass
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return a is b


def available() -> tuple[bool, str]:
    """``(can_run, reason)`` — reason is ``""`` when AX is usable."""
    AS = _as()
    if AS is None:
        return False, "ax-unavailable"
    trusted = getattr(AS, "AXIsProcessTrusted", None)
    if callable(trusted):
        try:
            if not trusted():
                return False, "permission-denied"
        except Exception:  # noqa: BLE001
            pass
    return True, ""


def front_pid() -> int:
    """PID of the frontmost application (0 when unavailable)."""
    try:
        from utter.macos import desktop
        return int(getattr(desktop.focused_window(), "pid", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0


def _app_element(pid: int):
    AS = _as()
    if AS is None or not pid:
        return None
    try:
        return AS.AXUIElementCreateApplication(int(pid))
    except Exception:  # noqa: BLE001
        return None


def is_electron(pid: int) -> bool:
    """Heuristic: is this Chromium/Electron (needs ``AXManualAccessibility``)?"""
    if not pid:
        return False
    bundle = ""
    try:
        from utter.macos import desktop
        bundle = str(getattr(desktop.focused_window(), "app_id", "") or "")
    except Exception:  # noqa: BLE001
        bundle = ""
    low = bundle.casefold()
    if any(token in low for token in _ELECTRON_TOKENS) or low in _ELECTRON_BUNDLES:
        return True
    # A settable AXManualAccessibility attribute is the definitive WebKit/Electron
    # signal; probe it only when the name heuristic is inconclusive.
    app = _app_element(pid)
    if app is not None:
        try:
            AS = _as()
            err, _value = AS.AXUIElementCopyAttributeValue(app, "AXManualAccessibility", None)
            if err == 0:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def enable_manual_accessibility(pid: int) -> bool:
    """Set ``AXManualAccessibility`` on ``pid``; True when accepted."""
    app = _app_element(pid)
    if app is None:
        return False
    try:
        import CoreFoundation as CF  # type: ignore[import-not-found]

        true_value: Any = CF.kCFBooleanTrue
    except Exception:  # noqa: BLE001
        true_value = True
    try:
        AS = _as()
        err = AS.AXUIElementSetAttributeValue(app, "AXManualAccessibility", true_value)
        return err == 0
    except Exception:  # noqa: BLE001
        return False


def _axvalue(value, value_type, holder):
    """Read an ``AXValue`` box into ``holder`` (handles PyObjC's tuple form)."""
    AS = _as()
    if AS is None or value is None:
        return None
    # PyObjC usually returns ``(ok, struct)`` when the out-param is ``None``.
    try:
        result = AS.AXValueGetValue(value, value_type, None)
        if isinstance(result, tuple) and len(result) == 2:
            ok, out = result
            return out if ok else None
    except Exception:  # noqa: BLE001
        pass
    try:
        result = AS.AXValueGetValue(value, value_type, holder)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(result, tuple):
        result = result[0]
    return holder if result else None


def _rect(el) -> Optional[Rect]:
    """Screen rect of an AX element, or None when unreadable/zero-size."""
    try:
        import Quartz  # type: ignore[import-not-found]
        AS = _as()
        if AS is None:
            return None
        pos_v = _copy(el, _attr(AS, "kAXPositionAttribute"))
        size_v = _copy(el, _attr(AS, "kAXSizeAttribute"))
        if pos_v is None or size_v is None:
            return None
        point = _axvalue(pos_v, getattr(AS, "kAXValueCGPointType", 1), Quartz.CGPoint())
        size = _axvalue(size_v, getattr(AS, "kAXValueCGSizeType", 2), Quartz.CGSize())
        if point is None or size is None:
            return None
        w, h = int(size.x), int(size.y)
        if w <= 0 or h <= 0:
            return None
        return Rect(x=int(point.x), y=int(point.y), w=w, h=h)
    except Exception:  # noqa: BLE001
        return None


def _children(el) -> list:
    AS = _as()
    if AS is None or el is None:
        return []
    value = _copy(el, _attr(AS, "kAXChildrenAttribute"), [])
    try:
        return [c for c in (value or []) if c is not None]
    except Exception:  # noqa: BLE001
        return []


def _build(node, indices: list[int], app_id: str, focused_el, deadline: float,
           max_nodes: int, budget: dict, _depth: int = 0) -> Optional[UIElement]:
    if budget["count"] >= max_nodes or time.monotonic() > deadline or _depth > 64:
        return None
    budget["count"] += 1

    AS = _as()
    role = str(_copy(node, _attr(AS, "kAXRoleAttribute"), "") or "")
    name = str(_copy(node, _attr(AS, "kAXTitleAttribute"), "") or "")
    description = str(_copy(node, _attr(AS, "kAXDescriptionAttribute"), "") or "")
    value = str(_copy(node, _attr(AS, "kAXValueAttribute"), "") or "")[:_MAX_VALUE_CHARS]
    rect = _rect(node)
    is_focused = _same(node, focused_el) if focused_el is not None else False

    path = f"{app_id}#{'.'.join(str(i) for i in indices)}" if indices else f"{app_id}#"
    children: list[UIElement] = []
    for i, child in enumerate(_children(node)):
        if budget["count"] >= max_nodes or time.monotonic() > deadline:
            break
        built = _build(child, indices + [i], app_id, focused_el, deadline,
                       max_nodes, budget, _depth + 1)
        if built is not None:
            children.append(built)

    # Mirror AT-SPI state nicks so the shared predicate/ranking stay neutral.
    states: list[str] = []
    if role in _AX_TEXT_ROLES:
        states = ["editable", "focusable", "enabled"]
    if is_focused:
        states = list(dict.fromkeys(states + ["focused"]))

    meaningful = bool(children) or bool(name) or bool(description) or rect is not None or bool(states)
    if not meaningful:
        return None
    return UIElement(
        id=path, role=role, name=name, description=description, value=value,
        rect=rect, states=states, actions=[], app_id=app_id, path=path,
        children=children,
    )


def dump_focused_tree(app_pid: Optional[int] = None, *, app_id: str = "",
                      max_nodes: int = _MAX_NODES,
                      deadline_s: float = 1.0) -> Optional[UIElement]:
    """Bounded AX tree of ``app_pid``'s focused window (None when unavailable).

    The returned tree may be partial (node + wall-clock bounded). The focused
    element is marked with a ``focused`` state and the app's window is the root.
    """
    AS = _as()
    if AS is None:
        return None
    pid = int(app_pid or front_pid() or 0)
    if not pid:
        return None
    app = _app_element(pid)
    if app is None:
        return None
    focused_el = _copy(app, _attr(AS, "kAXFocusedUIElementAttribute"))
    root = _copy(app, _attr(AS, "kAXFocusedWindowAttribute")) or focused_el
    if root is None:
        return None
    deadline = time.monotonic() + max(0.0, float(deadline_s))
    budget = {"count": 0}
    return _build(root, [], app_id or str(pid), focused_el, deadline,
                  max(1, int(max_nodes)), budget)


__all__ = [
    "available",
    "front_pid",
    "is_electron",
    "enable_manual_accessibility",
    "dump_focused_tree",
]
