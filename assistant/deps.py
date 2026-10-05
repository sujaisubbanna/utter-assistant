"""Dependency probing for ``assistant doctor`` (stdlib only)."""
from __future__ import annotations

import ctypes.util
import os
import subprocess
from typing import Any

try:  # grp/pwd are Unix-only; importing grp at module scope breaks Windows.
    import grp
except ImportError:  # pragma: no cover - exercised only on Windows
    grp = None  # type: ignore[assignment]

from . import util


def _run_ok(cmd: list[str], timeout: float = 4.0) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _systemd_user() -> bool:
    return _run_ok(["systemctl", "--user", "show-environment"])


def _in_input_group() -> bool:
    if grp is None:
        return False
    try:
        gid = grp.getgrnam("input").gr_gid
    except KeyError:
        return False
    if gid in os.getgroups():
        return True
    try:
        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
        return user in grp.getgrnam("input").gr_mem
    except (KeyError, ImportError, AttributeError):
        return False


def _lib_present(pkgconfig_name: str, lib_name: str) -> bool:
    if util.which("pkg-config") and _run_ok(["pkg-config", "--exists", pkgconfig_name]):
        return True
    try:
        return ctypes.util.find_library(lib_name) is not None
    except (OSError, TypeError):
        return False


def _compositor_name() -> str:
    try:
        from utter.context import compositor

        return compositor.active_name()
    except Exception:  # noqa: BLE001
        return "unknown"


# Windows backends (audio capture, input injection, screen grab) are not
# implemented yet. They are reported as "advisory/not-implemented" rather than
# absent, so ``doctor`` does not tell Windows users to install Linux tooling.
ADVISORY = "advisory/not-implemented"


def probe_deps() -> dict[str, Any]:
    from utter import platform
    if platform.is_macos():
        return {
            "screencapture": bool(util.which("screencapture")),
            "pbpaste": bool(util.which("pbpaste")),
            "pbcopy": bool(util.which("pbcopy")),
            "say": bool(util.which("say")),
            "afplay": bool(util.which("afplay")),
            "osascript": bool(util.which("osascript")),
            "ollama": bool(util.which("ollama")),
            "vocamac": bool(util.which("VocaMac") or os.path.exists(os.path.expanduser("/Applications/VocaMac.app"))),
        }
    if platform.is_windows():
        return {
            # Tools that do exist natively (or as a normal install).
            "powershell": bool(util.which("powershell") or util.which("pwsh")),
            "nvidia-smi": bool(util.which("nvidia-smi")),
            "ollama": bool(util.which("ollama")),
            # Backends with no Windows implementation in this release.
            "wasapi_audio": ADVISORY,
            "win32_input": ADVISORY,
            "win32_screen": ADVISORY,
        }
    comp = _compositor_name()
    deps: dict[str, bool] = {}
    if comp == "kwin":
        # KDE Plasma: D-Bus CLI + spectacle instead of wtype/grim; kdotool is optional
        # but unlocks per-window actions, so it is listed.
        deps["dbus_cli"] = bool(util.which("gdbus") or util.which("qdbus6") or util.which("qdbus")
                                or util.which("dbus-send"))
        deps["spectacle"] = bool(util.which("spectacle"))
        deps["kdotool"] = bool(util.which("kdotool"))
    else:
        deps["wtype"] = bool(util.which("wtype"))
        deps["grim"] = bool(util.which("grim"))
    deps.update({
        "ydotool": bool(util.which("ydotool")),
        "ydotoold": bool(util.which("ydotoold")),
        "wl_copy": bool(util.which("wl-copy")),
        "pw_play": bool(util.which("pw-play")),
        "systemd_user": _systemd_user(),
        "input_group": _in_input_group(),
        "uinput": os.path.exists("/dev/uinput"),
        "webkit2gtk": _lib_present("webkit2gtk-4.1", "webkit2gtk-4.1"),
        "gtk3": _lib_present("gtk+-3.0", "gtk-3"),
    })
    return deps


def missing_deps(deps: dict[str, Any]) -> list[str]:
    return [name for name, present in deps.items() if not present]
