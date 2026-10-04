"""Step executor with tier escalation.

Executes a Plan. For CLICK_ELEMENT it escalates: accessibility tree (T1) ->
vision grounding (T3). Never acts on a stale target: context is re-read between
steps.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from . import platform
from .types import Action, ActionResult, Context, Plan, Step, Tier

log = logging.getLogger("utter.executor")


def _is_cli_agent_name(app) -> bool:
    """True for a synthesised CLI-agent target (``codex``, ``claude code`` ...).

    These are not catalogue profiles; the per-app opt-in gate must not block
    them (their dangerous part is the runner's terminal/input gate).
    """
    if app is None:
        return False
    try:
        from .router.rules import CLI_AGENTS
        return str(app).strip().lower() in {str(k).strip().lower() for k in CLI_AGENTS}
    except Exception:  # noqa: BLE001 - never let the guard break execution
        return False


class Executor:
    def __init__(self, ctx_builder: Callable[..., Context], cfg,
                 profiles: Optional[dict] = None, confirm: Optional[Callable[[dict], bool]] = None,
                 reload_profiles: bool = False):
        self.ctx_builder = ctx_builder
        self.cfg = cfg
        self._profiles = profiles
        # When True the executor re-reads profiles (mtime-invalidated) on every
        # use, so a live GUI/CLI opt-in toggle applies without a restart. Unit
        # tests pass an explicit ``profiles`` and leave this off.
        self._reload_profiles = reload_profiles
        # ``confirm(request) -> bool`` is the host's confirmation channel
        # (runner ``host.confirm``). ``None`` means no channel: disruptive
        # cross-workspace/fullscreen focus moves are refused, never guessed.
        self.confirm = confirm

    # -- public ------------------------------------------------------------
    def execute_plan(self, plan: Plan) -> list[ActionResult]:
        results: list[ActionResult] = []
        log.info("plan(%s): %s", plan.source,
                 " -> ".join(f"{s.action.value}{s.args}" for s in plan.steps))
        for step in plan.steps:
            res = self.execute_step(step)
            results.append(res)
            if not res.ok:
                # A Linux-only desktop action (niri compositor command, MPRIS
                # media, ``foot`` terminal) cannot run on macOS. Report it, but
                # keep going: later steps may still work, and aborting would
                # turn a useful partial success into a whole-plan failure.
                # Linux is unchanged: any failure still stops the plan.
                if res.unsupported and platform.is_macos():
                    log.info("step unsupported on macOS, continuing: %s (%s)",
                             step.action.value, res.detail)
                    continue
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
        app = step.args.get("app")
        # A *direct* argv launch (CLI agents, ComfyUI: ``app: foot`` + argv) is
        # not an app-profile action; the runner's terminal/input gate covers it.
        # Only a launch that names a known profile may be blocked for opt-out.
        if not step.args.get("argv") and app is not None and self._known_disabled(app):
            return ActionResult(False, step.action, step.tier, f"{app} is disabled")
        return launch.launch_app(step.args.get("argv") or step.args["app"])

    def _do_focus_app(self, step: Step) -> ActionResult:
        from .context import desktop
        app = step.args["app"]
        if self._known_disabled(app):
            return ActionResult(False, step.action, Tier.APP, f"{app} is disabled")
        if platform.is_macos():
            # macOS reports bundle ids (``com.apple.Safari``) while profile ids
            # may differ. Reuse the same tolerant, profile-aware resolution that
            # ``ensure_app`` uses (``_windows_for_app`` -> candidate app_ids +
            # ``desktop.find_windows`` substring match) instead of exact-match.
            windows = self._windows_for_app(app)
            if not windows:
                return ActionResult(False, step.action, Tier.APP, f"{app} not running")
            windows.sort(key=lambda w: (not getattr(w, "is_focused", False),
                                        getattr(w, "workspace_id", 0),
                                        getattr(w, "id", 0)))
            target = windows[0]
            ok = desktop.focus_window(target.id)
            return ActionResult(ok, step.action, Tier.APP, f"focus {app}")
        for win in _list_windows():
            if win.get("app_id") == app:
                ok = desktop.focus_window(win["id"])
                return ActionResult(ok, step.action, Tier.APP, f"focus {app}")
        return ActionResult(False, step.action, Tier.APP, f"{app} not running")

    def _do_key(self, step: Step) -> ActionResult:
        from .actions import keyboard
        blocked = self._blocked_target(step)
        if blocked is not None:
            return blocked
        # macOS first: a targeted window is injected natively to its pid, with
        # no focus change. On Linux this is always None, so the Wayland focus
        # round-trip below is untouched. macOS must outrank `_targeted`, or the
        # pid path is never reached.
        pid = self._macos_target_pid(step)
        if pid is not None:
            return keyboard.send_key(step.args["chord"], pid=pid)
        if step.args.get("app") is not None or step.args.get("window_id") is not None:
            return self._targeted(step, lambda: keyboard.send_key(step.args["chord"]))
        return keyboard.send_key(step.args["chord"])

    def _do_type_text(self, step: Step) -> ActionResult:
        from .actions import keyboard
        blocked = self._blocked_target(step)
        if blocked is not None:
            return blocked
        pid = self._macos_target_pid(step)
        if pid is not None:
            return keyboard.type_text(step.args["text"], pid=pid)
        if step.args.get("app") is not None or step.args.get("window_id") is not None:
            return self._targeted(step, lambda: keyboard.type_text(step.args["text"]))
        return keyboard.type_text(step.args["text"])

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

    # -- app-targeted input (focus round-trip) -----------------------------
    def _get_profiles(self) -> dict:
        if self._reload_profiles:
            try:
                from .router import profiles as profiles_mod
                self._profiles = profiles_mod.load_cached()
                return self._profiles
            except Exception:  # noqa: BLE001 - fall through to the cached dict
                pass
        if self._profiles is None:
            try:
                from .router import profiles as profiles_mod
                self._profiles = profiles_mod.load()
            except Exception:  # noqa: BLE001 - resolution degrades to raw ids
                self._profiles = {}
        return self._profiles

    def _app_profile(self, app):
        """Resolve a spoken name / id to an ``AppProfile`` (or None)."""
        if app is None:
            return None
        profiles = self._get_profiles()
        prof = profiles.get(str(app)) if profiles else None
        if prof is None and profiles:
            from .router import profiles as profiles_mod
            prof = profiles_mod.resolve(str(app), profiles)
        return prof

    def _app_enabled(self, app) -> bool:
        """Whether a *known, opted-out* app must be refused.

        A known profile that is disabled returns False. An unknown name (a CLI
        agent, a macOS app with no profile, or any raw name) returns True: it is
        not a catalogue app the user could have opted out of. Window targeting
        still refuses an unresolved name: :meth:`_candidate_ids` has no
        raw-name fallback, so an unknown target only ever works with an
        explicit ``window_id`` (or a synthesised CLI-agent name).
        """
        prof = self._app_profile(app)
        if prof is None:
            return True
        return bool(getattr(prof, "enabled", False))

    def _known_disabled(self, app) -> bool:
        """True only when ``app`` resolves to a profile that is opted out."""
        prof = self._app_profile(app)
        return prof is not None and not bool(getattr(prof, "enabled", False))

    def _browser_allowed(self, app_id) -> bool:
        """A window whose app profile is disabled must never be focused.

        Sites/URLs stay openable (``open youtube``); this only stops Utter from
        driving a browser it was told to ignore.
        """
        if not app_id:
            return False
        prof = self._app_profile(app_id)
        if prof is None:
            return True  # not a catalogue profile (e.g. zen): not gated here
        return bool(getattr(prof, "enabled", False))

    def _blocked_target(self, step: Step):
        """Refusal result when a step names a *disabled* app, else ``None``.

        An explicit ``window_id`` is a capability and may target without a
        profile; an unknown spoken ``app`` is not blocked here but will refuse
        later for lack of a window candidate.
        """
        app = step.args.get("app")
        if app is None or step.args.get("window_id") is not None:
            return None
        if self._app_enabled(app):
            return None
        return ActionResult(False, step.action, step.tier, f"{app} is disabled")

    def _candidate_ids(self, app) -> list:
        """Window ``app_id`` candidates for a profile: ``[id, *app_ids]``, deduped.

        ``app_ids`` are precomputed (curated profile data); the compositor list
        only ever *selects* one of these — it never authors a target. An
        unresolved spoken name has no fallback (only an explicit ``window_id``
        may target without a profile); a synthesised CLI-agent name is allowed
        because it is ungated.
        """
        if app is None:
            return []
        prof = self._app_profile(app)
        if prof is None:
            return [str(app)] if _is_cli_agent_name(app) else []
        ids = [getattr(prof, "id", str(app)),
               *(getattr(prof, "app_ids", []) or [])]
        out: list = []
        seen: set = set()
        for cid in ids:
            if cid and cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out

    def _app_display(self, app, target=None) -> str:
        """A trusted display name for confirmations: curated name, else id.

        Never a window title (titles are untrusted).
        """
        prof = self._app_profile(app)
        if prof is not None:
            return getattr(prof, "name", "") or getattr(prof, "id", str(app))
        if app is not None:
            return str(app)
        return getattr(target, "app_id", "") if target is not None else ""

    def _windows_for_app(self, app) -> list:
        from .context import desktop
        seen: dict = {}
        for cid in self._candidate_ids(app):
            try:
                found = desktop.find_windows(app_id=cid)
            except Exception:  # noqa: BLE001
                found = []
            for w in found or []:
                seen.setdefault(w.id, w)
        return list(seen.values())

    def _window_by_id(self, window_id: int):
        from .context import desktop
        try:
            windows = desktop.list_windows() or []
        except Exception:  # noqa: BLE001
            windows = []
        for w in windows:
            if getattr(w, "id", None) == window_id:
                return w
        return None

    def _resolve_target(self, step: Step, *, destructive: bool):
        """Resolve ``args.app`` / ``args.window_id`` to exactly one window.

        Returns ``(WindowInfo | None, error)``. 0 windows and multi-window
        destructive targets refuse rather than guess.
        """
        window_id = step.args.get("window_id")
        if window_id is not None:
            try:
                wid = int(window_id)
            except (TypeError, ValueError):
                return None, f"bad window_id {window_id!r}"
            target = self._window_by_id(wid)
            if target is None:
                return None, f"window {wid} not found"
            return target, ""
        app = step.args.get("app")
        if app is None:
            return None, "no app target"
        windows = self._windows_for_app(app)
        if not windows:
            return None, f"{app} not running"
        if destructive:
            if len(windows) > 1:
                return None, f"{app} has {len(windows)} windows; refusing to guess which to close"
            return windows[0], ""
        # Deterministic preference: focused, then lowest workspace, then lowest id.
        windows.sort(key=lambda w: (not getattr(w, "is_focused", False),
                                    getattr(w, "workspace_id", 0),
                                    getattr(w, "id", 0)))
        return windows[0], ""

    def _target_cfg(self):
        cfg = getattr(self.cfg, "target", None)
        if cfg is None:
            from .config import TargetConfig
            return TargetConfig()
        mode = getattr(cfg, "mode", "round_trip")
        cross = getattr(cfg, "cross_workspace", "ask")
        restore = getattr(cfg, "restore", "if_unchanged")
        timeout = getattr(cfg, "focus_timeout_ms", 500)
        if mode not in ("round_trip", "leave", "off"):
            mode = "round_trip"
        if cross not in ("ask", "allow", "refuse"):
            cross = "ask"
        if restore not in ("if_unchanged", "always", "never"):
            restore = "if_unchanged"
        try:
            timeout = max(0, int(timeout))
        except (TypeError, ValueError):
            timeout = 500
        from .config import TargetConfig
        return TargetConfig(mode, cross, restore, timeout)

    def _wayland_cfg(self):
        cfg = getattr(self.cfg, "wayland", None)
        from .config import WaylandConfig
        if cfg is None:
            return WaylandConfig()
        cross = getattr(cfg, "cross_workspace", "auto")
        if cross not in ("auto", "ask", "allow", "refuse"):
            cross = "auto"
        assume = bool(getattr(cfg, "assume_animations_off", False))
        return WaylandConfig(cross, assume)

    def _cross_workspace_decision(self) -> str:
        """Resolve the cross-workspace policy to ``ask`` / ``allow`` / ``refuse``.

        ``[wayland].cross_workspace`` supersedes ``[target].cross_workspace``:
        an explicit ``ask``/``allow``/``refuse`` wins; ``auto`` allows only when
        ``[wayland].assume_animations_off`` is set, else it falls back to
        ``[target].cross_workspace``.
        """
        wl = self._wayland_cfg()
        if wl.cross_workspace in ("ask", "allow", "refuse"):
            return wl.cross_workspace
        if wl.assume_animations_off:
            return "allow"
        return self._target_cfg().cross_workspace

    def _ask_target(self, app_name: str, target, reasons: list) -> bool:
        if self.confirm is None:
            return False
        request = {
            "kind": "app_target_focus",
            "app": app_name,
            "window_id": getattr(target, "id", 0),
            "workspace_id": getattr(target, "workspace_id", 0),
            "reasons": list(reasons),
        }
        try:
            return bool(self.confirm(request))
        except Exception as e:  # noqa: BLE001
            log.debug("target confirmation failed: %s", e)
            return False

    def _focus_and_wait(self, window_id: int, timeout_ms: int) -> bool:
        from .context import desktop
        fn = getattr(desktop, "focus_window_on_workspace", None) or getattr(desktop, "focus_window", None)
        if fn is None:
            return False
        try:
            fn(window_id)
        except Exception as e:  # noqa: BLE001
            log.debug("focus_window_on_workspace(%s) failed: %s", window_id, e)
            fallback = getattr(desktop, "focus_window", None)
            if fallback is None:
                return False
            try:
                fallback(window_id)
            except Exception:  # noqa: BLE001
                return False
        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
        while True:
            try:
                cur = desktop.focused_window()
            except Exception:  # noqa: BLE001
                cur = None
            if cur is not None and getattr(cur, "window_id", None) == window_id:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def _restore_focus(self, prev, target_id: int, policy: str) -> None:
        if prev is None or policy == "never":
            return
        if policy == "if_unchanged":
            from .context import desktop
            try:
                cur = desktop.focused_window()
            except Exception:  # noqa: BLE001
                return
            if cur is None or getattr(cur, "window_id", None) != target_id:
                return  # the user moved away: never yank focus back
        self._focus_window(prev.window_id)

    def _with_focus(self, target, app_name: str, payload: Callable[[], ActionResult],
                    step: Step) -> ActionResult:
        """Run ``payload`` with ``target`` focused, then restore per policy.

        Refuses when focus cannot be achieved (never injects into the wrong
        window) and asks on disruptive moves (cross-workspace / prior
        fullscreen) through the confirmation channel.
        """
        tcfg = self._target_cfg()
        if tcfg.mode == "off":
            return ActionResult(False, step.action, step.tier,
                                f"target mode off: refusing to focus {app_name}")
        from .context import desktop
        try:
            prev = desktop.focused_window()
        except Exception as e:  # noqa: BLE001
            return ActionResult(False, step.action, step.tier, f"focus read failed: {e}")
        if prev is not None and getattr(prev, "window_id", None) == getattr(target, "id", None):
            return payload()  # already focused: no focus call, no confirmation
        cross = (prev is not None
                 and getattr(target, "workspace_id", 0) != getattr(prev, "workspace_id", 0))
        fullscreen = bool(prev is not None and getattr(prev, "is_fullscreen", False))
        reasons = []
        if cross:
            decision = self._cross_workspace_decision()
            if decision == "refuse":
                return ActionResult(False, step.action, step.tier,
                                    f"refusing cross-workspace target {app_name}")
            if decision == "ask":
                reasons.append("cross_workspace")
            # allow -> same-workspace-level, no confirmation
        if fullscreen:
            reasons.append("fullscreen")
        if reasons and not self._ask_target(app_name, target, reasons):
            return ActionResult(False, step.action, step.tier,
                                f"target confirmation refused for {app_name}")
        if not self._focus_and_wait(getattr(target, "id", 0), tcfg.focus_timeout_ms):
            return ActionResult(False, step.action, step.tier,
                                f"could not focus {app_name} (win {getattr(target, 'id', 0)}); not injecting")
        try:
            return payload()
        finally:
            if tcfg.mode == "round_trip":
                self._restore_focus(prev, getattr(target, "id", 0), tcfg.restore)

    def _targeted(self, step: Step, payload: Callable[[], ActionResult]) -> ActionResult:
        target, err = self._resolve_target(step, destructive=False)
        if target is None:
            return ActionResult(False, step.action, step.tier, err)
        app_name = self._app_display(step.args.get("app"), target)
        return self._with_focus(target, app_name, payload, step)

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
        browsers = [w for w in windows
                    if _is_browser_app(w.app_id, prefer) and self._browser_allowed(w.app_id)]
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
            if self._browser_allowed("zen") and zen.is_up():
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

        if (ctx.focused and self._browser_allowed(ctx.focused.app_id)
                and _is_browser_app(ctx.focused.app_id, prefer) and _title_has(ctx.focused.title, kw)):
            return ActionResult(True, Action.ENSURE_URL, Tier.APP,
                                f"already on {kw} (focused window)")

        for w in browsers:
            if _title_has(w.title, kw):
                self._focus_window(w.id)
                return ActionResult(True, Action.ENSURE_URL, Tier.APP,
                                    f"focused existing '{kw}' window {w.id}")

        from .actions import launch
        fallback_browser = preferred if (preferred and self._browser_allowed(preferred)) else None
        opened = launch.open_url(url, browser_app_id=browsers[0].app_id if browsers else fallback_browser)
        detail = f"opened {url}"
        if browsers:
            self._focus_window(browsers[0].id)
            detail += f" in existing browser (win {browsers[0].id})"
        return ActionResult(opened.ok, Action.ENSURE_URL, Tier.APP, detail)

    def _do_ensure_app(self, step: Step) -> ActionResult:
        """Context-aware 'open <app>': focus an existing window, else launch."""
        app = step.args["app"]
        argv = step.args.get("argv")
        if self._known_disabled(app):
            return ActionResult(False, Action.ENSURE_APP, Tier.APP, f"{app} is disabled")
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
        if platform.is_macos():
            # ``foot`` is Linux-only. Rather than spawn a missing binary, report
            # a clear unsupported result (the plan keeps going). A focused
            # terminal still takes the typing path above.
            return ActionResult(False, Action.TERMINAL, Tier.APP,
                                "terminal is not supported on macOS (no terminal focused)",
                                unsupported=True)
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
        if res.unsupported and platform.is_macos():
            # The macOS fallback backend reports the same structured outcome;
            # replace its internal wording with something user-clear. It stays
            # ``unsupported`` so ``execute_plan`` reports it without aborting.
            res.detail = (f"'{step.args['command']}' is a niri/Linux compositor action, "
                          "not available on macOS")
        return res

    def _do_media(self, step: Step) -> ActionResult:
        app = step.args.get("app")
        # Generic media transport keys (no app) are always allowed; a named app
        # target must be enabled and resolve to at least one MPRIS candidate id
        # (never silently drive a different player).
        if app is not None:
            if not self._app_enabled(app):
                return ActionResult(False, Action.MEDIA, step.tier, f"{app} is disabled")
            candidate_ids = self._candidate_ids(app)
            if not candidate_ids:
                return ActionResult(False, Action.MEDIA, step.tier,
                                    f"no media player for {app}")
        else:
            candidate_ids = None
        return _mpris(step.args.get("command", "play-pause"), candidate_ids=candidate_ids)

    def _do_close_app(self, step: Step) -> ActionResult:
        """Close a window belonging to ``step.args['app']`` (or ``window_id``).

        Never focuses: a close is issued straight at the target window id. A
        multi-window app is never guessed at — the caller must be specific.
        """
        app = step.args.get("app")
        if app is not None and step.args.get("window_id") is None and not self._app_enabled(app):
            return ActionResult(False, Action.CLOSE_APP, step.tier, f"{app} is disabled")
        target, err = self._resolve_target(step, destructive=True)
        if target is None:
            return ActionResult(False, Action.CLOSE_APP, step.tier, err)
        try:
            from .context import desktop
            backend = desktop.backend()
            fn = getattr(backend, "close_window", None)
            if fn is None:
                return ActionResult(False, Action.CLOSE_APP, step.tier,
                                    "close not supported on this platform")
            out = fn(target.id)
        except Exception as e:  # noqa: BLE001
            return ActionResult(False, Action.CLOSE_APP, step.tier, f"close error: {e}")
        ok = bool(getattr(out, "ok", out))
        detail = getattr(out, "detail", "") or f"closed window {target.id}"
        res = ActionResult(ok, Action.CLOSE_APP, step.tier, detail)
        res.unsupported = bool(getattr(out, "unsupported", False))
        return res

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
        # `tts.speak` picks the platform backend itself (macOS `say`/AVSpeech,
        # Linux espeak-ng/espeak/spd-say/piper) and never raises.
        try:
            from .voice import tts

            tts.speak(text, self.cfg)
        except Exception:  # noqa: BLE001 - spoken replies must not break actions
            pass
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
        # `[perception] accessibility_enabled = false` skips the a11y tier and
        # lets the caller fall through to vision.
        if not getattr(getattr(self.cfg, "perception", None), "accessibility_enabled", True):
            return None
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


def _select_mpris(names: list, candidate_ids=None):
    """Pick the MPRIS bus name to drive.

    ``candidate_ids`` (profile id + curated ``app_ids``) filter the bus names so
    ``spotify pause`` controls Spotify even when another player is also
    registered. Returns None when the named app has no MPRIS player (never
    silently drives a different one).
    """
    if candidate_ids:
        wanted = [str(c).lower() for c in candidate_ids if c]
        matched = [n for n in names if any(w in str(n).lower() for w in wanted)]
        if not matched:
            return None
        names = matched
    if not names:
        return None
    # prefer a real player over the noctalia stub
    names = sorted(names, key=lambda n: n == "dev.noctalia.Mpris")
    return names[0]


def _mpris(command: str, candidate_ids=None) -> ActionResult:
    """Control the active MPRIS media player (Cine/Plezy/mpv/browser) over DBus."""
    if platform.is_macos():
        # MPRIS is a Linux/freedesktop D-Bus interface; PyGObject (``gi``) is
        # absent on macOS, so return a clear unsupported result instead of an
        # import error. ``unsupported`` lets a plan continue past it.
        return ActionResult(False, Action.MEDIA, Tier.APP,
                            "media control is not supported on macOS",
                            unsupported=True)
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
        target = _select_mpris(names, candidate_ids)
        if target is None:
            detail = "no MPRIS player" + (
                f" for {candidate_ids[0]}" if candidate_ids else "")
            return ActionResult(False, Action.MEDIA, Tier.APP, detail)
        bus.call_sync(target, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                      method, None, None, Gio.DBusCallFlags.NONE, 3000, None)
        return ActionResult(True, Action.MEDIA, Tier.APP, f"media {method} -> {target}")
    except Exception as e:  # noqa: BLE001
        return ActionResult(False, Action.MEDIA, Tier.APP, f"mpris error: {e}")


_BROWSERS = {
    "zen", "zen-browser", "zen-browser-bin", "firefox", "google-chrome", "chrome",
    "com.google.Chrome", "chromium", "chromium-browser", "brave", "brave-browser",
    "org.mozilla.firefox", "vivaldi", "opera", "tor browser", "torbrowser", "helium",
    # macOS browsers. ``_is_browser_app`` lowercases the window's app_id before
    # the membership test, so these are stored lowercased.
    "com.apple.safari", "com.apple.safaritechnologypreview",
    "company.thebrowser.browser", "com.google.chrome.canary",
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
