"""App launch and URL open.

`launch_app` accepts either a desktop-entry id (e.g. "foot", "zen") or a raw
argv string. Desktop entries are parsed from `Exec=` (field codes stripped) and
spawned directly with `subprocess.Popen` list args. No shell is ever used.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from utter.types import Action, ActionResult, Tier

# XDG Exec field codes (%f %F %u %U %d %D %n %N %i %c %k %v %m) plus literal %%.
_FIELD_CODE = re.compile(r"%[fFuUdDnNickvm%]")


def _data_dirs() -> list[Path]:
    dirs: list[Path] = []
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    dirs.append(Path(home) / "applications")
    xdg = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for d in xdg.split(":"):
        if d:
            dirs.append(Path(d) / "applications")
    return dirs


def _find_desktop(app_id: str) -> Path | None:
    name = app_id[:-8] if app_id.endswith(".desktop") else app_id
    for base in _data_dirs():
        candidate = base / f"{name}.desktop"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    # Fall back to a case-insensitive basename match.
    target = name.casefold()
    for base in _data_dirs():
        try:
            entries = list(base.glob("*.desktop"))
        except OSError:
            continue
        for p in entries:
            if p.stem.casefold() == target:
                return p
    return None


def _exec_line(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Desktop Entry" and line.startswith("Exec="):
            return line[5:].strip()
    return None


def _spawn(argv: list[str]) -> tuple[bool, str]:
    if not argv:
        return False, "empty argv"
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, " ".join(argv)
    except OSError as e:
        return False, f"spawn failed: {e}"


def launch_app(app_id_or_argv) -> ActionResult:
    """Launch an app by desktop-entry id, or spawn a raw argv string / list."""
    t0 = time.perf_counter()
    # Already-resolved argv (from a profile or the router): spawn directly.
    if isinstance(app_id_or_argv, (list, tuple)):
        argv = [str(x) for x in app_id_or_argv if str(x)]
        if not argv:
            return ActionResult(False, Action.LAUNCH_APP, Tier.APP, "empty argv",
                                (time.perf_counter() - t0) * 1000)
        ok, detail = _spawn(argv)
        return ActionResult(ok, Action.LAUNCH_APP, Tier.APP, detail,
                            (time.perf_counter() - t0) * 1000)

    spec = (app_id_or_argv or "").strip()
    if not spec:
        return ActionResult(False, Action.LAUNCH_APP, Tier.APP, "empty app spec",
                            (time.perf_counter() - t0) * 1000)

    argv: list[str] | None = None
    desktop = _find_desktop(spec)
    if desktop is not None:
        line = _exec_line(desktop)
        if line:
            cleaned = _FIELD_CODE.sub("", line).strip()
            if cleaned:
                try:
                    argv = shlex.split(cleaned)
                except ValueError:
                    argv = None

    if not argv:
        # Raw argv / binary path. shlex keeps quoting without invoking a shell.
        try:
            candidate = shlex.split(spec)
        except ValueError:
            candidate = [spec]
        if len(candidate) == 1 and " " not in spec and os.path.isabs(spec):
            candidate = [spec]
        argv = candidate or None

    ok, detail = _spawn(argv or [])
    if desktop is not None and ok:
        detail = f"{detail} ({desktop.name})"
    return ActionResult(ok, Action.LAUNCH_APP, Tier.APP, detail,
                        (time.perf_counter() - t0) * 1000)


def _browser_argv(app_id: str) -> list[str] | None:
    """The launch argv of the browser profile matching ``app_id``, if installed."""
    try:
        from utter.router import profiles as _profiles
        profs = _profiles.load()
    except Exception:  # noqa: BLE001 - profiles are optional here
        return None
    a = app_id.lower()
    for prof in profs.values():
        if prof.kind != "browser" or not prof.launch:
            continue
        if a != prof.id.lower() and a not in [x.lower() for x in prof.app_ids]:
            continue
        argv = list(prof.launch) if isinstance(prof.launch, list) else shlex.split(prof.launch)
        if argv and ((os.path.isabs(argv[0]) and os.access(argv[0], os.X_OK)) or shutil.which(argv[0])):
            return argv
    return None


def open_url(url: str, browser_app_id: str | None = None) -> ActionResult:
    """Open a URL (scheme defaults to https).

    When a browser window is already open (``browser_app_id``), the URL goes to
    that browser so it lands as a tab in the window on screen. Otherwise the
    desktop's default handler decides (xdg-open).
    """
    t0 = time.perf_counter()
    target = (url or "").strip()
    if not target:
        return ActionResult(False, Action.OPEN_URL, Tier.APP, "empty url",
                            (time.perf_counter() - t0) * 1000)
    if "://" not in target and not target.startswith(("mailto:", "tel:")):
        target = "https://" + target
    argv = None
    if browser_app_id and target.startswith(("http://", "https://")):
        argv = _browser_argv(browser_app_id)
    ok, detail = _spawn([*(argv or ["xdg-open"]), target])
    return ActionResult(ok, Action.OPEN_URL, Tier.APP, detail,
                        (time.perf_counter() - t0) * 1000)


__all__ = ["launch_app", "open_url"]
