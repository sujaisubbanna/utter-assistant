#!/usr/bin/env python3
"""Regression: the installer ships a discoverable "Utter" launcher.

The GUI step writes ``~/.local/share/applications/utter-gui.desktop``. Two
defects are guarded here:

* the entry was named ``utter Settings`` with ``Categories=Settings;`` and could
  be invisible on KDE until ``update-desktop-database`` ran;
* an uninstall only removes what the per-component record lists, so the desktop
  entry must stay in the GUI component's ``files``.

The content check is a hermetic contract check on the heredoc actually present
in ``install.sh`` (rendered with sample values). The cleanup check is
functional: it builds a throwaway install-state record, runs the real
``install.sh --uninstall --yes`` against a sandbox, and requires the entry to be
gone. Nothing touches the host: everything lives under a temp HOME and
``systemctl`` is a stub on PATH.

Usage::

    .venv-agent/bin/python tests/m5/test_installer_launcher.py
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


def _desktop_content(script: str, gui_bin: str, icon: str) -> str:
    """Render the GUI desktop-entry heredoc with sample values."""
    m = re.search(
        r'cat > "\$DESKTOP_FILE" <<DESKTOP\n(.*?)\nDESKTOP\n',
        script, re.S,
    )
    if not m:
        return ""
    body = m.group(1)
    rendered = body.replace("$GUI_BIN", gui_bin).replace("$ICON_NAME", icon)
    return rendered + "\n"


def _sandbox_env(tmp: Path) -> dict:
    env = dict(os.environ)
    env.update({
        "HOME": str(tmp),
        "PREFIX": str(tmp / "prefix"),
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "XDG_DATA_HOME": str(tmp / "data"),
        "XDG_STATE_HOME": str(tmp / "state"),
        "XDG_CACHE_HOME": str(tmp / "cache"),
        "UTTER_UI": "plain",
        "NO_COLOR": "1",
    })
    # Stub systemctl so uninstall never touches the host user manager.
    binp = tmp / "bin"
    binp.mkdir(parents=True, exist_ok=True)
    stub = binp / "systemctl"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    env["PATH"] = str(binp) + os.pathsep + env.get("PATH", "")
    return env


def main() -> int:
    rep = Report()
    print("installer launcher regression (Utter desktop entry + uninstall)")

    script = INSTALL.read_text(encoding="utf-8")

    # 1) the generated entry is a discoverable "Utter" launcher ---------------- #
    entry = _desktop_content(script, "/opt/utter/bin/utter-gui", "org.utter.settings")
    rep.check("desktop heredoc is present", bool(entry), "no <<DESKTOP block found")
    rep.check("entry is named Utter", "Name=Utter\n" in entry, entry[:200])
    rep.check("entry runs the GUI binary",
              "Exec=/opt/utter/bin/utter-gui\n" in entry, entry[:200])
    rep.check("entry uses the installed icon",
              "Icon=org.utter.settings\n" in entry, entry[:200])
    rep.check("entry is a non-terminal application",
              "Terminal=false\n" in entry, entry[:200])
    rep.check("entry sets a WM class for KDE",
              "StartupWMClass=utter\n" in entry, entry[:200])
    cats = re.search(r"^Categories=(.*)$", entry, re.M)
    rep.check("Categories are Utility + Accessibility",
              bool(cats) and "Utility;" in cats.group(1)
              and "Accessibility;" in cats.group(1),
              cats.group(1) if cats else "(missing)")
    rep.check("installer refreshes the desktop database",
              "update-desktop-database" in script, "no update-desktop-database call")
    rep.check("GUI component records the desktop entry for uninstall",
              re.search(r'D_FILES=\("\$GUI_BIN" "\$DESKTOP_FILE"', script) is not None,
              "D_FILES does not include $DESKTOP_FILE")

    # 2) uninstall removes the recorded entry ---------------------------------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-launcher-") as d:
        tmp = Path(d)
        comp = tmp / "state" / "utter" / "components" / "gui"
        comp.mkdir(parents=True)
        desktop = tmp / "data" / "applications" / "utter-gui.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text("[Desktop Entry]\nName=Utter\n", encoding="utf-8")
        (comp / "label").write_text("GUI (appimage)\n", encoding="utf-8")
        (comp / "keep").write_text("0\n", encoding="utf-8")
        (comp / "files").write_text(str(desktop) + "\n", encoding="utf-8")

        r = subprocess.run(
            ["bash", str(INSTALL), "--uninstall", "--yes"],
            cwd=str(REPO), env=_sandbox_env(tmp),
            capture_output=True, text=True, timeout=120,
        )
        rep.check("uninstall exits 0", r.returncode == 0,
                  (r.stderr or r.stdout)[-300:])
        rep.check("uninstall removes the desktop entry", not desktop.exists(), str(desktop))
        rep.check("uninstall removes the component record", not comp.exists(), str(comp))

    summary = rep.summary()
    print(f"\n=== {summary['passed']}/{summary['total']} checks passed, "
          f"{summary['skipped']} skipped ===")
    if rep.failed:
        print("FAILED:")
        for c in rep.failed:
            print(f"  - {c['name']}: {c['detail']}")
        return 1
    print("M5 INSTALLER LAUNCHER: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
