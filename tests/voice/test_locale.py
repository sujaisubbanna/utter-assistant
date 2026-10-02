#!/usr/bin/env python3
"""Spoken-language resolution (``utter/locale.py``) — pure, injected env.

    .venv-agent/bin/python tests/voice/test_locale.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter import locale


class TestNormalizeLocale(unittest.TestCase):
    def test_posix_locales(self):
        self.assertEqual(locale.normalize_locale("en_GB.UTF-8"), "en-GB")
        self.assertEqual(locale.normalize_locale("de_DE"), "de-DE")
        self.assertEqual(locale.normalize_locale("de_DE.utf8@euro"), "de-DE")
        self.assertEqual(locale.normalize_locale("pt_BR.UTF-8"), "pt-BR")
        self.assertEqual(locale.normalize_locale("en"), "en")
        self.assertEqual(locale.normalize_locale("es_419"), "es-419")

    def test_bcp47_passthrough(self):
        self.assertEqual(locale.normalize_locale("en-GB"), "en-GB")
        self.assertEqual(locale.normalize_locale("zh-hans"), "zh-Hans")
        self.assertEqual(locale.normalize_locale("sr_RS@latin"), "sr-RS")

    def test_unknown_is_none(self):
        for raw in ("", None, "C", "POSIX", "C.UTF-8", "not a locale", "en_US_extra_region"):
            self.assertIsNone(locale.normalize_locale(raw), raw)

    def test_base_and_english(self):
        self.assertEqual(locale.base_language("en-GB"), "en")
        self.assertEqual(locale.base_language("de-DE"), "de")
        self.assertIsNone(locale.base_language(None))
        self.assertTrue(locale.is_english("en-GB"))
        self.assertFalse(locale.is_english("de-DE"))
        self.assertFalse(locale.is_english(None))


class TestResolve(unittest.TestCase):
    def test_auto_uses_env_precedence(self):
        env = {"LC_ALL": "de_DE.UTF-8", "LC_MESSAGES": "fr_FR.UTF-8", "LANG": "es_ES.UTF-8"}
        self.assertEqual(locale.resolve("auto", env), "de-DE")
        self.assertEqual(locale.resolve("", env), "de-DE")
        self.assertEqual(locale.resolve(None, env), "de-DE")

    def test_auto_skips_unset_and_c_locale(self):
        env = {"LC_ALL": "", "LC_MESSAGES": "C", "LANG": "en_GB.UTF-8"}
        self.assertEqual(locale.resolve("auto", env), "en-GB")
        self.assertIsNone(locale.resolve("auto", {}))
        self.assertIsNone(locale.resolve("auto", {"LANG": "C.UTF-8"}))
        self.assertIsNone(locale.resolve("auto", {"LANG": "POSIX"}))

    def test_explicit_code(self):
        self.assertEqual(locale.resolve("de_DE", {"LANG": "en_US.UTF-8"}), "de-DE")
        self.assertEqual(locale.resolve("en-GB", {}), "en-GB")
        self.assertEqual(locale.resolve("es", {}), "es")

    def test_invalid_explicit_is_none_not_english(self):
        self.assertIsNone(locale.resolve("klingon", {"LANG": "de_DE.UTF-8"}))
        self.assertIsNone(locale.resolve("!!", {}))


if __name__ == "__main__":
    unittest.main()