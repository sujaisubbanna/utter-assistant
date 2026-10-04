"""Global push-to-talk hotkey via evdev.

Reads key events from every keyboard that exposes the configured key, without
``grab()``-ing the device (grabbing steals input from the desktop). The user
only needs to be in the ``input`` group, not root.

Public API:
    listen(on_press, on_release, key_name="KEY_RIGHTCTRL")
    process_event(event, key_code=..., on_press=..., on_release=...)
    find_ptt_devices(key_name="KEY_RIGHTCTRL") -> list[InputDevice]
"""
from __future__ import annotations

import logging
import select
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:  # keep the module importable on machines without evdev / non-Linux
    import evdev
    from evdev import ecodes
except Exception:  # pragma: no cover - exercised only without evdev
    evdev = None
    ecodes = None  # type: ignore


DEFAULT_KEY = "KEY_RIGHTCTRL"

EV_KEY = 1
KEY_UP = 0
KEY_DOWN = 1
KEY_REPEAT = 2


def resolve_keycode(key_name: str) -> int:
    """Resolve an evdev key name (``"KEY_RIGHTCTRL"``) to its numeric code."""
    if ecodes is None:
        raise RuntimeError("python-evdev is not installed; cannot resolve key names")
    code = getattr(ecodes, key_name, None)
    if code is None:
        raise ValueError(f"unknown evdev key name: {key_name!r}")
    return int(code)


def _device_keycodes(dev) -> set:
    """Return the set of numeric key codes a device advertises."""
    codes: set = set()
    try:
        caps = dev.capabilities()
    except OSError:
        return codes
    for code in caps.get(EV_KEY, []):
        if isinstance(code, tuple):  # verbose=True shape: ('KEY_A', 30)
            codes.update(c for c in code if isinstance(c, int))
        elif isinstance(code, int):
            codes.add(code)
    return codes


def find_ptt_devices(key_name: str = DEFAULT_KEY, *, open_devices: bool = True):
    """Return input devices that expose ``key_name``.

    Args:
        key_name: evdev key name, e.g. ``"KEY_RIGHTCTRL"``.
        open_devices: When True (default) return open ``InputDevice`` objects
            (caller must close them). When False return ``(path, name)`` tuples
            suitable for logging/reporting.
    """
    if evdev is None:
        raise RuntimeError("python-evdev is not installed")
    return _find_devices_for_codes({resolve_keycode(key_name)}, open_devices=open_devices)


def _find_devices_for_codes(codes, *, open_devices: bool = True):
    """Return input devices that expose any of the numeric ``codes``."""
    if evdev is None:
        raise RuntimeError("python-evdev is not installed")
    wanted = set(codes)

    found = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except (PermissionError, OSError) as exc:
            logger.debug("skipping %s: %s", path, exc)
            continue
        if _device_keycodes(dev) & wanted:
            if open_devices:
                found.append(dev)
            else:
                found.append((path, dev.name))
                dev.close()
        else:
            dev.close()
    return found


def enumerate_devices() -> list:
    """List all readable input devices and whether they expose keys.

    Read-only helper for diagnostics; closes every device it opens.
    """
    if evdev is None:
        raise RuntimeError("python-evdev is not installed")
    out = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except (PermissionError, OSError) as exc:
            out.append({"path": path, "name": None, "error": str(exc)})
            continue
        try:
            codes = _device_keycodes(dev)
            out.append(
                {
                    "path": path,
                    "name": dev.name,
                    "phys": getattr(dev, "phys", ""),
                    "key_count": len(codes),
                    "has_key": bool(codes),
                }
            )
        finally:
            dev.close()
    return out


def process_event(
    event: Any,
    *,
    key_code: int,
    on_press: Callable[[], None],
    on_release: Callable[[], None],
) -> bool:
    """Dispatch a single synthetic or real evdev event.

    Kept as a pure function so the callback logic can be unit-tested with a
    fake event object (any object with ``type``/``code``/``value``).

    Returns True when the event was the configured key and was dispatched.
    Key auto-repeat (value 2) is ignored.
    """
    if getattr(event, "type", None) != EV_KEY:
        return False
    if getattr(event, "code", None) != key_code:
        return False
    value = getattr(event, "value", None)
    if value == KEY_DOWN:
        on_press()
        return True
    if value == KEY_UP:
        on_release()
        return True
    # KEY_REPEAT (2): ignore so a held key does not re-fire on_press.
    return False


def _guarded(on_press: Callable[[], None],
             on_release: Callable[[], None]) -> tuple:
    """Wrap callbacks so auto-repeat / a missing edge cannot re-fire a lane."""
    state = {"pressed": False}

    def press() -> None:
        if not state["pressed"]:
            state["pressed"] = True
            on_press()

    def release() -> None:
        if state["pressed"]:
            state["pressed"] = False
            on_release()

    return press, release


