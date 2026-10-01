"""Desktop context on macOS: focused app + window, window list, monitors.

Sources (all via PyObjC, imported lazily):
    * ``NSWorkspace.sharedWorkspace().frontmostApplication()`` -> focused app
      (bundle id, pid, localized name);
    * Accessibility ``AXUIElementCreateApplication(pid)`` ->
      ``kAXFocusedWindowAttribute`` -> ``kAXTitleAttribute`` (needs the
      Accessibility permission; degrades to an empty title without it);
    * ``CGWindowListCopyWindowInfo`` -> on-screen windows (title, owner, pid);
    * ``NSScreen.screens()`` -> monitors in global top-left points.

The ``app_id`` reported is the **bundle identifier** (``com.apple.Safari``),
falling back to the localized app name. Window ids are ``kCGWindowNumber``.

Everything is best-effort and never raises into the daemon loop. On Linux this
module is importable but every provider returns empty results.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Optional

from utter.types import Context, FocusedWindow, Monitor, Rect, WindowInfo

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0


def _appkit():
    import AppKit  # type: ignore[import-not-found]

    return AppKit


def _front_app() -> Optional[Any]:
    try:
        return _appkit().NSWorkspace.sharedWorkspace().frontmostApplication()
    except Exception as exc:  # noqa: BLE001
        logger.debug("frontmostApplication failed: %s", exc)
        return None


def app_identifier(app: Any) -> str:
    """Bundle id if present, else the localized name (pure helper)."""
    if app is None:
        return ""
    for getter in ("bundleIdentifier", "localizedName"):
        try:
            value = getattr(app, getter)()
        except Exception:  # noqa: BLE001
            value = None
        if value:
            return str(value)
    return ""


def ax_focused_window_title(pid: int) -> tuple[str, int]:
    """``(title, window_number)`` of ``pid``'s focused window via Accessibility."""
    try:
        import ApplicationServices as AS  # type: ignore[import-not-found]
    except ImportError:
        return "", 0
    try:
        app = AS.AXUIElementCreateApplication(int(pid))
        err, win = AS.AXUIElementCopyAttributeValue(app, AS.kAXFocusedWindowAttribute, None)
        if err != 0 or win is None:
            return "", 0
        err, title = AS.AXUIElementCopyAttributeValue(win, AS.kAXTitleAttribute, None)
        title_s = str(title) if err == 0 and title else ""
        number = 0
        try:  # private but widely used; harmless if missing
            err, num = AS._AXUIElementGetWindow(win, None)  # type: ignore[attr-defined]
            if err == 0 and num:
                number = int(num)
        except Exception:  # noqa: BLE001
            pass
        return title_s, number
    except Exception as exc:  # noqa: BLE001
        logger.debug("AX focused window failed: %s", exc)
        return "", 0


def focused_window() -> Optional[FocusedWindow]:
    app = _front_app()
    if app is None:
        return None
    try:
        pid = int(app.processIdentifier())
    except Exception:  # noqa: BLE001
        pid = 0
    title, number = ax_focused_window_title(pid) if pid else ("", 0)
    if not title:
        # Fall back to the frontmost layer-0 window of that pid in the window list.
        for w in _raw_windows():
            if int(w.get("pid") or 0) == pid and w.get("title"):
                title, number = str(w["title"]), int(w.get("id") or 0)
                break
    return FocusedWindow(app_id=app_identifier(app), title=title, pid=pid, window_id=number)


