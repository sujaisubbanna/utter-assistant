"""Platform-neutral text-field detection (Phase 0 of the field chooser).

This module answers two questions without any UI:

* :func:`focused_text_field` — which text input currently has keyboard focus;
* :func:`list_text_fields`  — which text inputs exist in the focused app/window.

It is the only place that turns a platform accessibility tree into
:class:`~utter.types.TextFieldCandidate` values. Linux uses AT-SPI
(:mod:`utter.context.atspi`), macOS a bounded AX walk
(:mod:`utter.macos.axtree`) and Windows a bounded UI Automation walk
(:mod:`utter.win32.axtree`). All degrade to an empty list and say *why* through
:func:`detection_status`.

Design rules (the des-2 field-picker spec):

* a text input is a small set of roles that is editable/focusable and not
  disabled/hidden/zero-size (:func:`is_text_input`);
* candidates rank focused element first, then the focused app/window, then the
  rest; ties keep enumeration order (stable);
* enumeration is capped at 27 candidates and a ~1.5 s aggregate deadline;
* nothing here raises — callers always get a list (possibly empty).

This module is additive: it does not touch the dictation path in ``daemon.py``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from utter import platform
from utter.types import TextFieldCandidate, UIElement

MAX_CANDIDATES = 27
MAX_OTHER_WINDOWS = 3
DEFAULT_DEADLINE_S = 1.5
_MAX_NODES_PER_TREE = 400
_MAC_MAX_NODES = 200


# --- predicate --------------------------------------------------------------

def _norm_token(value) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").casefold()
    return " ".join(text.split())


# AT-SPI roles plus their macOS AX equivalents, normalized (lower case, spaces
# collapsed). ``axstatictext``/``static text`` are deliberately absent: a label
# is never an editable target.
_TEXT_ROLES = frozenset({
    # AT-SPI 2.0
    "entry", "text entry", "password text", "combo box", "text", "document text",
    # macOS Accessibility
    "axtextfield", "axtextarea", "axcombobox", "axsearchfield", "axsecuretextfield",
    # de-facto toolkit spellings
    "text field", "text area", "search field", "secure text field", "input",
})

# A candidate must be usable: editable, or at least focusable.
_INPUT_STATES = frozenset({"editable", "focusable"})

# States that disqualify a node outright.
_BLOCKED_STATES = frozenset({
    "disabled", "insensitive", "hidden", "invisible", "defunct", "unavailable",
})

_FOCUSED_STATES = frozenset({"focused", "active"})


def is_text_input(role, states) -> bool:
    """True when ``role``/``states`` describe an editable/focusable text input.

    Platform-neutral: accepts AT-SPI role names (``entry``, ``combo box``, ...)
    and macOS AX roles (``AXTextField``, ``AXSecureTextField``, ...). The role
    must be a text-input role and carry ``editable`` or ``focusable``; any
    disabled/hidden/defunct state rejects it. Size is checked separately by the
    caller, which has the rect.
    """
    role_token = _norm_token(role)
    if role_token not in _TEXT_ROLES:
        return False
    state_set = {_norm_token(s) for s in (states or [])}
    if state_set & _BLOCKED_STATES:
        return False
    return bool(state_set & _INPUT_STATES)


# --- probe result -----------------------------------------------------------

@dataclass
class ProbeResult:
    """Internal result: candidates + whether the mechanism ran + why."""
    candidates: list[TextFieldCandidate] = field(default_factory=list)
    available: bool = False
    reason: str = "unknown"


# --- shared collection + ranking --------------------------------------------

def _focused_window_snapshot():
    """Focused window via the platform seam, or None (never raises)."""
    try:
        from utter.context import desktop
        return desktop.focused_window()
    except Exception:  # noqa: BLE001 - detection must never raise
        return None


def _as_candidate(el: UIElement, *, app_id: str, app_name: str, pid: int,
                  window_id: int) -> Optional[TextFieldCandidate]:
    if not is_text_input(el.role, el.states):
        return None
    rect = el.rect
    if rect is None or rect.w <= 0 or rect.h <= 0:
        return None  # zero-size / no geometry: not a usable target
    states = {_norm_token(s) for s in (el.states or [])}
    return TextFieldCandidate(
        app_id=app_id or el.app_id or "",
        pid=int(pid or 0),
        window_id=int(window_id or 0),
        path=el.path or el.id or "",
        role=el.role or "",
        name=el.name or "",
        label=el.description or el.name or "",
        rect=rect,
        focused=bool(states & _FOCUSED_STATES),
        app_name=app_name or app_id or "",
    )


def _collect(root: UIElement, *, primary: bool, app_id: str, app_name: str,
             pid: int, window_id: int, seq_start: int = 0):
    """Flatten one tree into ``(group, seq, candidate)`` ranking entries.

    ``group`` is 0 for the focused element, 1 for a primary (focused app/window)
    candidate, 2 for the rest. ``seq`` preserves enumeration order within a
    group (stable sort).
    """
    entries: list[tuple[int, int, TextFieldCandidate]] = []
    seq = seq_start
    for el in root.walk():
        cand = _as_candidate(el, app_id=app_id, app_name=app_name, pid=pid,
                             window_id=window_id)
        if cand is None:
            continue
        group = 0 if cand.focused else (1 if primary else 2)
        entries.append((group, seq, cand))
        seq += 1
    return entries, seq


def _rank(entries) -> list[TextFieldCandidate]:
    entries = sorted(entries, key=lambda item: (item[0], item[1]))
    return [cand for _, _, cand in entries]


# --- Linux / AT-SPI ---------------------------------------------------------

def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _other_app_ids(focused, own_app_id: str) -> list[str]:
    """Distinct app ids (at most :data:`MAX_OTHER_WINDOWS`) besides the focused one."""
    skip = {str(own_app_id or "").casefold()}
    if focused is not None and getattr(focused, "app_id", ""):
        skip.add(str(focused.app_id).casefold())
    out: list[str] = []
    seen = set(skip)
    try:
        from utter.context import desktop
        windows = desktop.list_windows()
    except Exception:  # noqa: BLE001
        return []
    for win in windows:
        app = str(getattr(win, "app_id", "") or "")
        if not app:
            continue
        key = app.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(app)
        if len(out) >= MAX_OTHER_WINDOWS:
            break
    return out


def _atspi():
    """Import seam for :mod:`utter.context.atspi` (tests replace this)."""
    from utter.context import atspi
    return atspi


def _linux_probe(app_id, include_windows: bool, deadline: float) -> ProbeResult:
    atspi = _atspi()

    if not getattr(atspi, "_HAS_ATSPI", False):
        return ProbeResult([], False, "atspi-unavailable")

    focused = _focused_window_snapshot()
    primary_app = app_id or (getattr(focused, "app_id", "") if focused else "")
    tree = atspi.dump_tree(app_id, max_nodes=_MAX_NODES_PER_TREE,
                           timeout_s=max(0.05, _remaining(deadline)))
    if tree is None:
        return ProbeResult([], True, "no-a11y-tree")

    roots: list[tuple[bool, UIElement, str]] = [(True, tree, primary_app or tree.app_id)]
    if include_windows:
        for other in _other_app_ids(focused, primary_app):
            if _remaining(deadline) <= 0:
                break
            other_tree = atspi.dump_tree(other, max_nodes=_MAX_NODES_PER_TREE,
                                         timeout_s=max(0.05, _remaining(deadline)))
            if other_tree is not None:
                roots.append((False, other_tree, other))

    # pid/window_id only describe the focused app's window; explicit app_id
    # dumps of another app must not inherit them.
    pid = int(getattr(focused, "pid", 0) or 0)
    wid = int(getattr(focused, "window_id", 0) or 0)
    if app_id and focused is not None and app_id != getattr(focused, "app_id", ""):
        pid = wid = 0

    entries: list[tuple[int, int, TextFieldCandidate]] = []
    seq = 0
    for primary, root, app in roots:
        collected, seq = _collect(
            root, primary=primary, app_id=app, app_name=app,
            pid=pid if primary else 0, window_id=wid if primary else 0,
            seq_start=seq)
        entries.extend(collected)

    candidates = _rank(entries)[:MAX_CANDIDATES]
    return ProbeResult(candidates, True, "ok" if candidates else "no-text-fields")


# --- macOS / Accessibility --------------------------------------------------

def _axtree():
    """Import seam for :mod:`utter.macos.axtree` (tests replace this)."""
    from utter.macos import axtree
    return axtree


def _macos_probe(app_id, include_windows: bool, deadline: float) -> ProbeResult:
    axtree = _axtree()
    ok, reason = axtree.available()
    if not ok:
        return ProbeResult([], False, reason)

    focused = _focused_window_snapshot()
    pid = int(getattr(focused, "pid", 0) or 0) or int(axtree.front_pid() or 0)
    if not pid:
        return ProbeResult([], True, "no-ax-tree")
    app = app_id or (getattr(focused, "app_id", "") if focused else "")
    wid = int(getattr(focused, "window_id", 0) or 0)

    def _dump():
        return axtree.dump_focused_tree(pid, app_id=app, max_nodes=_MAC_MAX_NODES,
                                        deadline_s=max(0.05, _remaining(deadline)))

    tree = _dump()
    entries: list[tuple[int, int, TextFieldCandidate]] = []
    if tree is not None:
        entries, _ = _collect(tree, primary=True, app_id=app, app_name=app,
                              pid=pid, window_id=wid)

    if not entries and axtree.is_electron(pid):
        # Chromium/Electron builds no AX tree until the flag is set: try once.
        enabled = False
        try:
            enabled = bool(axtree.enable_manual_accessibility(pid))
        except Exception:  # noqa: BLE001
            enabled = False
        if enabled and _remaining(deadline) > 0:
            tree = _dump()
            if tree is not None:
                entries, _ = _collect(tree, primary=True, app_id=app, app_name=app,
                                      pid=pid, window_id=wid)
        if not entries:
            return ProbeResult([], True, "electron-ax-disabled")

    if tree is None:
        return ProbeResult([], True, "no-ax-tree")
    candidates = _rank(entries)[:MAX_CANDIDATES]
    return ProbeResult(candidates, True, "ok" if candidates else "no-text-fields")


# --- Windows / UI Automation -------------------------------------------------

def _winaxtree():
    """Import seam for :mod:`utter.win32.axtree` (tests replace this)."""
    from utter.win32 import axtree
    return axtree


def _windows_probe(app_id, include_windows: bool, deadline: float) -> ProbeResult:
    axtree = _winaxtree()
    ok, reason = axtree.available()
    if not ok:
        return ProbeResult([], False, reason)

    focused = _focused_window_snapshot()
    primary_app = app_id or (getattr(focused, "app_id", "") if focused else "")
    tree = axtree.dump_tree(primary_app or None, max_nodes=_MAX_NODES_PER_TREE,
                            timeout_s=max(0.05, _remaining(deadline)))
    if tree is None:
        return ProbeResult([], True, "no-a11y-tree")

    roots: list[tuple[bool, UIElement, str]] = [(True, tree, primary_app or tree.app_id)]
    if include_windows:
        for other in _other_app_ids(focused, primary_app):
            if _remaining(deadline) <= 0:
                break
            other_tree = axtree.dump_tree(other, max_nodes=_MAX_NODES_PER_TREE,
                                          timeout_s=max(0.05, _remaining(deadline)))
            if other_tree is not None:
                roots.append((False, other_tree, other))

    pid = int(getattr(focused, "pid", 0) or 0)
    wid = int(getattr(focused, "window_id", 0) or 0)
    if app_id and focused is not None and app_id != getattr(focused, "app_id", ""):
        pid = wid = 0

    entries: list[tuple[int, int, TextFieldCandidate]] = []
    seq = 0
    for primary, root, app in roots:
        collected, seq = _collect(
            root, primary=primary, app_id=app, app_name=app,
            pid=pid if primary else 0, window_id=wid if primary else 0,
            seq_start=seq)
        entries.extend(collected)

    candidates = _rank(entries)[:MAX_CANDIDATES]
    return ProbeResult(candidates, True, "ok" if candidates else "no-text-fields")


# --- public API -------------------------------------------------------------

def probe(app_id=None, *, include_windows: bool = True,
          deadline_s: float = DEFAULT_DEADLINE_S) -> ProbeResult:
    """Run the platform probe once and return candidates + status (never raises)."""
    deadline = time.monotonic() + max(0.0, float(deadline_s))
    try:
        if platform.is_macos():
            return _macos_probe(app_id, include_windows, deadline)
        if platform.is_windows():
            return _windows_probe(app_id, include_windows, deadline)
        return _linux_probe(app_id, include_windows, deadline)
    except Exception:  # noqa: BLE001 - a probe failure is an empty result
        return ProbeResult([], False, "error")


def list_text_fields(app_id=None, *, include_windows: bool = True,
                     deadline_s: float = DEFAULT_DEADLINE_S) -> list[TextFieldCandidate]:
    """Enumerate text inputs, best-first, capped at :data:`MAX_CANDIDATES`.

    Focused element first, then the focused app/window, then at most three other
    windows/apps; bounded by ``deadline_s``. Never raises — returns ``[]``.
    """
    try:
        return probe(app_id, include_windows=include_windows,
                     deadline_s=deadline_s).candidates
    except Exception:  # noqa: BLE001
        return []


def focused_text_field() -> Optional[TextFieldCandidate]:
    """The focused text input, or ``None`` when nothing reports focus.

    Strict by design: callers that want a best-effort target should use
    ``list_text_fields()[0]`` instead.
    """
    try:
        for cand in list_text_fields():
            if cand.focused:
                return cand
    except Exception:  # noqa: BLE001
        pass
    return None


def detection_status(*, deadline_s: float = DEFAULT_DEADLINE_S) -> dict:
    """Why did detection return what it did? ``{available, platform, reason, count}``.

    ``available`` says whether the platform mechanism could run at all; ``reason``
    is one of:

    * ``ok`` / ``no-text-fields`` — mechanism ran (tree present or not).
    * ``atspi-unavailable`` — Linux without the optional AT-SPI import.
    * ``no-a11y-tree`` — AT-SPI app not registered / Electron without the flag.
    * ``ax-unavailable`` / ``permission-denied`` — macOS without PyObjC AX or
      Accessibility permission.
    * ``electron-ax-disabled`` — macOS Chromium app exposes no AX tree even
      after :func:`AXManualAccessibility` was requested.
    * ``no-ax-tree`` — macOS app has no focused window/element.
    * ``win-unavailable`` — Windows backend used off Windows.
    * ``uiautomation-unavailable`` — Windows without the optional UI Automation
      package.
    * ``error`` — the probe raised and was swallowed.
    """
    try:
        result = probe(deadline_s=deadline_s)
    except Exception:  # noqa: BLE001
        result = ProbeResult([], False, "error")
    return {
        "available": result.available,
        "platform": "darwin" if platform.is_macos() else platform.name(),
        "reason": result.reason,
        "count": len(result.candidates),
    }


__all__ = [
    "MAX_CANDIDATES",
    "DEFAULT_DEADLINE_S",
    "ProbeResult",
    "is_text_input",
    "probe",
    "list_text_fields",
    "focused_text_field",
    "detection_status",
]
