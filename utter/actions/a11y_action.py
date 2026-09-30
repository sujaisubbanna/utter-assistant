"""Invoke an AT-SPI action on a node previously found via `context.atspi`.

`path` is the stable path stored on `types.UIElement.path`
(`<app name>#<i>.<j>...`). The tree is re-resolved at invoke time so we never
act on a stale handle.
"""
from __future__ import annotations

import time

from utter.types import Action, ActionResult, Tier

# Preference order when the requested action name is not present verbatim.
_FALLBACKS = ("click", "activate", "press", "do", "invoke")


def _choose_action(available: list[str], requested: str) -> tuple[int, str] | None:
    if not available:
        return None
    req = (requested or "click").casefold()
    for i, name in enumerate(available):
        if name.casefold() == req:
            return i, name
    for i, name in enumerate(available):
        if req in name.casefold() or name.casefold() in req:
            return i, name
    for want in _FALLBACKS:
        for i, name in enumerate(available):
            if want in name.casefold():
                return i, name
    return 0, available[0]


def invoke(path: str, action: str = "click") -> ActionResult:
    """Perform an AT-SPI action (`do_action`) on the node at `path`."""
    t0 = time.perf_counter()
    if not path:
        return ActionResult(False, Action.CLICK_ELEMENT, Tier.A11Y, "empty path",
                            (time.perf_counter() - t0) * 1000)
    try:
        from utter.context import atspi
    except Exception as e:  # noqa: BLE001
        return ActionResult(False, Action.CLICK_ELEMENT, Tier.A11Y,
                            f"atspi unavailable: {e}",
                            (time.perf_counter() - t0) * 1000)

    app_name, node = atspi.resolve_path(path)
    if node is None:
        return ActionResult(False, Action.CLICK_ELEMENT, Tier.A11Y,
                            f"node not found: {path}",
                            (time.perf_counter() - t0) * 1000)

    iface = atspi._safe(node.get_action_iface)
    if iface is None:
        return ActionResult(False, Action.CLICK_ELEMENT, Tier.A11Y,
                            "node exposes no Action interface",
                            (time.perf_counter() - t0) * 1000)

    available: list[str] = []
    for i in range(atspi._safe(iface.get_n_actions, 0) or 0):
        name = atspi._safe(lambda i=i: iface.get_action_name(i))
        if name:
            available.append(str(name))
    chosen = _choose_action(available, action)
    if chosen is None:
        return ActionResult(False, Action.CLICK_ELEMENT, Tier.A11Y,
                            "no actions available",
                            (time.perf_counter() - t0) * 1000)

    idx, name = chosen
    ok = bool(atspi._safe(lambda: iface.do_action(idx), False))
    detail = f"{app_name}: {name} on {path}"
    return ActionResult(ok, Action.CLICK_ELEMENT, Tier.A11Y, detail,
                        (time.perf_counter() - t0) * 1000)


__all__ = ["invoke"]
