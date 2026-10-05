#!/usr/bin/env python3
"""Windows STT is whisper.cpp + ``ggml-small.en.bin``, and it is mandatory.

Hermetic: parses ``pyproject.toml``, ``install.ps1`` and ``docs/WINDOWS.md``.
It never executes PowerShell and never needs a Windows host, so it runs in the
Linux/macOS ``verify`` job.

    .venv-agent/bin/python tests/platform/test_windows_stt.py
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
INSTALL_PS1 = ROOT / "install.ps1"
WINDOWS_DOC = ROOT / "docs" / "WINDOWS.md"

MODEL_SOURCE = "hf:ggerganov/whisper.cpp:ggml-small.en.bin"
MODEL_SHA256 = "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"
MODEL_BYTES = 487614201

ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}{(' -> ' + extra) if extra and not cond else ''}")


def ps_function(script: str, name: str) -> str:
    """Body of a top-level PowerShell ``function name { ... }`` ('' if absent)."""
    match = re.search(rf"^function\s+{re.escape(name)}\b.*?^\}}", script, re.S | re.M)
    return match.group(0) if match else ""


# --------------------------------------------------------------------------- #
# 1. the `windows` extra ships pywhispercpp (mandatory STT)
# --------------------------------------------------------------------------- #
data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
windows_extra = data["project"]["optional-dependencies"]["windows"]
normalised = [d.split(";", 1)[0].strip() for d in windows_extra]

check("windows extra includes pywhispercpp>=1.5",
      any(re.match(r"pywhispercpp\s*>=\s*1\.5\b", dep, re.I) for dep in normalised),
      repr(windows_extra))

# The old comment claimed the win_amd64 wheel was unconfirmed; it is not.
pyproject_text = PYPROJECT.read_text(encoding="utf-8")
for stale in ("not guaranteed", "is left out", "not been confirmed", "unconfirmed"):
    check(f"pyproject no longer claims '{stale}'", stale not in pyproject_text)

# --------------------------------------------------------------------------- #
# 2. install.ps1 installs the extra and a mandatory, unskippable model step
# --------------------------------------------------------------------------- #
ps = INSTALL_PS1.read_text(encoding="utf-8")
install_venv = ps_function(ps, "Install-AgentVenv")
model_fn = ps_function(ps, "Install-WhisperModel")
main_fn = ps_function(ps, "Main")

check("install.ps1 installs the windows extra", "[windows]" in install_venv)
check("windows extra install is not optional/failure-tolerant",
      "Invoke-Native" in install_venv and "-AllowFailure" not in install_venv)

check("install.ps1 defines Install-WhisperModel", bool(model_fn))
check("model step pins the exact hf source", MODEL_SOURCE in ps)
check("model step pins the sha256", MODEL_SHA256 in ps)
check("model step pins the byte size", str(MODEL_BYTES) in ps)

check("model step calls `assistant models pull`",
      re.search(r"['\"]models['\"]\s*,\s*['\"]pull['\"]", model_fn) is not None)
check("model step publishes a Fail path",
      re.search(r"\bFail\s+\"", model_fn) is not None)

# Main must call it at top level (4-space indent), not behind an `if`.
check("Main calls Install-WhisperModel unconditionally",
      re.search(r"(?m)^    Install-WhisperModel\s*$", main_fn) is not None,
      main_fn)

# There must be no skip switch for the model anywhere.
skip_names = ("SkipWhisper", "SkipModel", "SkipStt", "SkipSTT", "WhisperOptional")
for name in skip_names:
    check(f"no '{name}' skip switch exists", name not in ps)

# --------------------------------------------------------------------------- #
# 3. docs/WINDOWS.md documents the mandatory flow + fallback
# --------------------------------------------------------------------------- #
doc = WINDOWS_DOC.read_text(encoding="utf-8")
check("WINDOWS.md calls the model mandatory", "mandatory" in doc.lower())
check("WINDOWS.md documents CPU-by-default", "CPU" in doc and "whisper.cpp" in doc)
check("WINDOWS.md documents the pinned binary fallback",
      "whisper-bin-x64.zip" in doc and "b5130" in doc and "whisper-cli.exe" in doc)
check("WINDOWS.md keeps CUDA opt-in", "CUDA is opt-in" in doc or "CUDA is **opt-in" in doc)

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
