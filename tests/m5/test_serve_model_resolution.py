#!/usr/bin/env python3
"""The vLLM serving scripts must resolve a model from the store / checkout / HF.

``scripts/resolve_model.sh`` is the shared resolver sourced by
``serve_planner.sh`` and ``serve_vision.sh``. Hermetic: a throwaway
``REPO_ROOT`` and store, no vLLM, no network.

    .venv-agent/bin/python tests/m5/test_serve_model_resolution.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
HELPER = REPO / "scripts" / "resolve_model.sh"


def _resolve(repo_root: Path, *args: str, env: dict | None = None,
             models: str | None = None) -> subprocess.CompletedProcess:
    full = dict(os.environ)
    full["REPO_ROOT"] = str(repo_root)
    if models is not None:
        full["UTTER_MODELS"] = models
    if env:
        full.update(env)
    script = f'source "{HELPER}"; resolve_model "$@"'
    return subprocess.run(["bash", "-c", script, "_", *args],
                          env=full, capture_output=True, text=True)


def main() -> int:
    failed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            failed += 1
            if detail:
                print(f"       {detail.strip()}")

    print("serve-script model resolution")

    with tempfile.TemporaryDirectory(prefix="lav-serve-") as d:
        tmp = Path(d)
        store = tmp / "store"

        # 1) override wins verbatim
        r = _resolve(tmp, "/custom/model", "UTTER_VISION_MODEL_PATH",
                     "UI-TARS-2B-SFT", "ByteDance-Seed/UI-TARS-2B-SFT")
        check("env override is used verbatim", r.stdout == "/custom/model", r.stdout)

        # 2) a full local checkout is preferred over the HF id
        (tmp / "models" / "UI-TARS-2B-SFT").mkdir(parents=True)
        r = _resolve(tmp, "", "UTTER_VISION_MODEL_PATH",
                     "UI-TARS-2B-SFT", "ByteDance-Seed/UI-TARS-2B-SFT")
        check("local checkout is used",
              r.stdout == str(tmp / "models" / "UI-TARS-2B-SFT"), r.stdout)

        # 3) a store-only entry warns and falls back to the HF repo id
        (tmp / "models" / "UI-TARS-2B-SFT").rmdir()
        manifest = (store / "manifests" / "huggingface.co" / "ByteDance-Seed"
                    / "UI-TARS-2B-SFT" / "latest.json")
        manifest.parent.mkdir(parents=True)
        blob = tmp / "blob"
        blob.write_bytes(b"weights")
        manifest.write_text(
            '{"name":"UI-TARS-2B-SFT","files":'
            f'[{{"name":"model.safetensors","path":"{blob}"}}]}}',
            encoding="utf-8")
        r = _resolve(tmp, "", "UTTER_VISION_MODEL_PATH",
                     "UI-TARS-2B-SFT", "ByteDance-Seed/UI-TARS-2B-SFT",
                     models=str(store))
        check("store-only hit falls back to the HF repo id",
              r.stdout == "ByteDance-Seed/UI-TARS-2B-SFT", r.stdout)
        check("store-only hit explains the blob limitation",
              "content-addressed" in r.stderr, r.stderr)

        # 4) no store / no checkout / no HF id is a clear, non-zero error
        r = _resolve(tmp, "", "UTTER_PLANNER_MODEL_PATH",
                     "Qwen3-4B-Instruct-2507-AWQ-4bit", "",
                     models=str(tmp / "empty"))
        check("missing model errors non-zero", r.returncode != 0, str(r.returncode))
        check("missing model names the override",
              "UTTER_PLANNER_MODEL_PATH" in r.stderr, r.stderr)

    print(f"\n{'FAILED' if failed else 'SERVE MODEL RESOLUTION: OK'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
