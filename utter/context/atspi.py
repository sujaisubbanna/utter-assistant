"""AT-SPI accessibility tree (T1).

This is the latency-sensitive perception path. `dump_tree` is bounded by both a
node budget and a wall-clock deadline; if the accessibility bus stalls it
returns a partial tree rather than blocking the daemon.

Requires the AT-SPI bridge to be active on the session:
  - `gsettings set org.gnome.desktop.interface toolkit-accessibility true`
  - `org.a11y.Status.IsEnabled` must be true on the session bus.
Firefox/Zen expose a tree once accessibility is enabled at/near startup.
Electron/Chromium apps need `--force-renderer-accessibility` at launch.

PRIVACY NOTE: an AT-SPI tree can contain on-screen text (e.g. page content).
Callers embedding it in prompts should treat it as sensitive.
"""
from __future__ import annotations

import time
from typing import Optional

from utter.types import Rect, UIElement

try:  # gi/Atspi only exists inside .venv-agent (system-site-packages)
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi  # type: ignore

    _HAS_ATSPI = True
except Exception:  # noqa: BLE001 - degrade gracefully on machines without AT-SPI
    Atspi = None  # type: ignore
    _HAS_ATSPI = False

# Cache the StateType enum once; iterating it per-node is unnecessary D-Bus work.
_STATE_TYPES = list(Atspi.StateType) if _HAS_ATSPI else []
_SCREEN = Atspi.CoordType.SCREEN if _HAS_ATSPI else 0

_MAX_VALUE_CHARS = 200


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - a single bad node must not abort the dump
        return default


class _Budget:
    __slots__ = ("max_nodes", "deadline", "count", "stop")

    def __init__(self, max_nodes: int, timeout_s: float):
        self.max_nodes = max(1, int(max_nodes))
        self.deadline = time.monotonic() + max(0.1, float(timeout_s))
        self.count = 0
        self.stop = False


def _candidate_apps(desktop) -> list[tuple[str, object]]:
    apps: list[tuple[str, object]] = []
    for i in range(_safe(desktop.get_child_count, 0) or 0):
        child = _safe(lambda i=i: desktop.get_child_at_index(i))
        if child is None:
            continue
        apps.append((str(_safe(child.get_name, "") or ""), child))
    return apps


def find_app(app_id: Optional[str]):
    """Locate an application accessible by name/toolkit (case-insensitive).

    With app_id=None the focused window's app_id is tried first, then the
    application with the most immediate children is used. Returns
    (name, accessible) or (None, None).
    """
    if not _HAS_ATSPI:
        return None, None
    desktop = _safe(lambda: Atspi.get_desktop(0))
    if desktop is None:
        return None, None
    apps = _candidate_apps(desktop)
    if not apps:
        return None, None

    wanted = app_id
    if not wanted:
        try:
            from utter.context.niri import focused_window

            fw = focused_window()
            wanted = fw.app_id if fw else None
        except Exception:  # noqa: BLE001
            wanted = None

    if wanted:
        target = str(wanted).casefold()
        for name, node in apps:
            nm = name.casefold()
            if nm == target or target in nm or nm in target:
                return name, node
        # A focused app may not expose AT-SPI (Electron without the flag, etc.).
        return None, None

    # No hint: prefer the app with the most immediate descendants.
    best = max(apps, key=lambda kv: _safe(kv[1].get_child_count, 0) or 0)
    return best


def _node_value(node) -> str:
    ti = _safe(node.get_text_iface)
    if ti is None:
        return ""
    n = _safe(ti.get_character_count, 0) or 0
    if not n:
        return ""
    text = _safe(lambda: ti.get_text(0, min(int(n), _MAX_VALUE_CHARS)), "")
    return text or ""


def _node_actions(node) -> list[str]:
    act = _safe(node.get_action_iface)
    if act is None:
        return []
    out: list[str] = []
    for i in range(_safe(act.get_n_actions, 0) or 0):
        nm = _safe(lambda i=i: act.get_action_name(i))
        if nm:
            out.append(str(nm))
    return out


def _node_states(node) -> list[str]:
    ss = _safe(node.get_state_set)
    if ss is None:
        return []
    return [st.value_nick for st in _STATE_TYPES if _safe(lambda st=st: ss.contains(st), False)]


