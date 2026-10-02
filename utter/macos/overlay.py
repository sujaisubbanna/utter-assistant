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


class Overlay:
    """Thread-safe facade. ``show/listening`` etc. may be called anywhere."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._level = 0.0
        self._history = [0.0] * BARS
        self._text = ""
        self._mode = "idle"  # listening | loading | final
        self._ok = False
        self._visible = False
        self._hide_at = 0.0
        self._panel = None
        self._view = None
        self._ready = False
        try:
            import Cocoa  # type: ignore[import-not-found]
            self._Cocoa = Cocoa
        except ImportError:
            self._Cocoa = None

    # -- public API (any thread) -------------------------------------------
    def listening(self, text: str = "") -> None:
        with self._lock:
            self._visible = True
            self._mode = "listening"
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

    def final(self, text: str, ok: bool, dismiss_ms: int = 1200) -> None:
        with self._lock:
            self._visible = True
            self._mode = "final"
            self._text = text or ""
            self._ok = bool(ok)
            self._hide_at = time.monotonic() + max(200, dismiss_ms) / 1000.0
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
            x = sx + (sw - PANEL_W) / 2.0
            y = sy + BOTTOM_MARGIN
            rect = Cocoa.NSMakeRect(x, y, PANEL_W, PANEL_H)
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
            view = _OverlayView.alloc().initWithFrame_owner_(
                ((0, 0), (PANEL_W, PANEL_H)), self)
            view.setWantsLayer_(True)
            panel.setContentView_(view)
            panel.orderOut_(None)
            self._panel = panel
            self._view = view
            # 30 Hz refresh driven by the main runloop (timers work because the
            # hotkey lane parks the main thread in CFRunLoop, which AppKit shares).
            timer = Cocoa.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / 30.0, view, "utterOverlayTick:", None, True)
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
            return (self._visible, self._mode, self._text, self._ok,
                    list(self._history), self._hide_at)


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
                visible, _mode, _txt, _ok, _hist, hide_at = owner.snapshot()
                panel = self.window()
                if panel is None:
                    return
                if not visible:
                    if panel.isVisible():
                        panel.orderOut_(None)
                    return
                if hide_at and time.monotonic() >= hide_at:
                    owner.idle()
                    return
                if not panel.isVisible():
                    panel.orderFrontRegardless()
                self.setNeedsDisplay_(True)
            except Exception:
                pass

        def drawRect_(self, _dirty):
            owner = getattr(self, "_owner", None)
            if owner is None:
                return
            _, mode, text, ok, history, _ = owner.snapshot()
            NSColor = Cocoa.NSColor
            NSBezierPath = Cocoa.NSBezierPath
            bounds = self.bounds()
            W, H = bounds.size.width, bounds.size.height

            def rgb(c):
                return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    c[0], c[1], c[2], 1.0)

            # Rounded dark pill.
            bg = NSColor.colorWithWhite_alpha_(0.10, 0.94)
            pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, 18.0, 18.0)
            bg.set()
            pill.fill()

            # Copy + status line (Linux panel text contract).
            if mode == "final":
                color = OK if ok else ERROR
                status = "Done" if ok else "Didn't catch that"
                title = text or status
            elif mode == "loading":
                color = LOADING
                status = "Starting up"
                title = text or "Models are coming up…"
            else:
                color = YELLOW
                status = "Assistant · listening"
                title = text or "Listening…"
                if len(title) > TAIL_CHARS:
                    tail = title[-(TAIL_CHARS - 1):]
                    cut = tail.find(" ")
                    if 0 < cut < 8:
                        tail = tail[cut + 1:]
                    title = "…" + tail

            # Text column (left), waveform (right).
            pad = 18.0
            wave_w = BARS * BAR_W + (BARS - 1) * BAR_GAP
            text_w = W - pad * 2 - wave_w - 12.0
            title_attrs = {
                Cocoa.NSFontAttributeName: Cocoa.NSFont.boldSystemFontOfSize_(14.0),
                Cocoa.NSForegroundColorAttributeName: rgb(INK),
            }
            status_attrs = {
                Cocoa.NSFontAttributeName: Cocoa.NSFont.systemFontOfSize_(11.0),
                Cocoa.NSForegroundColorAttributeName: (
                    rgb(color) if mode in ("final", "loading") else rgb(MUTED)),
            }
            t_ns = Cocoa.NSString.stringWithString_(title)
            # Truncate to fit (single line, like maxLines=1).
            while t_ns.sizeWithAttributes_(title_attrs).width > text_w and len(title) > 1:
                title = title[:-2] + "…"
                t_ns = Cocoa.NSString.stringWithString_(title)
            t_ns.drawAtPoint_withAttributes_((pad, H - 44.0), title_attrs)
            s_ns = Cocoa.NSString.stringWithString_(status)
            s_ns.drawAtPoint_withAttributes_((pad, H - 64.0), status_attrs)

            # Waveform: 17 rounded bars, taller in the middle.
            now = time.time()
            base_x = W - pad - wave_w
            mid_y = H / 2.0
            for i, lv in enumerate(history):
                if mode == "loading":
                    s = 0.5 + 0.5 * math.sin(now * 1.5 - i * 0.55)
                    lv = 0.12 + 0.33 * s
                    bar_color = LOADING
                elif mode == "listening":
                    bar_color = YELLOW
                else:
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
except ImportError:
    pass

__all__ = ["Overlay"]
