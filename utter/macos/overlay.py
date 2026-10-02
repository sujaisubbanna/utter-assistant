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

PANEL_W, PANEL_H = 380.0, 84.0
BOTTOM_MARGIN = 90.0


class Overlay:
    """Thread-safe facade. ``show/listening`` etc. may be called anywhere."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._level = 0.0
        self._text = ""
        self._color = None  # None | "green" | "red"
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
            self._color = None
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

    def final(self, text: str, ok: bool, dismiss_ms: int = 1200) -> None:
        with self._lock:
            self._visible = True
            self._text = text or ""
            self._color = "green" if ok else "red"
            self._hide_at = time.monotonic() + max(200, dismiss_ms) / 1000.0
        self._kick()

    def idle(self) -> None:
        with self._lock:
            self._visible = False
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
            return (self._visible, self._level, self._text, self._color, self._hide_at)


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
                visible, _lvl, _txt, _col, hide_at = owner.snapshot()
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
            _, level, text, color, _ = owner.snapshot()
            NSColor = Cocoa.NSColor
            NSBezierPath = Cocoa.NSBezierPath
            bounds = self.bounds()
            # Rounded dark pill.
            bg = NSColor.colorWithWhite_alpha_(0.12, 0.92)
            pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, 16.0, 16.0)
            bg.set()
            pill.fill()
            # Accent border: neutral while listening, green/red for the verdict.
            if color == "green":
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.30, 0.85, 0.40, 1.0).set()
            elif color == "red":
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.35, 0.35, 1.0).set()
            else:
                NSColor.colorWithWhite_alpha_(1.0, 0.35).set()
            pill.setLineWidth_(2.0)
            pill.stroke()
            # Level bar.
            pad, bar_h = 16.0, 10.0
            bw = bounds.size.width - pad * 2
            bar = ((pad, 18.0), (bw, bar_h))
            NSColor.colorWithWhite_alpha_(1.0, 0.18).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bar, 5.0, 5.0).fill()
            fill_w = bw * max(0.0, min(1.0, level))
            if fill_w > 1.0:
                NSColor.colorWithWhite_alpha_(1.0, 0.85).set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    ((pad, 18.0), (fill_w, bar_h)), 5.0, 5.0).fill()
            # Status text.
            label = text or ("listening…" if color is None else "")
            if label:
                attrs = {
                    Cocoa.NSFontAttributeName: Cocoa.NSFont.systemFontOfSize_(13.0),
                    Cocoa.NSForegroundColorAttributeName: NSColor.whiteColor(),
                }
                ns = Cocoa.NSString.stringWithString_(label)
                size = ns.sizeWithAttributes_(attrs)
                tx = (bounds.size.width - size.width) / 2.0
                ns.drawAtPoint_withAttributes_((tx, 40.0), attrs)
except ImportError:
    pass

__all__ = ["Overlay"]
