#!/usr/bin/env python3
"""Guard: the Linux installer's recommended defaults are opt-out.

The owner requirement is that everything needed to use Utter is installed by
default and the user *unselects* what they do not want. This pins the two
hardware-sensitive defaults by extracting the real shell functions and running
them in a tiny harness:

* ``stt`` (the curated whisper.cpp speech model backend) is always recommended
  **and mandatory** — ``--skip``/``--only`` and the wizard's ``n``/``s`` answers
  cannot drop it;
* ``perception`` (vLLM vision + planner) is recommended **only** when an NVIDIA
  GPU with enough VRAM is present, and stays selectable either way.

It is hermetic: a stub ``nvidia-smi`` supplies the VRAM query, and the "no GPU"
case runs with an empty PATH so a real card on the CI host cannot leak in. The
mandatory-STT checks either extract the real shell functions and run them in a
tiny harness, or drive ``install.sh`` against a throwaway PREFIX with a fake
``assistant`` (no network).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
BASH = shutil.which("bash") or "/bin/bash"


def _function_source(name: str) -> str:
    """Return the top-level shell function ``name`` verbatim from install.sh."""
    src = INSTALL.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", src, re.S | re.M)
    assert match is not None, f"{name} not found in install.sh"
    return match.group(0)


# Stubs for everything compute_recommendations() reads besides the GPU probe.
_HARNESS_PRELUDE = """\
set -u
declare -A REC_BY_ID=()
missing_pkgs() { :; }
GUI_AVAILABLE=1
WITH_NOCTALIA=0
CONFIG_FILE=/nonexistent/utter/config.toml
PERCEPTION_MIN_VRAM_MB=8192
"""


def _run(script: str, *, path: str | None = None) -> str:
    with tempfile.TemporaryDirectory() as d:
        runner = Path(d) / "run.sh"
        runner.write_text(script, encoding="utf-8")
        env = dict(os.environ)
        if path is not None:
            env["PATH"] = path
        out = subprocess.run(
            [BASH, str(runner)], capture_output=True, text=True, env=env
        )
        assert out.returncode == 0, out.stderr
        return out.stdout


def _recommendation_script() -> str:
    return (
        _HARNESS_PRELUDE
        + _function_source("perception_gpu_ok")
        + "\n"
        + _function_source("compute_recommendations")
        + "\ncompute_recommendations\n"
        + 'printf "stt=%s\\nperception=%s\\n" '
        '"${REC_BY_ID[stt]}" "${REC_BY_ID[perception]}"\n'
    )


class InstallerDefaultsTests(unittest.TestCase):
    def test_stt_defaults_on_without_gpu(self):
        # Empty PATH: no nvidia-smi, so perception is off — but STT must be on.
        with tempfile.TemporaryDirectory() as d:
            out = _run(_recommendation_script(), path=d)
        self.assertIn("stt=y", out)
        self.assertIn("perception=n", out)

    def test_perception_defaults_on_with_sufficient_gpu(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            bindir.mkdir()
            fake = bindir / "nvidia-smi"
            fake.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                "  *memory.total*) echo 24564 ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            out = _run(
                _recommendation_script(),
                path=f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            )
        self.assertIn("stt=y", out)
        self.assertIn("perception=y", out)

    def test_perception_off_with_small_gpu(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            bindir.mkdir()
            fake = bindir / "nvidia-smi"
            fake.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                "  *memory.total*) echo 4096 ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            out = _run(
                _recommendation_script(),
                path=f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            )
        self.assertIn("perception=n", out)

    def test_plan_copy_says_installed_by_default(self):
        src = INSTALL.read_text(encoding="utf-8")
        match = re.search(r"^print_plan\(\) \{.*?^\}", src, re.S | re.M)
        assert match is not None, "print_plan not found in install.sh"
        plan = match.group(0)
        self.assertIn("installed", plan)
        self.assertIn("unselected", plan)
        self.assertIn("NVIDIA", plan)
        # The speech model is now mandatory; the plan must say it cannot be skipped.
        self.assertIn("cannot be skipped", plan)
        # The old "opt-in" wording must be gone.
        self.assertNotIn("opt-in", plan)


# --------------------------------------------------------------------------- #
# Mandatory STT: the speech model cannot be skipped.
# --------------------------------------------------------------------------- #

_COMP_IDS = [
    "deps", "core", "lang", "units", "models",
    "gui", "stt", "perception", "noctalia", "config",
]
_COMP_LABELS = [
    "System deps", "Core runner + CLI", "Language", "systemd user units",
    "Models", "GUI", "STT backend", "Perception (vision server deps)",
    "Noctalia widget (optional)", "Config",
]


def _array_literal(name: str, values: list[str]) -> str:
    return f'{name}=(' + " ".join(f'"{v}"' for v in values) + ")\n"


def _decision_script(decisions: dict[str, str], models_yes: str,
                     only: list[str] | None = None,
                     skip: list[str] | None = None) -> str:
    """Run the real enforce_mandatory() over a full decision table."""
    vals = [decisions.get(c, "skip") for c in _COMP_IDS]
    only_body = " ".join(f"[{c}]=1" for c in (only or []))
    skip_body = " ".join(f"[{c}]=1" for c in (skip or []))
    return (
        "set -u\n"
        + f"declare -A ONLY_MAP=({only_body}) SKIP_MAP=({skip_body})\n"
        + _array_literal("COMP_IDS", _COMP_IDS)
        + _array_literal("COMP_LABELS", _COMP_LABELS)
        + _array_literal("DECISION", vals)
        + f'MODELS_YES="{models_yes}"\n'
        + "note_f() { printf 'NOTE: %s\\n' \"$*\"; }\n"
        + _function_source("decision_of") + "\n"
        + _function_source("is_mandatory") + "\n"
        + _function_source("flag_excluded") + "\n"
        + _function_source("enforce_mandatory") + "\n"
        + "enforce_mandatory\n"
        + 'for c in "${COMP_IDS[@]}"; do printf "%s=%s\\n" "$c" "$(decision_of "$c")"; done\n'
        + 'printf "models_yes=%s\\n" "$MODELS_YES"\n'
    )


def _allowed_script(only: list[str], skip: list[str]) -> str:
    """Run the real allowed()/flag_excluded() with --only/--skip maps."""
    only_body = " ".join(f"[{c}]=1" for c in only)
    skip_body = " ".join(f"[{c}]=1" for c in skip)
    return (
        "set -u\n"
        + f"declare -A ONLY_MAP=({only_body})\n"
        + f"declare -A SKIP_MAP=({skip_body})\n"
        + _function_source("is_mandatory") + "\n"
        + _function_source("flag_excluded") + "\n"
        + _function_source("allowed") + "\n"
        + 'for id in models stt deps gui core; do '
          'allowed "$id" && printf "%s=allow\\n" "$id" || printf "%s=deny\\n" "$id"; done\n'
    )


class MandatorySttTests(unittest.TestCase):
    """Runs the real enforcement functions; mirrors the wizard's n/s/--skip path."""

    def test_enforce_overrides_skip_all(self):
        # Every component recorded skip — what "s" (skip all) produces.
        out = _run(_decision_script({c: "skip" for c in _COMP_IDS}, ""))
        self.assertIn("models=yes", out)
        self.assertIn("stt=yes", out)
        self.assertIn("models_yes=stt", out)
        self.assertIn("NOTE:", out)
        self.assertIn("mandatory", out)

    def test_enforce_overrides_only_and_skip_flags(self):
        # The plan the wizard reaches with --skip stt / --skip models, or with
        # --only core,gui: mandatory steps are skipped, everything else chosen.
        out = _run(_decision_script(
            {c: "skip" for c in _COMP_IDS} | {"core": "yes", "gui": "yes"}, ""))
        self.assertIn("models=yes", out)
        self.assertIn("stt=yes", out)
        self.assertIn("models_yes=stt", out)

    def test_enforce_is_quiet_when_already_installed(self):
        out = _run(_decision_script({c: "yes" for c in _COMP_IDS}, "stt"))
        self.assertNotIn("NOTE:", out)
        self.assertIn("models=yes", out)
        self.assertIn("stt=yes", out)
        self.assertIn("models_yes=stt", out)

    def test_flag_excluded_notes_even_when_already_yes(self):
        # --yes records yes before enforce runs, but --skip was still ignored,
        # so the user is told rather than having the flag silently no-op.
        out = _run(_decision_script(
            {c: "yes" for c in _COMP_IDS}, "stt", skip=["models", "stt"]))
        self.assertIn("NOTE:", out)
        self.assertIn("models_yes=stt", out)

    def test_enforce_appends_stt_to_partial_csv(self):
        out = _run(_decision_script({c: "yes" for c in _COMP_IDS}, "vision"))
        self.assertIn("models_yes=vision,stt", out)

    def test_skip_flag_cannot_exclude_mandatory(self):
        out = _run(_allowed_script([], ["models", "stt"]))
        self.assertIn("models=allow", out)
        self.assertIn("stt=allow", out)

    def test_only_flag_cannot_exclude_mandatory(self):
        out = _run(_allowed_script(["core", "gui"], []))
        self.assertIn("models=allow", out)
        self.assertIn("stt=allow", out)
        self.assertIn("core=allow", out)
        self.assertIn("gui=allow", out)
        self.assertIn("deps=deny", out)


