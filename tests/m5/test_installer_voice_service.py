#!/usr/bin/env python3
"""Regression: a fresh Linux install wires a working voice daemon.

Three defects are guarded here:

* ``install.sh`` only installed/enabled the runner unit, never ``utter.service``
  (``python -m utter.daemon``), so fresh installs had no voice;
* ``systemd/utter.service`` ran the venv python directly, without the session-env
  discovery that ``scripts/utter-daemon-ready.sh`` gives it;
* ``config.default.toml`` defaulted to ``faster_whisper``/``distil-small.en``,
  but the installer pulls the whisper.cpp model ``ggml-small.en.bin``.

The content checks are hermetic contract checks on the files and the real
installer text. The functional check runs the real ``install.sh --only units``
against a throwaway ``PREFIX``/``XDG_*`` tree and a fake core, requiring both
units to land with ``@REPO@`` substituted. A ``systemctl`` stub keeps the host
untouched.

Usage::

    .venv-agent/bin/python tests/m5/test_installer_voice_service.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))  # tests/ for _harness

from _harness.report import Report  # noqa: E402

INSTALL = REPO / "install.sh"
DAEMON_READY = REPO / "scripts" / "utter-daemon-ready.sh"
DAEMON_UNIT = REPO / "systemd" / "utter.service"
RUNNER_UNIT = REPO / "install" / "utter-runner.service"
DEFAULT_TOML = REPO / "config.default.toml"


def _pinned_version() -> str:
    """A concrete tag from pyproject.toml so install.sh never calls GitHub."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return "v" + (match.group(1) if match else "0.0.0")


def _sandbox_env(tmp: Path) -> dict:
    """A minimal hermetic environment rooted entirely inside ``tmp``."""
    env = dict(os.environ)
    env.update({
        "HOME": str(tmp / "home"),
        "PREFIX": str(tmp / "prefix"),
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "XDG_DATA_HOME": str(tmp / "data"),
        "XDG_STATE_HOME": str(tmp / "state"),
        "XDG_CACHE_HOME": str(tmp / "cache"),
        "UTTER_UI": "plain",
        "UTTER_VERSION": _pinned_version(),
        "NO_COLOR": "1",
        "COLUMNS": "100",
    })
    # Stub systemctl so the units step never touches the host user manager.
    binp = tmp / "bin"
    binp.mkdir(parents=True, exist_ok=True)
    stub = binp / "systemctl"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    env["PATH"] = str(binp) + os.pathsep + env.get("PATH", "")
    return env


def _fake_core(tmp: Path) -> Path:
    """A core tree with the assistant dir and both systemd units.

    ``ensure_core_context`` prefers ``$SHARE_DIR`` when ``$SHARE_DIR/assistant``
    exists, so providing it keeps the run offline (no core tarball download).
    """
    share = tmp / "prefix" / "share" / "utter"
    (share / "assistant").mkdir(parents=True, exist_ok=True)
    (share / "config.default.toml").write_bytes(DEFAULT_TOML.read_bytes())
    (share / "install").mkdir(parents=True, exist_ok=True)
    (share / "install" / "utter-runner.service").write_bytes(RUNNER_UNIT.read_bytes())
    (share / "systemd").mkdir(parents=True, exist_ok=True)
    (share / "systemd" / "utter.service").write_bytes(DAEMON_UNIT.read_bytes())
    return share


def _toml_value(text: str, section: str, key: str) -> str:
    """Read a simple ``key = "value"`` string from a TOML section."""
    m = re.search(
        rf"^\[{re.escape(section)}\]\s*$(.*?)(?=^\[|\Z)",
        text, re.M | re.S,
    )
    if not m:
        return ""
    km = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', m.group(1), re.M)
    return km.group(1) if km else ""


