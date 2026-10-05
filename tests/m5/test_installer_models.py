#!/usr/bin/env python3
"""The installer's models step must pull the curated speech model.

Voice needs a model, so the STT tier is the only store source and is accepted
by default (``--yes`` and the wizard's recommended answer). The decision and
vision tiers have no store source and must never be pulled: UI-TARS is sharded
safetensors (``scripts/install_inference.sh``) and the AWQ planner needs
``UTTER_MODEL_DECISION``.

Hermetic: a throwaway ``PREFIX``/``XDG_*`` tree, a fake ``assistant`` that only
logs its arguments, a pseudo-terminal to drive the wizard, and no network.

    .venv-agent/bin/python tests/m5/test_installer_models.py
"""
from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))  # tests/ for _harness

from _harness.report import Report  # noqa: E402

INSTALL = REPO / "install.sh"
DEFAULT_TOML = REPO / "config.default.toml"
FAKE_ASSISTANT = "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$FAKE_LOG\"\nexit 0\n"

STT_DEFAULT = "hf:ggerganov/whisper.cpp:ggml-small.en.bin"


def _pinned_version() -> str:
    """A concrete tag from pyproject.toml so install.sh never calls GitHub."""
    import re
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return "v" + (match.group(1) if match else "0.0.0")


def _sandbox(tmp: Path, *, extra: dict | None = None) -> dict:
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
        "FAKE_LOG": str(tmp / "assistant.log"),
    })
    if extra:
        env.update(extra)
    return env


def _fake_core(tmp: Path) -> None:
    share = tmp / "prefix" / "share" / "utter"
    (share / "assistant").mkdir(parents=True, exist_ok=True)
    (share / "config.default.toml").write_bytes(DEFAULT_TOML.read_bytes())
    fake = tmp / "prefix" / "bin" / "assistant"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(FAKE_ASSISTANT, encoding="utf-8")
    fake.chmod(0o755)


def _run_wizard(tmp: Path, env: dict, *args: str,
                answers: int = 12) -> tuple[int, str]:
    """Run install.sh on a pseudo-terminal, answering 'y' to every prompt."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(["bash", str(INSTALL), *args], cwd=str(REPO), env=env,
                            stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    out = b""
    for _ in range(answers):
        time.sleep(0.2)
        try:
            os.write(master, b"y\n")
        except OSError:
            break
        r, _, _ = select.select([master], [], [], 0.1)
        if r:
            try:
                out += os.read(master, 65536)
            except OSError:
                break
    deadline = time.time() + 120
    while proc.poll() is None and time.time() < deadline:
        r, _, _ = select.select([master], [], [], 0.2)
        if r:
            try:
                out += os.read(master, 65536)
            except OSError:
                break
    try:
        while True:
            out += os.read(master, 65536)
    except OSError:
        pass
    os.close(master)
    return proc.wait(), out.decode("utf-8", errors="replace")


def _log(tmp: Path) -> str:
    path = tmp / "assistant.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    rep = Report()
    print("installer models-step defaults")

    # 1) interactive: STT is recommended and pulled; decision/vision are notes - #
    with tempfile.TemporaryDirectory(prefix="lav-inst-models-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        rc, out = _run_wizard(tmp, _sandbox(tmp), "--only", "models")
        log = _log(tmp)
        rep.check("models step exits 0", rc == 0, f"rc={rc}; {out[-300:]}")
        rep.check("default STT source is pulled",
                  f"models pull {STT_DEFAULT}" in log, log)
        rep.check("STT tier is offered as whisper.cpp / ggml-small.en.bin",
                  "whisper.cpp / ggml-small.en.bin" in out, out[-500:])
        rep.check("STT prompt defaults to yes",
                  "Download the whisper.cpp / ggml-small.en.bin model" in out
                  and "[Y/n]" in out, out[-500:])
        rep.check("vision tier is not given an impossible store pull",
                  "UI-TARS" not in log, log)
        rep.check("vision note points at install_inference.sh",
                  "install_inference.sh" in out, out[-500:])
        rep.check("decision tier is not given an invented source",
                  "models pull decision" not in log, log)
        rep.check("decision note points at UTTER_MODEL_DECISION",
                  "UTTER_MODEL_DECISION" in out, out[-500:])
        rep.check("models component is recorded",
                  "record component models" in out or "ok Models" in out, out[-500:])

    # 2) --yes pulls the speech model without any prompt ---------------------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-models-yes-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        r = subprocess.run(
            ["bash", str(INSTALL), "--only", "models", "--yes"],
            cwd=str(REPO), env=_sandbox(tmp),
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stderr or "") + r.stdout
        log = _log(tmp)
        rep.check("--yes models step exits 0", r.returncode == 0, out[-300:])
        rep.check("--yes pulls the default STT model",
                  f"models pull {STT_DEFAULT}" in log, log)
        rep.check("--yes does not pull the decision/vision tiers",
                  "models pull decision" not in log and "UI-TARS" not in log, log)
        rep.check("--yes records the models component",
                  "ok Models" in out, out[-400:])

    # 3) env overrides still win --------------------------------------------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-models-env-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        rc, _out = _run_wizard(
            tmp, _sandbox(tmp, extra={"UTTER_MODEL_STT": "hf:example/custom:stt.bin"}),
            "--only", "models")
        log = _log(tmp)
        rep.check("env override is pulled", "models pull hf:example/custom:stt.bin" in log, log)
        rep.check("env override replaces the default", STT_DEFAULT not in log, log)

    # 4) --dry-run prints the pull, changes nothing --------------------------- #
    with tempfile.TemporaryDirectory(prefix="lav-inst-models-dry-") as d:
        tmp = Path(d)
        _fake_core(tmp)
        rc, out = _run_wizard(tmp, _sandbox(tmp), "--only", "models", "--dry-run")
        log = _log(tmp)
        rep.check("dry-run exits 0", rc == 0, f"rc={rc}; {out[-300:]}")
        rep.check("dry-run does not pull", "models pull" not in log, log)
        rep.check("dry-run prints the planned pull",
                  "[dry-run]" in out and "models pull" in out and STT_DEFAULT in out,
                  out[-400:])

    summary = rep.summary()
    print(f"\n=== {summary['passed']}/{summary['total']} checks passed, "
          f"{summary['skipped']} skipped ===")
    if rep.failed:
        for c in rep.failed:
            print(f"  - {c['name']}: {c['detail']}")
        return 1
    print("M5 INSTALLER MODELS: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