# --------------------------------------------------------------------------- #
# End-to-end: install.sh still pulls the speech model when it is skipped.
# --------------------------------------------------------------------------- #

_STT_DEFAULT = "hf:ggerganov/whisper.cpp:ggml-small.en.bin"


def _pinned_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return "v" + (match.group(1) if match else "0.0.0")


def _sandbox(tmp: Path) -> dict:
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
    return env


def _fake_core(tmp: Path) -> None:
    """A core tree with a fake `assistant` that only logs its arguments."""
    share = tmp / "prefix" / "share" / "utter"
    (share / "assistant").mkdir(parents=True, exist_ok=True)
    (share / "config.default.toml").write_text(
        (ROOT / "config.default.toml").read_text(encoding="utf-8"), encoding="utf-8")
    fake = tmp / "prefix" / "bin" / "assistant"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$FAKE_LOG\"\nexit 0\n",
        encoding="utf-8")
    fake.chmod(0o755)


class MandatorySttIntegrationTests(unittest.TestCase):
    def test_skip_stt_and_models_still_pulls_speech_model(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _fake_core(tmp)
            r = subprocess.run(
                [BASH, str(INSTALL), "--only", "models",
                 "--skip", "models,stt", "--yes"],
                cwd=str(ROOT), env=_sandbox(tmp),
                capture_output=True, text=True, timeout=180,
            )
            log = tmp / "assistant.log"
            logged = log.read_text(encoding="utf-8") if log.is_file() else ""
        self.assertEqual(r.returncode, 0, (r.stderr or r.stdout)[-500:])
        self.assertIn(f"models pull {_STT_DEFAULT}", logged)

    def test_only_core_gui_keeps_stt_in_dry_run_plan(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _fake_core(tmp)
            r = subprocess.run(
                [BASH, str(INSTALL), "--only", "core,gui",
                 "--skip", "stt", "--yes", "--dry-run"],
                cwd=str(ROOT), env=_sandbox(tmp),
                capture_output=True, text=True, timeout=180,
            )
        out = (r.stdout or "") + (r.stderr or "")
        self.assertEqual(r.returncode, 0, out[-500:])
        self.assertIn("models accepted: stt", out)
        self.assertIn("pull stt model", out)


if __name__ == "__main__":
    unittest.main()