def _listen_loop(
    handlers: dict,
    *,
    label: str,
    find_devices: Callable[[], list],
    stop_event: Optional[threading.Event],
    rescan_interval: float,
    grab: bool,
) -> None:
    """Shared evdev loop for one or more keys.

    ``handlers`` maps a numeric key code to an already edge-guarded
    ``(on_press, on_release)`` pair; ``find_devices`` returns fresh open
    ``InputDevice`` objects exposing any watched code.
    """
    devices: dict = {}

    def add_new_devices() -> None:
        try:
            candidates = find_devices()
        except Exception as exc:  # never let a hotplug error kill the loop
            logger.debug("device rescan failed: %s", exc)
            return
        watched = {getattr(d, "path", None) for d in devices.values()}
        for dev in candidates:
            # A re-opened device always gets a fresh fd, so de-duplicate by path;
            # comparing fds leaked one descriptor per device on every rescan.
            if dev.path in watched:
                dev.close()
                continue
            watched.add(dev.path)
            devices[dev.fd] = dev
            logger.info("watching PTT device %s (%s)", dev.path, dev.name)
            if grab:
                try:
                    dev.grab()
                except OSError as exc:
                    logger.warning("could not grab %s: %s", dev.path, exc)

    def drop_device(fd: int) -> None:
        dev = devices.pop(fd, None)
        if dev is None:
            return
        logger.info("stopped watching %s", dev.path)
        if grab:
            try:
                dev.ungrab()
            except OSError:
                pass
        try:
            dev.close()
        except OSError:
            pass

    def dispatch(event: Any) -> None:
        pair = handlers.get(getattr(event, "code", None))
        if pair is not None:
            process_event(event, key_code=event.code, on_press=pair[0],
                          on_release=pair[1])

    add_new_devices()
    if not devices:
        logger.warning(
            "no keyboard exposes %s now; will keep rescanning every %.1fs",
            label,
            rescan_interval,
        )

    try:
        while not (stop_event is not None and stop_event.is_set()):
            if not devices:
                # Nothing to select on: sleep in short slices so stop_event works.
                if stop_event is not None:
                    stop_event.wait(min(rescan_interval, 0.5))
                else:
                    time.sleep(min(rescan_interval, 0.5))
                add_new_devices()
                continue

            try:
                readable, _, _ = select.select(list(devices.values()), [], [], rescan_interval)
            except (OSError, ValueError):
                # A device vanished underneath select(); prune and continue.
                for fd in list(devices):
                    drop_device(fd)
                add_new_devices()
                continue

            if not readable:
                # Idle timeout: look for newly plugged keyboards.
                add_new_devices()
                continue

            for dev in readable:
                try:
                    for event in dev.read():
                        dispatch(event)
                except OSError:
                    drop_device(dev.fd)
    finally:
        for fd in list(devices):
            drop_device(fd)


def listen(
    on_press: Callable[[], None],
    on_release: Callable[[], None],
    key_name: str = DEFAULT_KEY,
    *,
    stop_event: Optional[threading.Event] = None,
    rescan_interval: float = 3.0,
    grab: bool = False,
) -> None:
    """Run a blocking evdev loop for push-to-talk.

    Args:
        on_press: called on key-down edge (no auto-repeat).
        on_release: called on key-up edge.
        key_name: evdev key name to watch.
        stop_event: when set, the loop returns. If None the loop runs forever
            (until KeyboardInterrupt).
        rescan_interval: seconds between rescans for newly plugged keyboards.
        grab: do NOT enable unless you want to steal the key from the desktop.
            Defaults to False; even when True the device is ungrabbed on exit.
    """
    if evdev is None:
        raise RuntimeError("python-evdev is not installed; cannot listen for hotkeys")
    key_code = resolve_keycode(key_name)
    _listen_loop(
        {key_code: _guarded(on_press, on_release)},
        label=key_name,
        find_devices=lambda: find_ptt_devices(key_name, open_devices=True),
        stop_event=stop_event,
        rescan_interval=rescan_interval,
        grab=grab,
    )


def listen_many(
    keys: dict,
    *,
    stop_event: Optional[threading.Event] = None,
    rescan_interval: float = 3.0,
    grab: bool = False,
) -> None:
    """Run a blocking evdev loop for several push-to-talk keys.

    Args:
        keys: mapping of evdev key name -> ``(on_press, on_release)``. Each key
            keeps its own press/release edge; any key may live on any keyboard.
        stop_event, rescan_interval, grab: as :func:`listen`.

    Raises ``ValueError`` for an empty map, an empty key name or an unknown key
    name, so a bad config fails fast instead of silently watching nothing.
    """
    if evdev is None:
        raise RuntimeError("python-evdev is not installed; cannot listen for hotkeys")
    if not keys:
        raise ValueError("listen_many requires at least one key")
    handlers: dict = {}
    for name, (on_press, on_release) in keys.items():
        if not name:
            raise ValueError("listen_many got an empty key name")
        handlers[resolve_keycode(name)] = _guarded(on_press, on_release)
    codes = set(handlers)
    _listen_loop(
        handlers,
        label=", ".join(keys),
        find_devices=lambda: _find_devices_for_codes(codes),
        stop_event=stop_event,
        rescan_interval=rescan_interval,
        grab=grab,
    )
