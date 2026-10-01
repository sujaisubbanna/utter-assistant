"""Step executor with tier escalation.

Executes a Plan. For CLICK_ELEMENT it escalates: accessibility tree (T1) ->
vision grounding (T3). Never acts on a stale target: context is re-read between
steps.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from .types import Action, ActionResult, Context, Plan, Step, Tier

log = logging.getLogger("utter.executor")


class Executor:
    def __init__(self, ctx_builder: Callable[..., Context], cfg):
        self.ctx_builder = ctx_builder
        self.cfg = cfg

    # -- public ------------------------------------------------------------
    def execute_plan(self, plan: Plan) -> list[ActionResult]:
        results: list[ActionResult] = []
        log.info("plan(%s): %s", plan.source,
                 " -> ".join(f"{s.action.value}{s.args}" for s in plan.steps))
        for step in plan.steps:
            res = self.execute_step(step)
            results.append(res)
            if not res.ok:
                log.warning("step failed: %s (%s)", step.action.value, res.detail)
                break
            time.sleep(0.05)
        return results

    def execute_step(self, step: Step) -> ActionResult:
        t0 = time.perf_counter()
        try:
            handler = getattr(self, f"_do_{step.action.value}", None)
            if handler is None:
                return ActionResult(False, step.action, step.tier, "no handler")
            res = handler(step)
            res.latency_ms = (time.perf_counter() - t0) * 1000
            if res.detail:
                log.info("%s: %s (%.0fms)", step.action.value, res.detail, res.latency_ms)
            return res
        except Exception as e:  # noqa: BLE001
            return ActionResult(False, step.action, step.tier, f"error: {e}",
                                (time.perf_counter() - t0) * 1000)

    # -- handlers ----------------------------------------------------------
    def _do_open_url(self, step: Step) -> ActionResult:
        from .actions import launch
        return launch.open_url(step.args["url"])

    def _do_launch_app(self, step: Step) -> ActionResult:
        from .actions import launch
        return launch.launch_app(step.args.get("argv") or step.args["app"])

    def _do_focus_app(self, step: Step) -> ActionResult:
        from .context import desktop
        app = step.args["app"]
        for win in _list_windows():
            if win.get("app_id") == app:
                ok = desktop.focus_window(win["id"])
                return ActionResult(ok, step.action, Tier.APP, f"focus {app}")
        return ActionResult(False, step.action, Tier.APP, f"{app} not running")

    def _do_key(self, step: Step) -> ActionResult:
        from .actions import keyboard
        # macOS: a targeted window is injected natively to its pid (no focus
        # change). On Linux this is always None, so the focused/round-trip path
        # is untouched.
        return keyboard.send_key(step.args["chord"], pid=self._macos_target_pid(step))

    def _do_type_text(self, step: Step) -> ActionResult:
        from .actions import keyboard
        return keyboard.type_text(step.args["text"], pid=self._macos_target_pid(step))

    def _do_scroll(self, step: Step) -> ActionResult:
        from .actions import mouse
        return mouse.scroll(step.args.get("direction", "down"), step.args.get("amount", 5))

    # -- native macOS background input -------------------------------------
    def _macos_target_pid(self, step: Step) -> Optional[int]:
        """PID to background-post to on macOS, or ``None`` for focused input.

        Experimental native macOS alternative to the Wayland focus round-trip:
        when a step targets a window (``args.window_id`` / ``args.app``) and the
        installed PyObjC exposes ``CGEventPostToPid``, return that window's pid
        so the key/text is posted straight to the process **without changing
        focus**. On Linux (or when the API is unavailable) this returns ``None``
        and the caller falls back to the existing focused post. Never raises.
        """
        try:
            from . import platform as _platform
            if not _platform.is_macos():
                return None
            if step.args.get("window_id") is None and step.args.get("app") is None:
                return None
            from .macos import inject
            if not inject.background_post_supported():
                log.debug("macOS background pid-post unsupported; falling back to focus")
                return None
            target = self._macos_target_window(step)
            pid = int(getattr(target, "pid", 0) or 0)
            return pid or None
        except Exception as exc:  # noqa: BLE001
            log.debug("macOS target pid resolution failed: %s", exc)
            return None

    def _macos_target_window(self, step: Step):
        """The :class:`WindowInfo` a targeted step refers to, or ``None``."""
        try:
            from .context import desktop
        except Exception:  # noqa: BLE001
            return None
        window_id = step.args.get("window_id")
        if window_id is not None:
            try:
                wid = int(window_id)
            except (TypeError, ValueError):
                return None
            for w in desktop.list_windows() or []:
                if int(getattr(w, "id", 0) or 0) == wid:
                    return w
            return None
        app = step.args.get("app")
        if app is None:
            return None
        found = desktop.find_windows(app_id=str(app)) or []
        for w in found:  # prefer the focused window of that app
            if getattr(w, "is_focused", False):
                return w
        return found[0] if found else None

    def _focus_window(self, window_id: int) -> None:
        """Focus a window (switching workspace first when the platform can)."""
        try:
            from .context import desktop as niri
        except Exception:
            return
        fn = getattr(niri, "focus_window_on_workspace", None) or getattr(niri, "focus_window", None)
        if fn is None:
            return
        try:
            fn(window_id)
        except Exception as e:  # noqa: BLE001
            log.debug("focus_window(%s) failed: %s", window_id, e)

    def _do_ensure_url(self, step: Step) -> ActionResult:
        """Context-aware 'open <site>': reuse an already-open tab/window if we can.

        1. focused browser already showing the site -> done
        2. another browser window showing the site -> focus it
        3. a browser is open -> open the URL in it, then focus that window
        4. no browser -> launch (xdg-open)
        """
        url = step.args["url"]
        site = step.args.get("site")
        prefer = step.args.get("app")
        kw = (site or _host_keyword(url) or "").lower()
        ctx = self.ctx_builder()
        windows = getattr(ctx, "windows", []) or []
        preferred = (getattr(getattr(self.cfg, "actions", None), "preferred_browser", "") or "").lower()
        prefer = prefer or preferred or None
        browsers = [w for w in windows if _is_browser_app(w.app_id, prefer)]
        if preferred:
            # A configured browser is the only one used; it is launched if closed.
            browsers = [w for w in browsers if preferred in (w.app_id or "").lower()]
        # The browser you're looking at wins over other open ones.
        focused_id = getattr(getattr(ctx, "focused", None), "id", None)
        browsers.sort(key=lambda w: w.id != focused_id)
        log.info("ensure_url %s (keyword=%r, browsers=%d)", url, kw, len(browsers))

        # 0. BiDi: exact detection across ALL tabs (incl. background) + activate.
        try:
            from .browser import zen
            if zen.is_up():
                tab = zen.activate_match(kw or url)
                if tab:
                    # BiDi selects the tab but does not raise the window on Wayland;
                    # ask niri to focus the browser window (title now matches the site).
                    try:
                        from .context import desktop as niri
                        cand = (niri.find_windows(app_id="zen", title_contains=kw)
                                or niri.find_windows(app_id="zen"))
                        if cand:
                            fn = getattr(niri, "focus_window_on_workspace", None) or niri.focus_window
                            fn(cand[0].id)
                    except Exception as e:  # noqa: BLE001
                        log.debug("niri focus after bidi failed: %s", e)
                    return ActionResult(True, Action.ENSURE_URL, Tier.APP,
                                        f"activated existing '{kw}' tab via BiDi: {tab.get('url', '')}")
        except Exception as e:  # noqa: BLE001
            log.debug("zen bidi lookup failed: %s", e)

        if ctx.focused and _is_browser_app(ctx.focused.app_id, prefer) and _title_has(ctx.focused.title, kw):
            return ActionResult(True, Action.ENSURE_URL, Tier.APP,
                                f"already on {kw} (focused window)")

        for w in browsers:
            if _title_has(w.title, kw):
                self._focus_window(w.id)
                return ActionResult(True, Action.ENSURE_URL, Tier.APP,
                                    f"focused existing '{kw}' window {w.id}")

        from .actions import launch
        opened = launch.open_url(url, browser_app_id=browsers[0].app_id if browsers else (preferred or None))
        detail = f"opened {url}"
        if browsers:
            self._focus_window(browsers[0].id)
            detail += f" in existing browser (win {browsers[0].id})"
        return ActionResult(opened.ok, Action.ENSURE_URL, Tier.APP, detail)

    def _do_ensure_app(self, step: Step) -> ActionResult:
        """Context-aware 'open <app>': focus an existing window, else launch."""
        app = step.args["app"]
        argv = step.args.get("argv")
        ctx = self.ctx_builder()
        for w in getattr(ctx, "windows", []) or []:
            if w.app_id == app or app.lower() in (w.app_id or "").lower():
                self._focus_window(w.id)
                return ActionResult(True, Action.ENSURE_APP, Tier.APP,
                                    f"focused existing {w.app_id} (win {w.id})")
        from .actions import launch
        res = launch.launch_app(argv or app)
        return ActionResult(res.ok, Action.ENSURE_APP, Tier.APP, f"launched {app}")

    def _do_search(self, step: Step) -> ActionResult:
        """Web search (decision head emits Action.SEARCH with a query)."""
        from urllib.parse import quote_plus
        from .actions import launch
        q = step.args.get("query") or step.args.get("q") or ""
        url = "https://duckduckgo.com/?q=" + quote_plus(str(q))
        res = launch.open_url(url)
        return ActionResult(res.ok, Action.SEARCH, Tier.APP, res.detail)

    def _do_terminal(self, step: Step) -> ActionResult:
        """Run a shell command: type it into a focused terminal, else open one."""
        cmd = step.args["command"]
        ctx = self.ctx_builder()
        app = (ctx.focused.app_id if ctx.focused else "").lower()
        is_term = app in {"foot", "alacritty", "kitty", "wezterm", "ghostty",
                          "konsole", "gnome-terminal", "xterm"} or "term" in app
        if is_term:
            from .actions import keyboard
            keyboard.type_text(cmd)
            if step.args.get("enter", True):
                keyboard.send_key("Return")
            return ActionResult(True, Action.TERMINAL, Tier.APP, f"terminal: {cmd}")
        from .actions import launch
        res = launch.launch_app(["foot", "-e", "bash", "-lc", cmd])
        return ActionResult(res.ok, Action.TERMINAL, Tier.APP, f"opened terminal: {cmd}")

    def _do_niri(self, step: Step) -> ActionResult:
        """Invoke a compositor action by its niri name.

        On niri this runs `niri msg action <command> [args...]` exactly as
        before; on KWin the name is mapped to a D-Bus call (kglobalaccel
        shortcut / virtual-desktop call). A missing mapping yields a
        structured ``unsupported`` result, never an exception.
        """
        from .context import compositor
        out = compositor.active().run_action(step.args["command"], step.args.get("args", []))
        res = ActionResult(out.ok, step.action, Tier.APP, out.detail)
        res.unsupported = bool(out.unsupported)
        return res

    def _do_media(self, step: Step) -> ActionResult:
        return _mpris(step.args.get("command", "play-pause"))

    def _do_click_point(self, step: Step) -> ActionResult:
        from .actions import mouse
        return mouse.click_point(int(step.args["x"]), int(step.args["y"]))

    def _do_wait(self, step: Step) -> ActionResult:
        time.sleep(step.args.get("ms", 300) / 1000)
        return ActionResult(True, step.action, step.tier, "waited")

    def _do_done(self, step: Step) -> ActionResult:
        return ActionResult(True, step.action, step.tier, "done")

    def _do_speak(self, step: Step) -> ActionResult:
        text = step.args.get("text", "")
        from . import platform
        if platform.is_macos():
            from .voice import tts
            tts.speak(text, self.cfg)
        return ActionResult(True, step.action, step.tier, text)

    # -- perception escalation --------------------------------------------
    def _do_click_element(self, step: Step) -> ActionResult:
        desc = step.args["description"]
        ctx = self.ctx_builder(with_a11y=False)

        # T1: accessibility tree
        a11y_res = self._try_a11y_click(desc)
        if a11y_res is not None:
            return a11y_res

        # T3: vision fallback
        return self._vision_click(desc, ctx)

    def _try_a11y_click(self, desc: str) -> Optional[ActionResult]:
        try:
            from .context import atspi
            from .actions import mouse
        except Exception:
            return None
        try:
            tree = atspi.dump_tree(max_nodes=400)
        except Exception as e:  # noqa: BLE001
            log.debug("a11y dump failed: %s", e)
            return None
        if tree is None:
            return None
        matches = atspi.find_elements(tree, name=desc)
        if not matches:
            return None
        # Prefer invoking the accessible action: robust on Wayland, where
        # component extents are window-relative (x=y=0) and unusable for clicks.
        invokable = [m for m in matches
                     if any(a in ("click", "activate", "press") for a in (m.actions or []))]
        if invokable:
            from .actions import a11y_action
            target = invokable[0]
            res = a11y_action.invoke(target.path, "click")
            res.tier = Tier.A11Y
            res.detail = f"a11y invoke '{target.name or target.role}'"
            if res.ok:
                return res
        # Coordinate click only when extents look absolute (non-zero origin).
        clickable = [m for m in matches if m.rect and (m.rect.x or m.rect.y)]
        if not clickable:
            return None
        target = min(clickable, key=lambda m: m.rect.w * m.rect.h)
        c = target.rect.center
        res = mouse.click_point(c.x, c.y)
        res.tier = Tier.A11Y
        res.detail = f"a11y '{target.name or target.role}' @({c.x},{c.y})"
        return res

    def _vision_click(self, desc: str, ctx: Context) -> ActionResult:
        if not getattr(self.cfg.vision, "enabled", True):
            return ActionResult(False, Action.CLICK_ELEMENT, Tier.VISION, "vision disabled")
        try:
            from .vision import client, screenshot
            path, geom = screenshot.capture()
            out = client.ground(path, desc, geom.w, geom.h)
        except Exception as e:  # noqa: BLE001
            return ActionResult(False, Action.CLICK_ELEMENT, Tier.VISION, f"vision error: {e}")
        points = out.get("points") if isinstance(out, dict) else None
        if not points:
            return ActionResult(False, Action.CLICK_ELEMENT, Tier.VISION,
                                f"no target for {desc!r}")
        from .actions import mouse
        p = points[0]
        # ground() returns coords relative to the captured output; offset by its origin
        res = mouse.click_point(int(p.x + geom.x), int(p.y + geom.y))
        res.tier = Tier.VISION
        res.detail = (f"vision '{desc}' @({p.x + geom.x},{p.y + geom.y}) "
                      f"in {out.get('latency_ms', 0):.0f}ms")
        return res


def _mpris(command: str) -> ActionResult:
    """Control the active MPRIS media player (Cine/Plezy/mpv/browser) over DBus."""
    method = {
        "play-pause": "PlayPause", "toggle": "PlayPause", "resume": "Play",
        "play": "Play", "pause": "Pause", "stop": "Stop",
        "next": "Next", "previous": "Previous",
    }.get(command, "PlayPause")
    try:
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        listed = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "ListNames", None, None, Gio.DBusCallFlags.NONE, 3000, None)
        names = [n for n in listed.unpack()[0] if n.startswith("org.mpris.MediaPlayer2.")]
        # prefer a real player over the noctalia stub
        names.sort(key=lambda n: n == "dev.noctalia.Mpris")
        if not names:
            return ActionResult(False, Action.MEDIA, Tier.APP, "no MPRIS player")
        target = names[0]
        bus.call_sync(target, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                      method, None, None, Gio.DBusCallFlags.NONE, 3000, None)
        return ActionResult(True, Action.MEDIA, Tier.APP, f"media {method} -> {target}")
    except Exception as e:  # noqa: BLE001
        return ActionResult(False, Action.MEDIA, Tier.APP, f"mpris error: {e}")


_BROWSERS = {
    "zen", "zen-browser", "zen-browser-bin", "firefox", "google-chrome", "chrome",
    "com.google.Chrome", "chromium", "chromium-browser", "brave", "brave-browser",
    "org.mozilla.firefox", "vivaldi", "opera", "tor browser", "torbrowser", "helium",
}


def _is_browser_app(app_id, prefer=None) -> bool:
    if not app_id:
        return False
    a = str(app_id).lower()
    if prefer and (a == str(prefer).lower() or str(prefer).lower() in a):
        return True
    return a in _BROWSERS or "browser" in a


def _host_keyword(url: str) -> str:
    from urllib.parse import urlparse
    try:
        host = urlparse(url if "://" in url else "https://" + url).netloc.lower().split(":")[0]
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


def _title_has(title, keyword) -> bool:
    if not keyword or not title:
        return False
    return str(keyword).lower() in str(title).lower()


def _list_windows() -> list[dict]:
    import json
    import subprocess
    from . import platform
    if platform.is_macos():
        try:
            from .context import desktop
            return desktop.windows_as_dicts()
        except Exception:
            return []
    try:
        from .context import compositor
        if compositor.active_name() != compositor.NIRI:
            from .context import desktop
            return desktop.windows_as_dicts()
    except Exception:
        return []
    try:
        raw = subprocess.run(["niri", "msg", "--json", "windows"],
                             capture_output=True, text=True, timeout=5).stdout
        return json.loads(raw)
    except Exception:
        return []
