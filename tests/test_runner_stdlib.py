#!/usr/bin/env python3
"""Guard: ``runner/**`` stays stdlib-only and never shells out.

Invariant (AGENTS.md): ``runner/**`` is stdlib-only and contains no
``shell=True`` / ``os.system``. ``utter/`` may keep guarded optional imports;
the runner trust boundary may not depend on third-party code or the shell.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "runner"


def _modules() -> list[Path]:
    return sorted(p for p in RUNNER.rglob("*.py") if "__pycache__" not in p.parts)


def _third_party_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in sys.stdlib_module_names:
                    bad.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import within runner
                continue
            if node.module:
                top = node.module.split(".")[0]
                if top not in sys.stdlib_module_names:
                    bad.append((node.lineno, node.module))
    return bad


def _shell_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                bad.append((node.lineno, "shell=True"))
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("system", "popen"):
            base = func.value
            if isinstance(base, ast.Name) and base.id == "os":
                bad.append((node.lineno, f"os.{func.attr}"))
    return bad


class TestRunnerIsStdlibOnly(unittest.TestCase):
    def test_no_third_party_imports(self):
        modules = _modules()
        self.assertTrue(modules, f"no modules found under {RUNNER}")
        offenders = {str(p.relative_to(ROOT)): hits for p in modules
                     if (hits := _third_party_imports(p))}
        self.assertEqual(offenders, {}, f"runner/** must be stdlib-only: {offenders}")

    def test_no_shell_execution(self):
        offenders = {str(p.relative_to(ROOT)): hits for p in _modules()
                     if (hits := _shell_calls(p))}
        self.assertEqual(offenders, {}, f"runner/** must not use the shell: {offenders}")


if __name__ == "__main__":
    unittest.main()