def main() -> int:
    rep = Report()
    print("installer voice-service regression (daemon unit + wrapper + STT default)")

    script = INSTALL.read_text(encoding="utf-8")
    toml = DEFAULT_TOML.read_text(encoding="utf-8")

    # 1) install.sh installs systemd/utter.service with @REPO@ substitution ---- #
    rep.check("install.sh installs the daemon unit",
              '"install utter.service"' in script,
              "no 'install utter.service' step found")
    rep.check("install.sh reads the daemon unit from systemd/",
              "systemd/utter.service" in script,
              "no systemd/utter.service source in install.sh")
    rep.check("install.sh substitutes @REPO@ for both units",
              'sed "s|@REPO@|$SHARE_DIR|g"' in script
              and script.count('install_daemon()') >= 1,
              "daemon unit install does not substitute @REPO@")
    rep.check("install.sh records both units for uninstall",
              'D_UNITS=("${names[@]}")' in script,
              "D_UNITS does not carry the installed unit names")
    rep.check("install.sh installs the Linux voice runtime",
              "sounddevice pywhispercpp" in script and "pywhispercpp" in script,
              "voice runtime deps not in the venv install")

    # 2) the wrapper exists and execs the daemon ------------------------------ #
    wrapper = DAEMON_READY.read_text(encoding="utf-8") if DAEMON_READY.is_file() else ""
    rep.check("scripts/utter-daemon-ready.sh exists", DAEMON_READY.is_file(),
              str(DAEMON_READY))
    rep.check("wrapper is executable",
              DAEMON_READY.is_file() and os.access(DAEMON_READY, os.X_OK),
              "not executable")
    rep.check("wrapper execs `python -m utter.daemon`",
              'exec "$PY" -m utter.daemon' in wrapper,
              wrapper[-200:])
    rep.check("wrapper discovers the Wayland session socket",
              "WAYLAND_DISPLAY" in wrapper and "XDG_RUNTIME_DIR" in wrapper,
              "no session-env discovery")
    rep.check("wrapper discovers the D-Bus / niri session",
              "DBUS_SESSION_BUS_ADDRESS" in wrapper and "NIRI_SOCKET" in wrapper,
              "no bus/niri discovery")
    rep.check("daemon unit execs the wrapper, not a bare python",
              'ExecStart=@REPO@/scripts/utter-daemon-ready.sh' in
              DAEMON_UNIT.read_text(encoding="utf-8"),
              "ExecStart not rewritten")

    # 3) the STT default matches the model the installer pulls ---------------- #
    rep.check("config.default.toml [stt] backend is whisper_cpp",
              _toml_value(toml, "stt", "backend") == "whisper_cpp",
              _toml_value(toml, "stt", "backend"))
    rep.check("config.default.toml [stt] model is ggml-small.en.bin",
              _toml_value(toml, "stt", "model") == "ggml-small.en.bin",
              _toml_value(toml, "stt", "model"))
    rep.check("installer pulls the whisper.cpp model the config names",
              "hf:ggerganov/whisper.cpp:ggml-small.en.bin" in script,
              "installer STT default source changed")
    rep.check("config keeps device + compute_type",
              "device =" in toml and "compute_type =" in toml,
              "device/compute_type keys missing")

    # 4) functional: --only units installs both, @REPO@ substituted ----------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-voice-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        r = subprocess.run(
            ["bash", str(INSTALL), "--only", "units", "--yes"],
            cwd=str(REPO), env=_sandbox_env(tmp),
            capture_output=True, text=True, timeout=180,
        )
        unit_dir = tmp / "config" / "systemd" / "user"
        runner = unit_dir / "utter-runner.service"
        daemon = unit_dir / "utter.service"
        share = tmp / "prefix" / "share" / "utter"
        rep.check("units step exits 0", r.returncode == 0,
                  (r.stderr or r.stdout)[-300:])
        rep.check("utter-runner.service is installed", runner.is_file(), str(runner))
        rep.check("utter.service is installed", daemon.is_file(), str(daemon))
        if daemon.is_file():
            body = daemon.read_text(encoding="utf-8")
            rep.check("daemon unit has no literal @REPO@", "@REPO@" not in body, body[:200])
            rep.check("daemon unit points at the installed core",
                      str(share) in body, body[:200])

    summary = rep.summary()
    print(f"\n=== {summary['passed']}/{summary['total']} checks passed, "
          f"{summary['skipped']} skipped ===")
    if rep.failed:
        print("FAILED:")
        for c in rep.failed:
            print(f"  - {c['name']}: {c['detail']}")
        return 1
    print("M5 INSTALLER VOICE SERVICE: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
