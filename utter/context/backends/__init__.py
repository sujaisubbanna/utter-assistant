"""Compositor backends (selected by :mod:`utter.context.compositor`).

Every backend is a *module* exposing the same functions, so the rest of the
assistant is written once against ``compositor.active()``:

    NAME                                     "niri" | "kwin" | "unknown"
    available() -> bool                      tooling for this backend is present
    capabilities() -> dict[str, bool]        see compositor.CAPABILITIES
    tools() -> dict[str, str | None]         which(...) probes, for diagnostics

    focused_window() -> FocusedWindow | None
    list_windows() -> list[WindowInfo]
    find_windows(app_id=None, title_contains=None) -> list[WindowInfo]
    list_monitors() -> list[Monitor]
    focus_window(window_id) -> bool
    focus_window_on_workspace(window_id) -> bool
    build_context(with_a11y=False) -> Context

    close_window(window_id=None) -> Outcome
    minimize_window(window_id=None) -> Outcome
    maximize_window(window_id=None) -> Outcome
    move_window_to_workspace(workspace, window_id=None) -> Outcome
    switch_workspace(workspace) -> Outcome
    screenshot(path=None, output=None) -> (png_path, Rect)   raises CompositorUnsupported
    run_action(command, args=()) -> Outcome                  niri-style action name
    plan_action(command, args=()) -> list[list[str]]         argv it would run (dry-run)
    plan() -> dict                                           argv per capability (dry-run)

``window_id`` is always an ``int`` (niri's native id; KWin UUIDs are mapped to
stable ints inside the kwin backend). A missing capability returns
``Outcome(unsupported=True)``, never raises. Only ``screenshot`` raises, because
it has to return a value.
"""
from __future__ import annotations

__all__ = ["niri", "kwin", "fallback", "dbus"]
