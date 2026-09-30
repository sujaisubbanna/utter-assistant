"""Dependency probing for ``assistant doctor`` (stdlib only)."""
from __future__ import annotations

import ctypes.util
import grp
import os
import subprocess
from typing import Any

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
    except (KeyError, ImportError):
        return False


def _lib_present(pkgconfig_name: str, lib_name: str) -> bool:
    if util.which("pkg-config") and _run_ok(["pkg-config", "--exists", pkgconfig_name]):
        return True
    try:
        return ctypes.util.find_library(lib_name) is not None
    except (OSError, TypeError):
        return False


def probe_deps() -> dict[str, bool]:
    return {
        "wtype": bool(util.which("wtype")),
        "ydotool": bool(util.which("ydotool")),
        "ydotoold": bool(util.which("ydotoold")),
        "grim": bool(util.which("grim")),
        "wl_copy": bool(util.which("wl-copy")),
        "pw_play": bool(util.which("pw-play")),
        "systemd_user": _systemd_user(),
        "input_group": _in_input_group(),
        "uinput": os.path.exists("/dev/uinput"),
        "webkit2gtk": _lib_present("webkit2gtk-4.1", "webkit2gtk-4.1"),
        "gtk3": _lib_present("gtk+-3.0", "gtk-3"),
    }


def missing_deps(deps: dict[str, Any]) -> list[str]:
    return [name for name, present in deps.items() if not present]
