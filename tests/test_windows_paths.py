#!/usr/bin/env python3
"""Windows path coverage for the remaining XDG/POSIX assumptions (P1).

Runs on Linux/macOS without any Windows runtime: it forces ``UTTER_PLATFORM``
and sets ``APPDATA``/``LOCALAPPDATA`` (and clears the XDG vars) to assert the
Windows-shaped paths, then asserts the Linux defaults are unchanged. Hermetic
(no real Windows, no desktop).

Usage::

    .venv-agent/bin/python tests/test_windows_paths.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
# fixtures
# --------------------------------------------------------------------------- #
from utter.router import profiles as profiles_mod  # noqa: E402
from utter.voice import osd as osd_mod  # noqa: E402
from utter.voice import stt as stt_mod  # noqa: E402
from utter import config as config_mod  # noqa: E402
from utter import sleep as sleep_mod  # noqa: E402
from utter import cli as cli_mod  # noqa: E402

_XDG_VARS = ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME",
             "XDG_RUNTIME_DIR", "UTTER_MODELS")


def _reload_profiles() -> None:
    importlib.reload(profiles_mod)


# --------------------------------------------------------------------------- #
# 1. profiles: USER_PROFILES_DIR / GENERATED_PATH / apps-state.json
# --------------------------------------------------------------------------- #
with tempfile.TemporaryDirectory() as td:
    local = Path(td) / "LocalAppData"
    roaming = Path(td) / "AppData"
    try:
        with forced_platform("windows"), env(
            LOCALAPPDATA=str(local), APPDATA=str(roaming),
            XDG_DATA_HOME=None, XDG_STATE_HOME=None, XDG_CONFIG_HOME=None,
        ):
            _reload_profiles()
            check("win USER_PROFILES_DIR -> %APPDATA%/utter/profiles",
                  profiles_mod.USER_PROFILES_DIR == roaming / "utter" / "profiles")
            check("win GENERATED_PATH -> %LOCALAPPDATA%/utter/generated.yaml",
                  profiles_mod.GENERATED_PATH == local / "utter" / "generated.yaml")
            check("win apps-state.json -> %LOCALAPPDATA%/utter/apps-state.json",
                  profiles_mod._state_path() == local / "utter" / "apps-state.json")
    finally:
        _reload_profiles()

    cfg = Path(td) / "cfg"
    data = Path(td) / "data"
    state = Path(td) / "state"
    try:
        with forced_platform("linux"), env(
            XDG_CONFIG_HOME=str(cfg), XDG_DATA_HOME=str(data),
            XDG_STATE_HOME=str(state),
        ):
            _reload_profiles()
            check("linux USER_PROFILES_DIR unchanged",
                  profiles_mod.USER_PROFILES_DIR == cfg / "utter" / "profiles")
            check("linux GENERATED_PATH unchanged",
                  profiles_mod.GENERATED_PATH == data / "utter" / "generated.yaml")
            check("linux apps-state.json unchanged",
                  profiles_mod._state_path() == state / "utter" / "apps-state.json")
    finally:
        _reload_profiles()


# --------------------------------------------------------------------------- #
# 2. osd: runtime-dir helper (Windows temp vs Linux XDG_RUNTIME_DIR)
# --------------------------------------------------------------------------- #
with tempfile.TemporaryDirectory() as td:
    runtime = Path(td) / "runtime"
    with forced_platform("windows"), env(
        LOCALAPPDATA=str(Path(td) / "LocalAppData"), XDG_RUNTIME_DIR=None,
    ):
        check("win osd path -> <temp>/utter/osd.json",
              osd_mod.default_path() == Path(tempfile.gettempdir()) / "utter" / "osd.json")
    with forced_platform("linux"), env(XDG_RUNTIME_DIR=str(runtime)):
        check("linux osd path honours XDG_RUNTIME_DIR",
              osd_mod.default_path() == runtime / "utter" / "osd.json")


# --------------------------------------------------------------------------- #
# 3. stt store root: primary + assistant-missing fallback
# --------------------------------------------------------------------------- #
with tempfile.TemporaryDirectory() as td:
    local = Path(td) / "LocalAppData"
    data = Path(td) / "data"
    with forced_platform("windows"), env(LOCALAPPDATA=str(local), UTTER_MODELS=None,
                                         XDG_DATA_HOME=None):
        check("win stt store (models_root) -> %LOCALAPPDATA%/utter/models",
              stt_mod._store_root() == local / "utter" / "models")
        with patch("assistant.util.models_root", side_effect=RuntimeError("no core")):
            check("win stt store fallback -> %LOCALAPPDATA%/utter/models",
                  stt_mod._store_root() == local / "utter" / "models")
    with forced_platform("linux"), env(XDG_DATA_HOME=str(data), UTTER_MODELS=None):
        check("linux stt store (models_root) -> $XDG_DATA_HOME/utter-models",
              stt_mod._store_root() == data / "utter-models")
        with patch("assistant.util.models_root", side_effect=RuntimeError("no core")):
            check("linux stt store fallback unchanged",
                  stt_mod._store_root() == data / "utter-models")


# --------------------------------------------------------------------------- #
# 4. config dir + cli --config default
# --------------------------------------------------------------------------- #
with tempfile.TemporaryDirectory() as td:
    roaming = Path(td) / "AppData"
    cfg = Path(td) / "cfg"
    with forced_platform("windows"), env(APPDATA=str(roaming), XDG_CONFIG_HOME=None):
        check("win config dir -> %APPDATA%/utter",
              config_mod._xdg_config_dir() == roaming / "utter")
        args = type("Args", (), {"config": None})()
        check("win cli config path -> %APPDATA%/utter/config.toml",
              cli_mod._config_path(args) == roaming / "utter" / "config.toml")
    with forced_platform("linux"), env(XDG_CONFIG_HOME=str(cfg)):
        check("linux config dir unchanged", config_mod._xdg_config_dir() == cfg / "utter")
        args = type("Args", (), {"config": None})()
        check("linux cli config path unchanged",
              cli_mod._config_path(args) == cfg / "utter" / "config.toml")


# --------------------------------------------------------------------------- #
# 5. sleep: no /run/user + os.getuid on Windows; systemd is a no-op
# --------------------------------------------------------------------------- #
with tempfile.TemporaryDirectory() as td:
    runtime = Path(td) / "runtime"
    with forced_platform("windows"), env(LOCALAPPDATA=str(td), XDG_RUNTIME_DIR=None):
        check("win sleep state -> <temp>/utter/sleep.json",
              sleep_mod.state_path() == Path(tempfile.gettempdir()) / "utter" / "sleep.json")
        ctrl = sleep_mod.SleepController()
        check("win SleepController does not manage systemd services",
              ctrl._manages_services is False and ctrl._systemctl is None)
    with forced_platform("linux"), env(XDG_RUNTIME_DIR=str(runtime)):
        check("linux sleep state honours XDG_RUNTIME_DIR",
              sleep_mod.state_path() == runtime / "utter" / "sleep.json")
    if hasattr(os, "getuid"):
        with forced_platform("linux"), env(XDG_RUNTIME_DIR=None):
            check("linux sleep state fallback (/run/user) unchanged",
                  sleep_mod.state_path() == Path(f"/run/user/{os.getuid()}")
                  / "utter" / "sleep.json")

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
