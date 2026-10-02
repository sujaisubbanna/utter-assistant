"""Native macOS OSD overlay: the Linux Noctalia panel's twin.

Bottom-centre floating panel, visible on all spaces and above all windows:

* assistant key down  -> panel appears, level bar pulses with the mic
* release             -> final text shown, border flashes green (command ran)
                       or red (nothing matched), then fades out
* dictation key       -> no panel (same rule as Linux: assistant lane only)

Runs in the daemon process (which owns mic level + router outcome directly, so
no IPC). All AppKit calls happen on the main thread; the audio callback only
writes plain floats. Never raises into the voice path.
"""
from __future__ import annotations

import logging
import math
import threading
import time

logger = logging.getLogger(__name__)

# Linux Noctalia twin: brand yellow bars, teal loading, green/red verdicts.
YELLOW = (0.969, 0.788, 0.282)
BLUE = (0.549, 0.784, 1.0)
OK = (0.298, 0.765, 0.541)
ERROR = (0.949, 0.467, 0.478)
LOADING = (0.482, 0.831, 0.769)
INK = (0.925, 0.925, 0.925)
MUTED = (0.612, 0.612, 0.612)

BARS = 17
BAR_W = 3.0
BAR_GAP = 3.0
WAVE_H = 30.0
MIN_H = 3.0
TAIL_CHARS = 22

PANEL_W, PANEL_H = 430.0, 96.0
BOTTOM_MARGIN = 90.0
BANNER_W, BANNER_H = 560.0, 110.0
BANNER_TOP_MARGIN = 150.0


