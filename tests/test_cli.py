"""Contract checks for the agent-facing CLI."""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from utter import cli


class CliContractTests(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_schema_golden(self):
        code, raw, _ = self.run_cli(["schema", "--json"])
        obj = json.loads(raw)
        self.assertEqual(code, 0)
        self.assertEqual(obj["schema"], "utter.cli/v1")
        self.assertEqual(set(obj), {"schema", "ok", "command", "data"})
        self.assertEqual(obj["data"]["exit_codes"], cli.EXIT)
        self.assertEqual(obj["data"]["error_codes"], cli.ERROR_CODES)
        self.assertEqual(set(obj["data"]["commands"]), set(cli.COMMANDS))
        schema_file = pathlib.Path(__file__).resolve().parents[1] / "utter" / "data" / "cli.schema.json"
        formal = json.loads(schema_file.read_text(encoding="utf-8"))
        self.assertEqual(obj["data"]["json_schema"], formal)
        self.assertEqual(formal["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("settings", formal["$defs"])
        self.assertIn("commands", formal["$defs"])

    def test_json_stdout_and_stderr_separation(self):
        code, raw, err = self.run_cli(["version", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(raw)["schema"], "utter.cli/v1")

    def test_backend_error_contract(self):
        with patch.object(cli, "_tts_engine", return_value=None):
            code, raw, err = self.run_cli(["speak", "hello", "--json"])
        self.assertEqual(code, 4)
        self.assertEqual(err, "")
        obj = json.loads(raw)
        self.assertEqual(obj["error"]["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(cli.ERROR_CODES[obj["error"]["code"]], code)

    def test_dictation_dry_run(self):
        code, raw, _ = self.run_cli(["dictation", "hello", "--dry-run", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(raw)["data"]["dry_run"])

    def test_confirmation_contract(self):
        code, raw, err = self.run_cli(["assistant", "open youtube", "--json"])
        obj = json.loads(raw)
        self.assertEqual(code, 3)
        self.assertEqual(err, "")
        self.assertEqual(obj["error"]["code"], "E_BLOCKED")
        self.assertEqual(cli.ERROR_CODES[obj["error"]["code"]], code)

    def _run_real_preview(self, args):
        repo = pathlib.Path(__file__).resolve().parents[1]
        return subprocess.run([sys.executable, "-X", "faulthandler", "-m", "utter.cli", *args],
                              cwd=repo, capture_output=True, text=True, timeout=6)

    def test_real_process_dry_run_flags_before_subcommand(self):
        proc = self._run_real_preview(["--dry-run", "assistant", "open youtube", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        obj = json.loads(proc.stdout)
        self.assertEqual(obj["schema"], "utter.cli/v1")
        self.assertTrue(obj["data"]["accepted"])
        self.assertTrue(obj["data"]["dry_run"])
        self.assertTrue(obj["data"]["plan"]["steps"])

    def test_real_process_dry_run_flags_after_subcommand(self):
        proc = self._run_real_preview(["assistant", "open youtube", "--dry-run", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        obj = json.loads(proc.stdout)
        self.assertEqual(obj["schema"], "utter.cli/v1")
        self.assertTrue(obj["data"]["accepted"])
        self.assertTrue(obj["data"]["dry_run"])
        self.assertTrue(obj["data"]["plan"]["steps"])

    def test_real_daemon_text_dry_run_bypasses_handle_utterance(self):
        repo = pathlib.Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, "-X", "faulthandler", "-m", "utter.daemon",
                               "--text", "open youtube", "--dry-run", "--json-plan"],
                              cwd=repo, capture_output=True, text=True, timeout=6)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        preview = json.loads(proc.stdout)
        self.assertTrue(preview["accepted"])
        self.assertTrue(preview["plan"]["steps"])

    def test_real_daemon_text_dry_run_without_json_plan_exits(self):
        repo = pathlib.Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, "-X", "faulthandler", "-m", "utter.daemon",
                               "--text", "open youtube", "--dry-run"],
                              cwd=repo, capture_output=True, text=True, timeout=6)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY-RUN ensure_url", proc.stderr)

    def test_missing_confirmation_is_fast_without_tty_or_stdin_read(self):
        class NonTty:
            def isatty(self): return False
            def read(self, *_args): raise AssertionError("CLI must not read stdin for confirmation")
        with patch("sys.stdin", NonTty()), patch("builtins.input", side_effect=AssertionError("must not prompt")):
            code, raw, err = self.run_cli(["assistant", "open youtube", "--json"])
        self.assertEqual((code, err), (3, ""))
        self.assertEqual(json.loads(raw)["error"]["code"], "E_BLOCKED")

    def test_usage_errors_are_json_with_documented_exit_code(self):
        code, raw, err = self.run_cli(["settings", "set", "audio.sample_rate", "--json"])
        self.assertEqual((code, err), (2, ""))
        obj = json.loads(raw)
        self.assertEqual(obj["command"], "usage")
        self.assertEqual(obj["error"]["code"], "E_USAGE")
        self.assertEqual(cli.ERROR_CODES[obj["error"]["code"]], code)

    def test_unknown_action_app_uses_schema_command_name(self):
        with patch.object(cli, "_profiles", return_value={}):
            code, raw, err = self.run_cli(["actions", "list", "--app", "missing", "--json"])
        self.assertEqual((code, err), (5, ""))
        obj = json.loads(raw)
        self.assertEqual(obj["command"], "actions list")
        self.assertEqual(obj["error"]["code"], "E_NOT_FOUND")

    def test_settings_get_and_dry_run_set(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = pathlib.Path(directory) / "config.toml"
            code, raw, _ = self.run_cli(["settings", "get", "audio.sample_rate", "--config", str(cfg), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(raw)["data"]["value"], 16000)
            code, raw, _ = self.run_cli(["settings", "set", "audio.sample_rate", "--value", "48000", "--dry-run", "--config", str(cfg), "--json"])
            self.assertEqual(code, 0)
            self.assertFalse(cfg.exists())
            self.assertFalse(json.loads(raw)["data"]["written"])

    def test_settings_write_preserves_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = pathlib.Path(directory) / "config.toml"
            cfg.write_text("[audio]\n# keep this comment\nsample_rate = 16000\n", encoding="utf-8")
            code, raw, err = self.run_cli(["settings", "set", "audio.sample_rate", "--value", "48000", "--confirm", "--config", str(cfg), "--json"])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("# keep this comment", cfg.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(raw)["data"]["written"], True)

    def test_first_settings_write_copies_shipped_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = pathlib.Path(directory) / "config.toml"
            code, _, err = self.run_cli(["settings", "set", "audio.sample_rate", "--value", "48000", "--confirm", "--config", str(cfg), "--json"])
            self.assertEqual((code, err), (0, ""))
            import tomllib
            saved = tomllib.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(saved["audio"]["sample_rate"], 48000)
            self.assertEqual(saved["general"]["trigger"], "hotkey")

    def test_custom_phrase_maps_to_keyboard_candidate(self):
        from utter.router import rules
        from utter.router.profiles import AppProfile
        from utter.types import Context, FocusedWindow, Action
        profile = AppProfile(id="firefox", name="Firefox", kind="browser", commands={"make it loud": "ctrl+up"})
        plan = rules.plan("Make it loud!", Context(focused=FocusedWindow(app_id="firefox")), {"firefox": profile})
        self.assertIsNotNone(plan)
        self.assertEqual(plan.steps[0].action, Action.KEY)
        self.assertEqual(plan.steps[0].args, {"chord": "ctrl+up"})

    def test_commands_set_persists_custom_phrase(self):
        from utter.router.profiles import AppProfile
        with tempfile.TemporaryDirectory() as directory:
            override = pathlib.Path(directory) / "firefox.yaml"
            with patch("utter.router.profiles.load", return_value={"firefox": AppProfile(id="firefox", name="Firefox")}), patch.object(cli, "_profile_override_path", return_value=override):
                code, raw, err = self.run_cli(["commands", "set", "firefox", "toggle developer tools", "ctrl+shift+i", "--confirm", "--json"])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(raw)["data"]["phrase"], "toggle developer tools")
            import yaml
            self.assertEqual(yaml.safe_load(override.read_text(encoding="utf-8"))["commands"], {"toggle developer tools": "ctrl+shift+i"})

    def test_gpu_detection_uses_local_runtime_probe(self):
        with patch.object(cli.shutil, "which", side_effect=lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None), patch.object(cli.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX\n")):
            self.assertEqual(cli._gpu_info(), {"available": True, "name": "NVIDIA GeForce RTX", "runtime": "cuda"})


if __name__ == "__main__":
    unittest.main()
