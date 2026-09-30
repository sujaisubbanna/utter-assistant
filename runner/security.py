"""Plugin hardening wrapper selection and per-permission enforceability.

When ``[security] enforce = true`` the runner prefers ``systemd-run --user
--scope`` (NoNewPrivileges, RestrictAddressFamilies, ReadOnlyPaths, ...), falls
back to ``bwrap``, and otherwise runs unhardened while marking every permission
**advisory** (TRUST.md §6: never imply safety that isn't enforced).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

# Permissions a supported wrapper can actually constrain.
ENFORCEABLE = {
    "microphone": "DeviceAllow",
    "filesystem.read": "ReadOnlyPaths",
    "filesystem.write": "ReadWritePaths",
    "network": "RestrictAddressFamilies",
    "device": "DeviceAllow",
}

_SYSTEMD_RUN = [
    "systemd-run", "--user", "--scope", "--quiet",
    "-p", "NoNewPrivileges=yes",
    "-p", "RestrictAddressFamilies=AF_UNIX",
    "-p", "PrivateTmp=no",
]
_BWRAP = [
    "bwrap", "--unshare-all", "--die-with-parent",
    "--proc", "/proc", "--dev", "/dev",
    "--ro-bind", "/", "/",
]


@dataclass
class Wrapper:
    kind: str | None  # "systemd-run" | "bwrap" | None
    reason: str
    build: list[str] = field(default_factory=list)

    @property
    def enforced(self) -> bool:
        return self.kind is not None


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
    probe = probe or _probe
    if which("systemd-run") and probe(_SYSTEMD_RUN):
        return Wrapper(
            "systemd-run",
            "systemd-run --user --scope (NoNewPrivileges, RestrictAddressFamilies, "
            "ReadOnlyPaths)",
            build=list(_SYSTEMD_RUN),
        )
    if which("bwrap") and probe(_BWRAP):
        return Wrapper(
            "bwrap",
            "bubblewrap (--unshare-all, read-only root)",
            build=list(_BWRAP),
        )
    return Wrapper(None, "no working hardening wrapper available — permissions are advisory")


def plugin_argv(
    entrypoint: list[str],
    wrapper: Wrapper | None,
    *,
    plugin_id: str,
    read_paths: list[str] | None = None,
    write_paths: list[str] | None = None,
) -> list[str]:
    """Return the argv used to spawn a plugin under ``wrapper``."""
    entry = list(entrypoint)
    if wrapper is None or not wrapper.enforced:
        return entry
    argv = list(wrapper.build)
    if wrapper.kind == "systemd-run":
        for path in read_paths or ():
            argv += ["-p", f"ReadOnlyPaths={path}"]
        for path in write_paths or ():
            argv += ["-p", f"ReadWritePaths={path}"]
    argv += ["--"] + entry
    return argv


def permission_status(permissions: list[str], wrapper: Wrapper | None) -> list[dict]:
    """Report each permission as ``{name, enforced}`` (advisory when unwrapped)."""
    active = wrapper is not None and wrapper.enforced
    out = []
    for name in permissions or ():
        out.append({"name": name, "enforced": bool(active and name in ENFORCEABLE)})
    return out
