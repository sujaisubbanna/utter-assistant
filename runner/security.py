"""Plugin hardening wrapper selection and per-permission enforceability.

When ``[security] enforce = true`` the runner prefers ``systemd-run --user
--scope`` (NoNewPrivileges, RestrictAddressFamilies, private tmp, device cgroup,
ReadOnlyPaths, ...), falls back to ``bwrap``, and otherwise runs unhardened while
marking every permission **advisory** (TRUST.md §6: never imply safety that
isn't enforced).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import platform as _platform

# Permissions a supported wrapper can actually constrain.
ENFORCEABLE = {
    "microphone": "DeviceAllow",
    "filesystem.read": "ReadOnlyPaths",
    "filesystem.write": "ReadWritePaths",
    "network": "RestrictAddressFamilies",
    "device": "DeviceAllow",
}

# Device nodes an ordinary subprocess needs to start. Everything else is denied
# by DevicePolicy=closed; audio is added only when a plugin asks for the mic.
_BASE_DEVICES = ("/dev/null", "/dev/zero", "/dev/urandom", "/dev/random", "/dev/tty")
_AUDIO_DEVICES = ("/dev/snd", "/dev/dsp")

# System + interpreter paths a plugin must be able to read to start. Dynamic
# entries (venv, sys.executable, repo root) are added by ``_default_read_paths``.
_SYSTEM_READ_PATHS = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin")

_SYSTEMD_RUN = [
    "systemd-run", "--user", "--scope", "--quiet",
    "-p", "NoNewPrivileges=yes",
    "-p", "RestrictAddressFamilies=AF_UNIX",
    "-p", "PrivateTmp=yes",
    # DevicePolicy=closed + DeviceAllow make the device cgroup default-deny.
    "-p", "DevicePolicy=closed",
] + [arg for dev in _BASE_DEVICES for arg in ("-p", f"DeviceAllow={dev}")]

_BWRAP = [
    "bwrap", "--unshare-all", "--die-with-parent",
    "--ro-bind", "/", "/",
    "--proc", "/proc", "--dev", "/dev",
    # Private, writable scratch space: plugins get their own /tmp + /var/tmp.
    "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
]


@dataclass
class Wrapper:
    kind: str | None  # "systemd-run" | "bwrap" | None
    reason: str
    build: list[str] = field(default_factory=list)

    @property
    def enforced(self) -> bool:
        return self.kind is not None


def _default_read_paths() -> list[str]:
    """Real system + interpreter/venv paths a plugin reads to start.

    Exposed as ``ReadOnlyPaths=`` for the systemd wrapper; the bwrap wrapper
    already mounts the whole root read-only, so it needs no per-path entries.
    """
    repo_root = Path(__file__).resolve().parent.parent
    candidates = list(_SYSTEM_READ_PATHS) + [
        sys.base_prefix,
        sys.prefix,
        str(Path(sys.executable).resolve().parent),
        str(repo_root),
    ]
    paths: list[str] = []
    for raw in candidates:
        path = str(raw)
        if not path or path in paths or not os.path.exists(path):
            continue
        # Skip symlinked roots (e.g. /lib -> /usr/lib): bwrap cannot mount onto
        # a symlink, and the real target is already covered by the root bind.
        if os.path.islink(path):
            continue
        paths.append(path)
    return paths


def _devices_for(permissions: list[str] | None) -> list[str]:
    """Extra device nodes a plugin's *declared* permissions require.

    Only nodes that exist on this host are returned: bwrap fails on a missing
    ``--dev-bind`` source, and an absent node cannot be mounted anyway.
    """
    if permissions and "microphone" in permissions:
        return [dev for dev in _AUDIO_DEVICES if os.path.exists(dev)]
    return []


def _probe(argv: list[str]) -> bool:
    try:
        result = subprocess.run(
            argv + ["--", "/bin/true"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def detect_wrapper(which=shutil.which, probe=None) -> Wrapper:
    """Choose the best *working* hardening wrapper (testable via injection)."""
    if _platform.is_windows():
        # No systemd-run/bwrap on Windows: permissions are advisory, never imply
        # enforcement (TRUST.md §6).
        return Wrapper(None, "Windows: no hardening wrapper; permissions advisory")
    probe = probe or _probe
    if which("systemd-run") and probe(_SYSTEMD_RUN):
        return Wrapper(
            "systemd-run",
            "systemd-run --user --scope (NoNewPrivileges, RestrictAddressFamilies, "
            "PrivateTmp, DevicePolicy/DeviceAllow, ReadOnlyPaths/ReadWritePaths)",
            build=list(_SYSTEMD_RUN),
        )
    if which("bwrap") and probe(_BWRAP):
        return Wrapper(
            "bwrap",
            "bubblewrap (--unshare-all, read-only root, private /tmp, minimal /dev)",
            build=list(_BWRAP),
        )
    return Wrapper(None, "no working hardening wrapper available — permissions are advisory")


def plugin_argv(
    entrypoint: list[str],
    wrapper: Wrapper | None,
    *,
    plugin_id: str,
    permissions: list[str] | None = None,
    read_paths: list[str] | None = None,
    write_paths: list[str] | None = None,
) -> list[str]:
    """Return the argv used to spawn a plugin under ``wrapper``.

    ``permissions`` selects extra device access (audio for ``microphone``);
    ``read_paths``/``write_paths`` are the plugin's declared filesystem needs.
    """
    entry = list(entrypoint)
    if wrapper is None or not wrapper.enforced:
        return entry
    argv = list(wrapper.build)
    if wrapper.kind == "systemd-run":
        for dev in _devices_for(permissions):
            argv += ["-p", f"DeviceAllow={dev}"]
        for path in _default_read_paths() + list(read_paths or ()):
            argv += ["-p", f"ReadOnlyPaths={path}"]
        for path in write_paths or ():
            argv += ["-p", f"ReadWritePaths={path}"]
    elif wrapper.kind == "bwrap":
        # The tmpfs above masks anything that happened to live under /tmp
        # (including, in development checkouts, the repo itself): re-bind the
        # paths the plugin must read so the sandbox stays usable.
        for path in _default_read_paths() + list(read_paths or ()):
            argv += ["--ro-bind", path, path]
        for dev in _devices_for(permissions):
            # --dev /dev gave a minimal device set; re-add only what was declared.
            argv += ["--dev-bind", dev, dev]
        for path in write_paths or ():
            # Root is read-only; re-bind declared write paths back to read-write.
            argv += ["--bind", path, path]
    argv += ["--"] + entry
    return argv


def permission_status(permissions: list[str], wrapper: Wrapper | None) -> list[dict]:
    """Report each permission as ``{name, enforced}`` (advisory when unwrapped)."""
    active = wrapper is not None and wrapper.enforced
    out = []
    for name in permissions or ():
        out.append({"name": name, "enforced": bool(active and name in ENFORCEABLE)})
    return out
