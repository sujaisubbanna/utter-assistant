"""Contract checks for the agent-facing CLI."""
import contextlib
import io
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