def _raw_windows() -> list[dict]:
    try:
        import Quartz  # type: ignore[import-not-found]

        infos = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("CGWindowListCopyWindowInfo failed: %s", exc)
        return []
    out: list[dict] = []
    for info in infos:
        try:
            if int(info.get("kCGWindowLayer", 0)) != 0:
                continue  # menu bar, dock, overlays
            out.append({
                "id": int(info.get("kCGWindowNumber", 0)),
                "pid": int(info.get("kCGWindowOwnerPID", 0)),
                "owner": str(info.get("kCGWindowOwnerName") or ""),
                "title": str(info.get("kCGWindowName") or ""),
                "bounds": dict(info.get("kCGWindowBounds") or {}),
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def _bundle_ids_by_pid() -> dict[int, str]:
    table: dict[int, str] = {}
    try:
        for app in _appkit().NSWorkspace.sharedWorkspace().runningApplications():
            try:
                table[int(app.processIdentifier())] = app_identifier(app)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return table


def list_windows() -> list[WindowInfo]:
    bundles = _bundle_ids_by_pid()
    front = _front_app()
    front_pid = int(front.processIdentifier()) if front is not None else -1
    out: list[WindowInfo] = []
    for w in _raw_windows():
        out.append(WindowInfo(
            id=w["id"], app_id=bundles.get(w["pid"]) or w["owner"], title=w["title"],
            workspace_id=0, pid=w["pid"], is_focused=(w["pid"] == front_pid),
        ))
    return out


def find_windows(app_id: Optional[str] = None, title_contains: Optional[str] = None) -> list[WindowInfo]:
    app_needle = app_id.lower() if app_id else None
    title_needle = title_contains.lower() if title_contains else None
    result: list[WindowInfo] = []
    for w in list_windows():
        if app_needle is not None and app_needle not in w.app_id.lower():
            continue
        if title_needle is not None and title_needle not in w.title.lower():
            continue
        result.append(w)
    return result


def list_monitors() -> list[Monitor]:
    monitors: list[Monitor] = []
    try:
        AppKit = _appkit()
        screens = list(AppKit.NSScreen.screens() or [])
        main_h = screens[0].frame().size.height if screens else 0
        main = AppKit.NSScreen.mainScreen()
        for idx, screen in enumerate(screens):
            fr = screen.frame()
            # NSScreen is bottom-left origin; convert to top-left global points.
            top = int(main_h - (fr.origin.y + fr.size.height))
            monitors.append(Monitor(
                id=idx, output=f"display-{idx}", is_focused=(screen == main),
                geometry=Rect(int(fr.origin.x), top, int(fr.size.width), int(fr.size.height)),
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("NSScreen failed: %s", exc)
    return monitors


def ax_raise_window(pid: int, window_id: int, title: Optional[str] = None) -> bool:
    """Raise a specific window of ``pid`` via Accessibility ``kAXRaiseAction``."""
    try:
        import ApplicationServices as AS  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        app = AS.AXUIElementCreateApplication(int(pid))
        if app is None:
            return False
        err, windows = AS.AXUIElementCopyAttributeValue(app, AS.kAXWindowsAttribute, None)
        if err != 0 or not windows:
            return False
        target_win = None
        for win in windows:
            try:
                err, num = AS._AXUIElementGetWindow(win, None)  # type: ignore[attr-defined]
                if err == 0 and num and int(num) == int(window_id):
                    target_win = win
                    break
            except Exception:  # noqa: BLE001
                pass
            if target_win is None and title:
                try:
                    err, w_title = AS.AXUIElementCopyAttributeValue(win, AS.kAXTitleAttribute, None)
                    if err == 0 and w_title and str(w_title) == str(title):
                        target_win = win
                except Exception:  # noqa: BLE001
                    pass
        if target_win is not None:
            action_err = AS.AXUIElementPerformAction(target_win, AS.kAXRaiseAction)
            return action_err == 0
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug("ax_raise_window pid=%s wid=%s failed: %s", pid, window_id, exc)
        return False


def close_window(window_id: int):
    """Close a specific window via Accessibility ``kAXCloseAction`` (experimental).

    Never focuses and never raises. Returns an
    :class:`~utter.context.compositor.Outcome` so callers can tell a real close
    from a platform/PyObjC that cannot (``unsupported=True``) and fall back.
    """
    from utter.context.compositor import Outcome

    def _unsupported(reason: str) -> "Outcome":
        return Outcome.unsupported_for("macos", "close", reason)

    try:
        import ApplicationServices as AS  # type: ignore[import-not-found]
    except ImportError:
        return _unsupported("PyObjC ApplicationServices not installed")
    try:
        wid = int(window_id)
    except (TypeError, ValueError):
        return Outcome(False, f"bad window id {window_id!r}", backend="macos", capability="close")
    if not hasattr(AS, "AXUIElementPerformAction"):
        return _unsupported("AXUIElementPerformAction unavailable")
    close_action = getattr(AS, "kAXCloseAction", "AXClose")
    try:
        target = next((w for w in _raw_windows() if w["id"] == wid), None)
        if target is None:
            return Outcome(False, f"window {wid} not found", backend="macos", capability="close")
        pid = int(target["pid"])
        app = AS.AXUIElementCreateApplication(pid)
        if app is None:
            return Outcome(False, f"no AX app for pid {pid}", backend="macos", capability="close")
        err, windows = AS.AXUIElementCopyAttributeValue(app, AS.kAXWindowsAttribute, None)
        if err != 0 or not windows:
            return Outcome(False, f"no AX windows for pid {pid}", backend="macos", capability="close")
        for win in windows:
            try:
                werr, num = AS._AXUIElementGetWindow(win, None)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                continue
            if werr == 0 and num and int(num) == wid:
                action_err = AS.AXUIElementPerformAction(win, close_action)
                if action_err == 0:
                    return Outcome(True, f"closed window {wid}", backend="macos", capability="close")
                return Outcome(False, f"AXClose failed ({action_err})",
                               backend="macos", capability="close")
        return Outcome(False, f"window {wid} not found in AX list",
                       backend="macos", capability="close")
    except Exception as exc:  # noqa: BLE001
        logger.debug("close_window pid=%s failed: %s", window_id, exc)
        return _unsupported(f"close failed: {exc}")


def focus_window(window_id: int) -> bool:
    """Activate the app owning ``window_id`` and raise the specific window via AX."""
    try:
        wid = int(window_id)
    except (TypeError, ValueError):
        return False
    target = next((w for w in _raw_windows() if w["id"] == wid), None)
    if target is None:
        return False
    pid = int(target["pid"])
    app_ok = activate_pid(pid)
    ax_ok = ax_raise_window(pid, wid, title=target.get("title"))
    return app_ok or ax_ok


def activate_pid(pid: int) -> bool:
    try:
        AppKit = _appkit()
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        if app is None:
            return False
        return bool(app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps))
    except Exception as exc:  # noqa: BLE001
        logger.debug("activate pid %s failed: %s", pid, exc)
        return False


def focus_window_on_workspace(window_id: int) -> bool:
    # Spaces cannot be switched programmatically without private APIs;
    # activating the app makes macOS switch to the Space holding its window.
    return focus_window(window_id)


def activate_app(name_or_bundle: str) -> bool:
    """Bring an app to the front by bundle id or name (``open -b`` / ``open -a``)."""
    spec = (name_or_bundle or "").strip()
    if not spec:
        return False
    flag = "-b" if "." in spec and " " not in spec else "-a"
    try:
        proc = subprocess.run(["open", flag, spec], capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def build_context(with_a11y: bool = False) -> Context:
    from utter.macos.clipboard import get_clipboard

    return Context(
        focused=focused_window(),
        monitors=list_monitors(),
        windows=list_windows(),
        clipboard=get_clipboard(),
        a11y=None,  # AX tree dumps are not wired yet (see docs/MACOS.md)
    )


__all__ = ["focused_window", "list_windows", "find_windows", "list_monitors", "focus_window",
           "focus_window_on_workspace", "activate_pid", "activate_app", "build_context",
           "app_identifier", "ax_focused_window_title", "ax_raise_window", "close_window"]
