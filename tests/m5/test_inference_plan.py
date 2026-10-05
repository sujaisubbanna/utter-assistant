#!/usr/bin/env python3
"""Platform plans for the inference provisioner + the bash wrapper. Hermetic.

* the Windows plan selects torch/transformers/accelerate (CUDA or CPU wheel),
  and never vLLM;
* Linux keeps vLLM; macOS keeps transformers/torch/accelerate;
* every platform installs the shared client packages;
* ``scripts/install_inference.sh`` delegates to
  ``python -m assistant inference install`` (no provisioning logic of its own).

No network, pip or venv is touched.

    .venv-agent/bin/python tests/m5/test_inference_plan.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from assistant import inference  # noqa: E402

WRAPPER = ROOT / "scripts" / "install_inference.sh"


class PlatformPlanTests(unittest.TestCase):
    def test_linux_uses_vllm(self):
        plan = inference.platform_plan("linux")
        self.assertEqual(plan.platform, "linux")
        self.assertIn("vllm>=0.10", plan.packages)
        self.assertNotIn("transformers>=4.45", plan.packages)
        self.assertNotIn("torch", plan.packages)

    def test_macos_uses_transformers_torch(self):
        plan = inference.platform_plan("macos")
        self.assertEqual(plan.platform, "macos")
        self.assertIn("transformers>=4.45", plan.packages)
        self.assertIn("accelerate>=1.0", plan.packages)
        self.assertIn("torch>=2.2", plan.packages)
        self.assertNotIn("vllm>=0.10", plan.packages)

    def test_windows_cuda_plan(self):
        plan = inference.platform_plan("windows", cuda=True)
        self.assertEqual(plan.platform, "windows")
        self.assertIn("torch", plan.packages)
        self.assertIn("transformers>=4.45", plan.packages)
        self.assertIn("accelerate>=1.0", plan.packages)
        self.assertNotIn("vllm>=0.10", plan.packages)
        # CUDA builds come from the default index; no CPU-only override.
        self.assertTrue(all(step.index_url is None for step in plan.steps))

    def test_windows_cpu_plan_uses_cpu_index(self):
        plan = inference.platform_plan("windows", cuda=False)
        self.assertIn("torch", plan.packages)
        torch_step = next(s for s in plan.steps if "torch" in s.packages)
        self.assertEqual(torch_step.index_url, inference.TORCH_CPU_INDEX)

    def test_all_platforms_install_shared_clients(self):
        for platform_name in ("linux", "macos", "windows"):
            with self.subTest(platform=platform_name):
                packages = inference.platform_plan(platform_name, cuda=False).packages
                self.assertIn("huggingface_hub[cli]", packages)
                self.assertIn("requests>=2.31", packages)
                self.assertIn("Pillow>=10", packages)

    def test_detection_selects_windows_and_probes_cuda(self):
        with mock.patch("assistant.inference._platform_name", return_value="windows"):
            with mock.patch("assistant.inference.cuda_available", return_value=True):
                cuda_plan = inference.platform_plan()
            with mock.patch("assistant.inference.cuda_available", return_value=False):
                cpu_plan = inference.platform_plan()
        self.assertEqual(cuda_plan.platform, "windows")
        torch_step = next(s for s in cpu_plan.steps if "torch" in s.packages)
        self.assertEqual(torch_step.index_url, inference.TORCH_CPU_INDEX)
        self.assertIsNone(
            next(s for s in cuda_plan.steps if "torch" in s.packages).index_url
        )

    def test_venv_python_is_platform_aware(self):
        venv = Path("/tmp/venv")
        self.assertEqual(inference.venv_python(venv, "windows").name, "python.exe")
        self.assertEqual(inference.venv_python(venv, "windows").parent.name, "Scripts")
        self.assertEqual(inference.venv_python(venv, "linux").parent.name, "bin")


class BashWrapperTests(unittest.TestCase):
    def test_wrapper_delegates_statically(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("assistant/inference.py", text)
        self.assertIn("-m assistant inference install", text)
        # The provisioning logic (vLLM, snapshot_download) lives in Python now.
        self.assertNotIn("snapshot_download", text)
        self.assertNotIn("pip install", text)

    def _fake_python_dir(self, tmp: Path) -> tuple[Path, Path]:
        bindir = tmp / "bin"
        bindir.mkdir()
        record = tmp / "args.txt"
        stub = bindir / "python3"
        stub.write_text(
            "#!/bin/sh\n"
            'echo "$@" > "$WRAPPER_ARGS"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return bindir, record

    def test_wrapper_runs_the_python_entrypoint(self):
        with tempfile.TemporaryDirectory(prefix="lav-inference-wrap-") as d:
            tmp = Path(d)
            bindir, record = self._fake_python_dir(tmp)
            env = dict(os.environ)
            env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
            env["WRAPPER_ARGS"] = str(record)
            env.pop("UTTER_INFERENCE_PYTHON", None)
            bash = shutil.which("bash") or "/bin/bash"
            result = subprocess.run(
                [bash, str(WRAPPER)], cwd=str(ROOT), env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(record.read_text(encoding="utf-8").strip(),
                             "-m assistant inference install")

    def test_wrapper_honours_interpreter_override(self):
        with tempfile.TemporaryDirectory(prefix="lav-inference-wrap-") as d:
            tmp = Path(d)
            bindir, record = self._fake_python_dir(tmp)
            stub = bindir / "python3"
            env = dict(os.environ)
            # No python3/python on PATH; the explicit override must be used.
            env["PATH"] = str(tmp / "empty")
            env["UTTER_INFERENCE_PYTHON"] = str(stub)
            env["WRAPPER_ARGS"] = str(record)
            bash = shutil.which("bash") or "/bin/bash"
            result = subprocess.run(
                [bash, str(WRAPPER)], cwd=str(ROOT), env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(record.read_text(encoding="utf-8").strip(),
                             "-m assistant inference install")


if __name__ == "__main__":
    unittest.main()
