#!/usr/bin/env python3
"""Windows detection + path/dependency seams (P0 plumbing).

Runs on Linux/macOS without any Windows runtime: it forces ``UTTER_PLATFORM``
and, where needed, monkeypatches ``sys.platform`` and the Windows env vars. It
must stay hermetic (no real Windows, no desktop).

Usage::

    .venv-agent/bin/python tests/platform/test_windows_detection.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}{(' -> ' + extra) if extra and not cond else ''}")


class forced_platform:
    """Context manager forcing ``UTTER_PLATFORM`` (None = unset)."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.prev = os.environ.get("UTTER_PLATFORM")
        if self.value is None:
            os.environ.pop("UTTER_PLATFORM", None)
        else:
            os.environ["UTTER_PLATFORM"] = self.value
        return self

    def __exit__(self, *exc):
        if self.prev is None:
            os.environ.pop("UTTER_PLATFORM", None)
        else:
            os.environ["UTTER_PLATFORM"] = self.prev


class env:
    """Context manager setting/removing env vars (None = remove) and restoring."""

    def __init__(self, **kw):
        self.kw = kw
        self.saved: dict = {}

    def __enter__(self):
        for key, value in self.kw.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --------------------------------------------------------------------------- #
# 1. detection: WINDOWS value, is_windows(), aliases, sys.platform
# --------------------------------------------------------------------------- #
from utter import platform  # noqa: E402

with forced_platform("windows"):
    check("UTTER_PLATFORM=windows -> is_windows only",
          platform.is_windows() and not platform.is_linux() and not platform.is_macos())
    check("WINDOWS constant + name()", platform.WINDOWS == "windows" and platform.name() == "windows")

for alias in ("windows", "win", "win32", "cygwin", "msys"):
    with forced_platform(alias):
        check(f"UTTER_PLATFORM={alias} -> windows", platform.is_windows())

for plat in ("win32", "cygwin", "msys"):
    with patch.object(platform.sys, "platform", plat), forced_platform(None):
        check(f"sys.platform={plat} -> windows", platform.name() == "windows" and platform.is_windows())

with forced_platform("linux"):
    check("UTTER_PLATFORM=linux keeps is_linux", platform.is_linux() and not platform.is_windows())
with forced_platform("darwin"):
    check("UTTER_PLATFORM=darwin keeps is_macos", platform.is_macos() and not platform.is_windows())

# --------------------------------------------------------------------------- #
# 2. deps: the module imports on Windows and the report is well-formed
# --------------------------------------------------------------------------- #
import assistant.deps as deps  # noqa: E402

with forced_platform("windows"):
    deps_report = deps.probe_deps()

check("assistant.deps imports on Windows and reports a dict",
      isinstance(deps_report, dict) and bool(deps_report))
check("windows deps list native tools (powershell/nvidia-smi/ollama)",
      all(k in deps_report for k in ("powershell", "nvidia-smi", "ollama")))
check("windows native tool values are bool",
      all(isinstance(deps_report[k], bool) for k in ("powershell", "nvidia-smi", "ollama")))
check("windows unimplemented backends are advisory",
      all(deps_report.get(k) == deps.ADVISORY for k in ("wasapi_audio", "win32_input", "win32_screen")))
check("missing_deps handles advisory string values",
      isinstance(deps.missing_deps(deps_report), list)
      and "wasapi_audio" not in deps.missing_deps(deps_report))

# --------------------------------------------------------------------------- #
# 3. util path helpers: Windows-shaped under a forced platform
# --------------------------------------------------------------------------- #
from assistant import util  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    local = Path(td) / "LocalAppData"
    roaming = Path(td) / "AppData"
    with forced_platform("windows"), env(
        LOCALAPPDATA=str(local), APPDATA=str(roaming),
        XDG_DATA_HOME=None, XDG_STATE_HOME=None, XDG_CONFIG_HOME=None,
        XDG_RUNTIME_DIR=None, UTTER_MODELS=None,
    ):
        check("win xdg_data_home -> %LOCALAPPDATA%", util.xdg_data_home() == local)
        check("win xdg_state_home -> %LOCALAPPDATA%", util.xdg_state_home() == local)
        check("win xdg_config_home -> %APPDATA%", util.xdg_config_home() == roaming)
        check("win state_dir -> %LOCALAPPDATA%/utter", util.state_dir() == local / "utter")
        check("win config_dir -> %APPDATA%/utter", util.config_dir() == roaming / "utter")
        check("win models_root -> %LOCALAPPDATA%/utter/models",
              util.models_root() == local / "utter" / "models")
        check("win runner_sock_path stays under a temp dir",
              util.runner_sock_path().endswith("runner.sock"))

    with forced_platform("windows"), env(
        LOCALAPPDATA=str(local), APPDATA=str(roaming),
        UTTER_MODELS=str(local / "custom-models"),
    ):
        check("UTTER_MODELS override wins on Windows",
              util.models_root() == local / "custom-models")

# Linux/macOS results are unchanged.
with tempfile.TemporaryDirectory() as td:
    xstate = Path(td) / "state"
    with forced_platform("linux"), env(XDG_STATE_HOME=str(xstate), UTTER_MODELS=None):
        check("linux state_dir unchanged", util.state_dir() == xstate / "utter")

# --------------------------------------------------------------------------- #
# 4. doctor: platform-specific "start the runner" hint (Linux text unchanged)
# --------------------------------------------------------------------------- #
from assistant import doctor  # noqa: E402

with forced_platform("windows"):
    win_hint = doctor._runner_start_hint()
with forced_platform("linux"):
    linux_hint = doctor._runner_start_hint()

check("windows runner hint points at Settings", "Settings" in win_hint and "systemctl" not in win_hint)
check("linux runner hint is byte-identical to before",
      linux_hint == "Start it with: systemctl --user start utter-runner.service")

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