class Overlay:
    """Thread-safe facade. All methods may be called from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._level = 0.0
        self._history = [0.0] * BARS
        self._text = ""
        self._lane = "assistant"  # assistant | dictation
        self._mode = "idle"  # listening | loading | final
        self._ok = False
        self._visible = False
        self._hide_at = 0.0
        # Top-center transcript banner (last verdict; persists across listens).
        self._banner_text = ""
        self._banner_lane = "assistant"
        self._banner_at = 0.0
        self._panel = None
        self._view = None
        self._banner_panel = None
        self._banner_view = None
        self._ready = False
        try:
            import Cocoa  # type: ignore[import-not-found]
            self._Cocoa = Cocoa
        except ImportError:
            self._Cocoa = None

    # -- public API (any thread) -------------------------------------------
    def listening(self, text: str = "", lane: str = "assistant") -> None:
        with self._lock:
            self._visible = True
            self._mode = "listening"
            self._lane = lane if lane == "dictation" else "assistant"
            self._text = text
            self._hide_at = 0.0
            self._history = [0.0] * BARS
        self._kick()

    def loading(self, text: str = "") -> None:
        with self._lock:
            self._visible = True
            self._mode = "loading"
            self._text = text
            self._hide_at = 0.0
        self._kick()

    def level(self, value: float) -> None:
        try:
            v = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        with self._lock:
            self._level = v
            # Center-out ripple, like the Noctalia wave: new samples enter at
            # the middle so the voice reads as coming out of the panel.
            mid = BARS // 2
            for i in range(mid):
                self._history[i] = self._history[i + 1]
            for i in range(BARS - 1, mid, -1):
                self._history[i] = self._history[i - 1]
            self._history[mid] = v

    def final(self, text: str, ok: bool, dismiss_ms: int = 1200,
              lane: str = "assistant") -> None:
        with self._lock:
            self._visible = True
            self._mode = "final"
            self._lane = lane if lane == "dictation" else "assistant"
            self._text = text or ""
            self._ok = bool(ok)
            self._hide_at = time.monotonic() + max(200, dismiss_ms) / 1000.0
            self._banner_text = text or ""
            self._banner_lane = self._lane
            self._banner_at = self._hide_at
        self._kick()

    def idle(self) -> None:
        with self._lock:
            self._visible = False
            self._mode = "idle"
            self._hide_at = 0.0
        self._kick()

    def clear_loading(self) -> None:
        """Hide the startup pulse once models answer; no-op otherwise."""
        with self._lock:
            if self._mode != "loading":
                return
            self._visible = False
            self._mode = "idle"
            self._hide_at = 0.0
        self._kick()

    # -- internals -----------------------------------------------------------
    def _kick(self) -> None:
        if self._Cocoa is None:
            return
        try:
            self._ensure()
            target = self._view
            if target is not None:
                target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "utterOverlayTick:", None, False)
        except Exception:
            logger.debug("overlay kick failed", exc_info=True)

    def _panel_with_view(self, Cocoa, screen_rect, w, h, y, view_cls):
        ((sx, sy), (sw, sh)) = screen_rect
        rect = Cocoa.NSMakeRect(sx + (sw - w) / 2.0, y, w, h)
        panel = Cocoa.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            Cocoa.NSWindowStyleMaskBorderless,
            Cocoa.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(Cocoa.NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(Cocoa.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        try:
            panel.setCollectionBehavior_(
                Cocoa.NSWindowCollectionBehaviorCanJoinAllSpaces
                | Cocoa.NSWindowCollectionBehaviorStationary
                | Cocoa.NSWindowCollectionBehaviorIgnoresCycle)
        except Exception:
            pass
        view = view_cls.alloc().initWithFrame_owner_(((0, 0), (w, h)), self)
        view.setWantsLayer_(True)
        panel.setContentView_(view)
        panel.orderOut_(None)
        return panel, view

    def _ensure(self) -> None:
        if self._ready or self._Cocoa is None:
            return
        try:
            Cocoa = self._Cocoa
            app = Cocoa.NSApplication.sharedApplication()
            try:
                app.setActivationPolicy_(Cocoa.NSApplicationActivationPolicyAccessory)
            except Exception:
                pass
            screen = Cocoa.NSScreen.mainScreen()
            frame = screen.frame() if screen is not None else ((0, 0), (1440, 900))
            ((sx, sy), (sw, sh)) = frame
            self._panel, self._view = self._panel_with_view(
                Cocoa, frame, PANEL_W, PANEL_H, sy + BOTTOM_MARGIN, _OverlayView)
            banner_y = sy + sh - BANNER_TOP_MARGIN - BANNER_H
            self._banner_panel, self._banner_view = self._panel_with_view(
                Cocoa, frame, BANNER_W, BANNER_H, banner_y, _BannerView)
            # 30 Hz refresh driven by the main runloop (timers work because the
            # hotkey lane parks the main thread in CFRunLoop, which AppKit shares).
            timer = Cocoa.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / 30.0, self._view, "utterOverlayTick:", None, True)
            try:
                Cocoa.NSRunLoop.mainRunLoop().addTimer_forMode_(timer, Cocoa.NSRunLoopCommonModes)
            except Exception:
                pass
            self._ready = True
        except Exception:
            logger.debug("overlay init failed", exc_info=True)

    # -- read by the view (main thread) --------------------------------------
    def snapshot(self):
        with self._lock:
            return {
                "visible": self._visible,
                "mode": self._mode,
                "lane": self._lane,
                "text": self._text,
                "ok": self._ok,
                "history": list(self._history),
                "hide_at": self._hide_at,
                "banner_text": self._banner_text,
                "banner_lane": self._banner_lane,
                "banner_at": self._banner_at,
            }

    def tick_banner(self) -> None:
        """Show/hide the top transcript banner. Main thread only."""
        try:
            with self._lock:
                text, lane = self._banner_text, self._banner_lane
                show = bool(text) and time.monotonic() < self._banner_at
            panel = self._banner_panel
            if panel is None:
                return
            if not show:
                if panel.isVisible():
                    panel.orderOut_(None)
                return
            if not panel.isVisible():
                panel.orderFrontRegardless()
            view = self._banner_view
            if view is not None:
                view.setNeedsDisplay_(True)
        except Exception:
            pass


try:
    import Cocoa  # type: ignore[import-not-found]
    from Cocoa import NSView

    class _OverlayView(NSView):
        def initWithFrame_owner_(self, frame, owner):
            self = self.initWithFrame_(frame)
            self._owner = owner
            return self

        def isOpaque(self):
            return False

        def utterOverlayTick_(self, _timer):
            owner = getattr(self, "_owner", None)
            if owner is None:
                return
            try:
                snap = owner.snapshot()
                panel = self.window()
                if panel is None:
                    return
                if not snap["visible"]:
                    if panel.isVisible():
                        panel.orderOut_(None)
                elif snap["hide_at"] and time.monotonic() >= snap["hide_at"]:
                    owner.idle()
                else:
                    if not panel.isVisible():
                        panel.orderFrontRegardless()
                    self.setNeedsDisplay_(True)
                # Top banner lives on its own timer but shares the snapshot.
                owner.tick_banner()
            except Exception:
                pass

        def drawRect_(self, _dirty):
            owner = getattr(self, "_owner", None)
            if owner is None:
                return
            snap = owner.snapshot()
            mode, lane = snap["mode"], snap["lane"]
            text, ok, history = snap["text"], snap["ok"], snap["history"]
            NSColor = Cocoa.NSColor
            NSBezierPath = Cocoa.NSBezierPath
            bounds = self.bounds()
            W, H = bounds.size.width, bounds.size.height

            def rgb(c):
                return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    c[0], c[1], c[2], 1.0)

            def draw_text(s, font, color, x, y, max_w=0):
                if not s:
                    return 0.0
                attrs = {
                    Cocoa.NSFontAttributeName: font,
                    Cocoa.NSForegroundColorAttributeName: color,
                }
                ns = Cocoa.NSString.stringWithString_(s)
                if max_w > 0:
                    while ns.sizeWithAttributes_(attrs).width > max_w and len(s) > 1:
                        s = s[:-2] + "…"
                        ns = Cocoa.NSString.stringWithString_(s)
                ns.drawAtPoint_withAttributes_((x, y), attrs)
                return ns.sizeWithAttributes_(attrs).width

            accent = BLUE if lane == "dictation" else YELLOW
            # Rounded dark pill.
            bg = NSColor.colorWithWhite_alpha_(0.10, 0.94)
            pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, 18.0, 18.0)
            bg.set()
            pill.fill()

            # Copy (Linux panel text contract, both lanes).
            glyph = ""
            if mode == "final":
                if lane == "dictation":
                    status = "Typed" if ok else "Couldn't type that"
                else:
                    status = "Done" if ok else "Didn't catch that"
                title = text or status
                color = OK if ok else ERROR
                glyph = "✓" if ok else "✕"
            elif mode == "loading":
                color = LOADING
                status = "Starting up"
                title = text or "Models are coming up…"
            elif lane == "dictation":
                color = accent
                status = "Dictation · typing"
                title = text or "Dictating…"
            else:
                color = accent
                status = "Assistant · listening"
                title = text or "Listening…"
            if len(title) > TAIL_CHARS and mode == "listening":
                tail = title[-(TAIL_CHARS - 1):]
                cut = tail.find(" ")
                if 0 < cut < 8:
                    tail = tail[cut + 1:]
                title = "…" + tail

            # Utter mark (yellow U) + text column (left), waveform (right).
            pad = 18.0
            wave_w = BARS * BAR_W + (BARS - 1) * BAR_GAP
            mark_font = Cocoa.NSFont.boldSystemFontOfSize_(26.0)
            draw_text("U", mark_font, rgb(YELLOW), pad, H - 62.0)
            tx = pad + 34.0
            text_w = W - tx - wave_w - 12.0 - pad
            title_font = Cocoa.NSFont.boldSystemFontOfSize_(14.0)
            status_font = Cocoa.NSFont.systemFontOfSize_(11.0)
            status_color = (rgb(color) if mode in ("final", "loading")
                            else rgb(MUTED))
            draw_text(title, title_font, rgb(INK), tx, H - 44.0, text_w)
            sx = tx
            if glyph:
                sx += draw_text(glyph, status_font, rgb(color), sx, H - 64.0) + 5.0
            draw_text(status, status_font, status_color, sx, H - 64.0, text_w)

            # Waveform: 17 rounded bars, taller in the middle.
            now = time.time()
            base_x = W - pad - wave_w
            mid_y = H / 2.0
            for i in range(BARS):
                if mode == "loading":
                    s = 0.5 + 0.5 * math.sin(now * 1.5 - i * 0.55)
                    lv = 0.12 + 0.33 * s
                    bar_color = LOADING
                elif mode == "listening":
                    lv = history[i] if i < len(history) else 0.0
                    bar_color = accent
                else:
                    # Verdict: flat calm bars in the verdict color.
                    lv = 0.18
                    bar_color = OK if ok else ERROR
                centre = 1.0 - abs((i - BARS / 2.0) / (BARS / 2.0)) * 0.45
                h = max(MIN_H, MIN_H + (WAVE_H - MIN_H) * min(1.0, lv * 1.35) * centre)
                x = base_x + i * (BAR_W + BAR_GAP)
                rect = ((x, mid_y - h / 2.0), (BAR_W, h))
                r, g, b = bar_color
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0).set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    rect, 2.0, 2.0).fill()

    class _BannerView(NSView):
        """Top-center transcript banner: mode label + big quoted text."""

        def initWithFrame_owner_(self, frame, owner):
            self = self.initWithFrame_(frame)
            self._owner = owner
            return self

        def isOpaque(self):
            return False

        def utterOverlayTick_(self, _timer):
            self.setNeedsDisplay_(True)

        def drawRect_(self, _dirty):
            owner = getattr(self, "_owner", None)
            if owner is None:
                return
            snap = owner.snapshot()
            text, lane = snap["banner_text"], snap["banner_lane"]
            if not text:
                return
            NSColor = Cocoa.NSColor
            NSBezierPath = Cocoa.NSBezierPath
            bounds = self.bounds()
            W, H = bounds.size.width, bounds.size.height

            def rgb(c):
                return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    c[0], c[1], c[2], 1.0)

            accent = BLUE if lane == "dictation" else YELLOW
            bg = NSColor.colorWithWhite_alpha_(0.08, 0.95)
            pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, 20.0, 20.0)
            bg.set()
            pill.fill()
            label = "DICTATION" if lane == "dictation" else "ASSISTANT"
            label_attrs = {
                Cocoa.NSFontAttributeName: Cocoa.NSFont.boldSystemFontOfSize_(11.0),
                Cocoa.NSForegroundColorAttributeName: rgb(accent),
            }
            quote = "\u201c%s\u201d" % text
            quote_attrs = {
                Cocoa.NSFontAttributeName: Cocoa.NSFont.boldSystemFontOfSize_(22.0),
                Cocoa.NSForegroundColorAttributeName: rgb(INK),
            }
            lab = Cocoa.NSString.stringWithString_(label)
            lw = lab.sizeWithAttributes_(label_attrs).width
            lab.drawAtPoint_withAttributes_(((W - lw) / 2.0, H - 34.0), label_attrs)
            q = Cocoa.NSString.stringWithString_(quote)
            qw = q.sizeWithAttributes_(quote_attrs).width
            if qw > W - 60.0:
                s = quote
                while q.sizeWithAttributes_(quote_attrs).width > W - 60.0 and len(s) > 1:
                    s = s[:-2] + "…"
                    q = Cocoa.NSString.stringWithString_(s)
                qw = q.sizeWithAttributes_(quote_attrs).width
            q.drawAtPoint_withAttributes_(((W - qw) / 2.0, H - 72.0), quote_attrs)
except ImportError:
    pass

__all__ = ["Overlay"]
