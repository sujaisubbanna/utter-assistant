"""App launch and URL open on Windows.

Same result contract as :mod:`utter.actions.launch`
(:class:`~utter.types.ActionResult`, ``Action.LAUNCH_APP`` / ``Action.OPEN_URL``).

* An app name is resolved to a Start-Menu ``.lnk`` (per-user first, then
  all-users) and handed to the shell; a raw argv list is spawned directly.
* A URL / file path / absolute executable is opened with ``os.startfile``
  (falling back to ``ShellExecuteW``), so the user's default handler decides.

No shell is ever invoked. ``shell32``/``ctypes.WinDLL`` are imported lazily;
on a non-Windows host the module imports cleanly and its helpers are unit-tested.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from utter import platform
from utter.types import Action, ActionResult, Tier

_SW_SHOWNORMAL = 1


def _start_menu_dirs() -> list[Path]:
    """Per-user then all-users Start-Menu *Programs* directories (existing only).

    Reads ``%APPDATA%`` / ``%PROGRAMDATA%`` (pure; unit-tested on Linux).
    """
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        candidates.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        candidates.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return candidates


def _lnk_search_dirs(dirs=None) -> list[Path]:
    """The directories :func:`find_lnk` scans (existing ones unless injected)."""
    if dirs is not None:
        return [Path(d) for d in dirs]
    return [d for d in _start_menu_dirs() if d.is_dir()]


def find_lnk(app_id: str, dirs=None) -> Optional[Path]:
    """Locate a Start-Menu ``.lnk`` for ``app_id`` (pure; unit-tested).

    Exact stem match (case-insensitive) wins over a substring match; per-user
    directories are scanned before all-users ones. Returns ``None`` when nothing
    matches. ``dirs`` can be injected for tests.
    """
    name = str(app_id or "").strip()
    if name.lower().endswith(".lnk"):
        name = name[:-4]
    if not name:
        return None
    target = name.casefold()

    candidates: list[Path] = []
    for base in _lnk_search_dirs(dirs):
        try:
            candidates.extend(p for p in base.rglob("*.lnk") if p.is_file())
        except OSError:
            continue
    for path in candidates:
        if path.stem.casefold() == target:
            return path
    for path in candidates:
        if target in path.stem.casefold():
            return path
    return None


def _spawn(argv: list[str]) -> tuple[bool, str]:
    """Spawn an already-resolved argv directly (no shell), like the Unix path."""
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
    except OSError as exc:
        return False, f"spawn failed: {exc}"


def _shell_execute(target: str, params: Optional[str] = None) -> tuple[bool, str]:
    """``ShellExecuteW(..., "open", target, params, ...)`` (HINSTANCE > 32 = ok)."""
    if not platform.is_windows():
        return False, "windows only"
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int,
        ]
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        rc = shell32.ShellExecuteW(None, "open", target, params, None, _SW_SHOWNORMAL)
        code = int(rc or 0)
        if code > 32:
            return True, target
        return False, f"ShellExecuteW failed ({code})"
    except Exception as exc:  # noqa: BLE001
        return False, f"ShellExecuteW error: {exc}"


def _open_target(target: str, params: Optional[str] = None) -> tuple[bool, str]:
    """Open a file/``.lnk``/URL via ``os.startfile``, falling back to the shell."""
    target = (target or "").strip()
    if not target:
        return False, "empty target"
    if params is None:
        try:
            os.startfile(target)  # type: ignore[attr-defined] - Windows only
            return True, target
        except (OSError, AttributeError):
            pass
    return _shell_execute(target, params)


def launch_app(app_id_or_argv) -> ActionResult:
    """Launch an app by name (Start-Menu ``.lnk``) or spawn a raw argv list."""
    t0 = time.perf_counter()
    if isinstance(app_id_or_argv, (list, tuple)):
        argv = [str(x) for x in app_id_or_argv if str(x)]
        if not argv:
            return ActionResult(False, Action.LAUNCH_APP, Tier.APP, "empty argv",
                                (time.perf_counter() - t0) * 1000)
        ok, detail = _spawn(argv)
        return ActionResult(ok, Action.LAUNCH_APP, Tier.APP, detail,
                            (time.perf_counter() - t0) * 1000)

    spec = str(app_id_or_argv or "").strip()
    if not spec:
        return ActionResult(False, Action.LAUNCH_APP, Tier.APP, "empty app spec",
                            (time.perf_counter() - t0) * 1000)

    lnk = find_lnk(spec)
    if lnk is not None:
        ok, detail = _open_target(str(lnk))
        if ok:
            detail = f"{detail} ({lnk.name})"
        return ActionResult(ok, Action.LAUNCH_APP, Tier.APP, detail,
                            (time.perf_counter() - t0) * 1000)

    ok, detail = _open_target(spec)
    return ActionResult(ok, Action.LAUNCH_APP, Tier.APP, detail,
                        (time.perf_counter() - t0) * 1000)


def open_url(url: str, browser_app_id: str | None = None) -> ActionResult:
    """Open a URL (scheme defaults to https) with the default handler.

    When ``browser_app_id`` names an installed browser, its Start-Menu ``.lnk``
    is used with the URL as a parameter so the tab lands in that browser.
    """
    t0 = time.perf_counter()
    target = str(url or "").strip()
    if not target:
        return ActionResult(False, Action.OPEN_URL, Tier.APP, "empty url",
                            (time.perf_counter() - t0) * 1000)
    if "://" not in target and not target.startswith(("mailto:", "tel:")):
        target = "https://" + target

    if browser_app_id:
        lnk = find_lnk(browser_app_id)
        if lnk is not None:
            ok, detail = _open_target(str(lnk), params=target)
            return ActionResult(ok, Action.OPEN_URL, Tier.APP, detail,
                                (time.perf_counter() - t0) * 1000)

    ok, detail = _open_target(target)
    return ActionResult(ok, Action.OPEN_URL, Tier.APP, detail,
                        (time.perf_counter() - t0) * 1000)


__all__ = ["launch_app", "open_url", "find_lnk"]
