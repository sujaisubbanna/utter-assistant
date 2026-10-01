"""Guard tests for the consolidated hardware probes (utter/hardware.py).

These pin the shared probe shapes that ``utter.cli``, ``utter.runtime`` and
``assistant.recommend`` all rely on, plus the fact that they now delegate to a
single implementation instead of carrying private copies.
"""
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from utter import hardware


class HardwareProbeTests(unittest.TestCase):
    def test_gpu_info_nvidia_shape(self):
        with patch.object(hardware.shutil, "which",
                          side_effect=lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None), \
             patch.object(hardware.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX\n")):
            self.assertEqual(
                hardware.gpu_info(),
                {"available": True, "name": "NVIDIA GeForce RTX", "runtime": "cuda"},
            )

    def test_gpu_info_absent_shape(self):
        fake_drm = MagicMock()
        fake_drm.glob.return_value = []
        with patch.object(hardware.shutil, "which", return_value=None), \
             patch.object(hardware, "Path", return_value=fake_drm):
            self.assertEqual(
                hardware.gpu_info(),
                {"available": False, "name": None, "runtime": "unknown"},
            )

    def test_nvidia_gpus_shape(self):
        with patch.object(hardware.shutil, "which", return_value="/usr/bin/nvidia-smi"), \
             patch.object(hardware.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stdout="RTX 5090, 32607\n")):
            self.assertEqual(
                hardware.nvidia_gpus(),
                [{"name": "RTX 5090", "vendor": "nvidia", "vram_gb": 31.8}],
            )

    def test_lspci_gpus_shape(self):
        stdout = "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3090]\n"
        with patch.object(hardware.shutil, "which", return_value="/usr/bin/lspci"), \
             patch.object(hardware.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stdout=stdout)):
            gpus = hardware.lspci_gpus()
        self.assertEqual(len(gpus), 1)
        self.assertEqual(gpus[0]["vendor"], "nvidia")
        self.assertEqual(gpus[0]["vram_gb"], 0.0)
        self.assertIn("GeForce RTX 3090", gpus[0]["name"])

    def test_probe_macos_gpu_shape(self):
        with patch.object(hardware.shutil, "which", return_value=None):
            info = hardware.probe_macos_gpu()
        self.assertEqual(
            set(info),
            {"available", "name", "runtime", "unified_memory_gb"},
        )
        self.assertTrue(info["available"])
        self.assertEqual(info["runtime"], "metal")

    def test_cli_gpu_info_delegates_to_hardware(self):
        from utter import cli
        with patch.object(hardware.shutil, "which",
                          side_effect=lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None), \
             patch.object(hardware.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX\n")):
            self.assertEqual(
                cli._gpu_info(),
                {"available": True, "name": "NVIDIA GeForce RTX", "runtime": "cuda"},
            )

    def test_recommend_probe_hardware_uses_shared_probes(self):
        from assistant import recommend
        with patch.object(recommend, "_nvidia_gpus",
                          return_value=[{"name": "Card", "vendor": "nvidia", "vram_gb": 8.0}]):
            hw = recommend.probe_hardware()
        self.assertEqual(hw["gpus"], [{"name": "Card", "vendor": "nvidia", "vram_gb": 8.0}])


if __name__ == "__main__":
    unittest.main()