def _node_rect(node) -> Optional[Rect]:
    comp = _safe(node.get_component_iface)
    if comp is None:
        return None
    r = _safe(lambda: comp.get_extents(_SCREEN))
    if r is None:
        return None
    w, h = int(_safe(lambda: r.width, 0) or 0), int(_safe(lambda: r.height, 0) or 0)
    if w <= 0 or h <= 0:
        return None
    return Rect(x=int(getattr(r, "x", 0) or 0), y=int(getattr(r, "y", 0) or 0), w=w, h=h)


def _build(node, indices: list[int], app_id: str, budget: _Budget, seen: set) -> Optional[UIElement]:
    if budget.stop:
        return None
    if budget.count >= budget.max_nodes or time.monotonic() > budget.deadline:
        budget.stop = True
        return None
    budget.count += 1

    nid = _safe(node.get_id, -1)
    if isinstance(nid, int) and nid >= 0:
        if nid in seen:
            return None
        seen.add(nid)

    role = str(_safe(node.get_role_name, "") or "")
    name = str(_safe(node.get_name, "") or "")
    description = str(_safe(node.get_description, "") or "")
    rect = _node_rect(node)
    actions = _node_actions(node)
    states = _node_states(node)
    value = _node_value(node)

    path = f"{app_id}#{'.'.join(str(i) for i in indices)}" if indices else f"{app_id}#"

    children: list[UIElement] = []
    count = _safe(node.get_child_count, 0) or 0
    for i in range(count):
        if budget.stop:
            break
        child = _safe(lambda i=i: node.get_child_at_index(i))
        if child is None:
            continue
        built = _build(child, indices + [i], app_id, budget, seen)
        if built is not None:
            children.append(built)

    # Prune empty leaves: keep nodes that carry information, actions, or content.
    meaningful = bool(children) or bool(actions) or bool(name) or bool(description) or rect is not None
    if not meaningful:
        return None

    return UIElement(
        id=str(nid) if isinstance(nid, int) and nid >= 0 else path,
        role=role,
        name=name,
        description=description,
        value=value,
        rect=rect,
        states=states,
        actions=actions,
        app_id=app_id,
        path=path,
        children=children,
    )


def dump_tree(app_id: Optional[str] = None, max_nodes: int = 400, timeout_s: float = 8.0) -> Optional[UIElement]:
    """Dump the accessibility tree of an app (focused app when app_id is None).

    Returns None when AT-SPI is unavailable, the app is not registered, or the
    deadline elapses before the root is produced. May return a partial tree
    (bounded by max_nodes/timeout_s) rather than blocking.
    """
    if not _HAS_ATSPI:
        return None
    name, app = find_app(app_id)
    if app is None:
        return None
    try:
        budget = _Budget(max_nodes, timeout_s)
        root = _build(app, [], name or (app_id or ""), budget, seen=set())
        return root
    except Exception:  # noqa: BLE001 - never raise into the daemon
        return None


def find_elements(root: Optional[UIElement], role: Optional[str] = None, name: Optional[str] = None) -> list[UIElement]:
    """Walk a dumped tree and filter by (substring) role and/or name."""
    if root is None:
        return []
    role_cf = role.casefold() if role else None
    name_cf = name.casefold() if name else None
    out: list[UIElement] = []
    for el in root.walk():
        if role_cf and role_cf not in (el.role or "").casefold():
            continue
        if name_cf and name_cf not in (el.name or "").casefold():
            continue
        out.append(el)
    return out


def resolve_path(path: str):
    """Resolve a `dump_tree` path (`<app name>#<i>.<j>...`) back to an accessible.

    Returns (app_name, accessible) or (None, None).
    """
    if not _HAS_ATSPI or not path or "#" not in path:
        return None, None
    app_part, idx_part = path.split("#", 1)
    name, node = find_app(app_part)
    if node is None:
        return None, None
    if idx_part:
        for tok in idx_part.split("."):
            if not tok:
                continue
            node = _safe(lambda tok=tok: node.get_child_at_index(int(tok)))
            if node is None:
                return None, None
    return name, node


__all__ = [
    "dump_tree",
    "find_elements",
    "find_app",
    "resolve_path",
]
