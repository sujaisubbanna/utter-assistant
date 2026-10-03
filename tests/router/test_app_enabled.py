#!/usr/bin/env python3
"""Per-app opt-in gate: loader defaults, filtering, merge order, marker (R1-R3, R9).

Run directly::

    .venv-agent/bin/python tests/router/test_app_enabled.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utter.router import profiles as profiles_mod  # noqa: E402
from utter.router.profiles import AppProfile  # noqa: E402


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _curated(tmp: pathlib.Path, *, preselected=("spotify", "firefox")) -> pathlib.Path:
    curated = tmp / "profiles"
    _write(curated / "_defaults.yaml", "defaults: {}\n")
    ids = "\n".join(f"    - {pid}" for pid in preselected)
    _write(curated / "_preselected.yaml", f"preselected:\n  ids:\n{ids}\n")
    return curated


def _generated(tmp: pathlib.Path, ids) -> pathlib.Path:
    gen = tmp / "generated.yaml"
    body = ["profiles:"]
    for pid in ids:
        body += [
            f"  {pid}:",
            f"    id: {pid}",
            f"    name: {pid.title()}",
            "    launch: [/bin/true]",
            "    kind: other",
        ]
    _write(gen, "\n".join(body) + "\n")
    return gen


class PredicateTest(unittest.TestCase):
    def test_is_enabled_and_filter(self):
        on = AppProfile(id="on", name="On", enabled=True)
        off = AppProfile(id="off", name="Off", enabled=False)
        self.assertTrue(profiles_mod.is_enabled(on))
        self.assertFalse(profiles_mod.is_enabled(off))
        self.assertEqual(list(profiles_mod.enabled_profiles({"on": on, "off": off})), ["on"])


class LoaderOptInTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-appgate-"))
        self.curated = _curated(self.tmp)
        self.gen = _generated(self.tmp, ["spotify", "firefox", "vlc"])
        self.user = self.tmp / "user"
        self.state = self.tmp / "state" / "apps-state.json"

    def _load(self):
        return profiles_mod.load(self.curated, user_dir=self.user,
                                 generated_path=self.gen, state_path=self.state)

    def test_preselected_set_is_enabled_others_off(self):
        profs = self._load()
        self.assertTrue(profs["spotify"].enabled)
        self.assertTrue(profs["spotify"].preselected)
        self.assertTrue(profs["firefox"].enabled)
        self.assertFalse(profs["vlc"].enabled)
        self.assertFalse(profs["vlc"].preselected)

    def test_explicit_false_beats_preselected(self):
        _write(self.user / "spotify.yaml", "id: spotify\nenabled: false\n")
        profs = self._load()
        self.assertTrue(profs["spotify"].preselected)
        self.assertFalse(profs["spotify"].enabled)

    def test_explicit_true_enables_non_preselected(self):
        _write(self.user / "vlc.yaml", "id: vlc\nenabled: true\n")
        profs = self._load()
        self.assertTrue(profs["vlc"].enabled)
        self.assertFalse(profs["vlc"].preselected)

    def test_user_override_beats_curated_enabled(self):
        _write(self.curated / "spotify.yaml", "id: spotify\nname: Spotify\nenabled: true\n")
        _write(self.user / "spotify.yaml", "id: spotify\nenabled: false\n")
        profs = self._load()
        self.assertFalse(profs["spotify"].enabled)

    def test_preselected_file_is_not_a_profile(self):
        overrides = profiles_mod._collect_overrides(self.curated)
        self.assertNotIn("_preselected.yaml", overrides)
        self.assertNotIn(profiles_mod.PRESELECTED_NAME, overrides)
        profs = self._load()
        self.assertNotIn("_preselected.yaml", profs)

    def test_gate_only_override_keeps_generated_true(self):
        # An override that only flips `enabled` must not make a generated app
        # look curated (that would change resolve()/the GUI `own` heuristic).
        _write(self.user / "vlc.yaml", "id: vlc\nenabled: true\n")
        profs = self._load()
        self.assertTrue(profs["vlc"].enabled)
        self.assertTrue(profs["vlc"].generated)

    def test_identity_override_flips_generated_false(self):
        _write(self.user / "vlc.yaml", "id: vlc\nname: My VLC\nlaunch: [/bin/vlc]\n")
        profs = self._load()
        self.assertFalse(profs["vlc"].generated)


class HardCutMarkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-appgate-marker-"))
        self.curated = _curated(self.tmp)
        self.gen = _generated(self.tmp, ["spotify", "vlc"])
        self.user = self.tmp / "user"
        self.state = self.tmp / "state" / "apps-state.json"

    def test_first_load_seeds_only_curated_and_writes_marker(self):
        self.assertFalse(self.state.exists())
        profs = profiles_mod.load(self.curated, user_dir=self.user,
                                  generated_path=self.gen, state_path=self.state)
        self.assertTrue(profs["spotify"].enabled)
        self.assertFalse(profs["vlc"].enabled)
        self.assertEqual(json.loads(self.state.read_text()), {"policy_version": 1})

    def test_marker_present_does_not_reseed_user_choice(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text('{"policy_version": 1}\n', encoding="utf-8")
        _write(self.user / "vlc.yaml", "id: vlc\nenabled: true\n")
        profs = profiles_mod.load(self.curated, user_dir=self.user,
                                  generated_path=self.gen, state_path=self.state)
        self.assertTrue(profs["vlc"].enabled)  # explicit choice kept

    def test_markerless_load_does_not_auto_enable_custom_app(self):
        # A user's full custom profile (identity override) is still off under
        # the hard cut; the marker never opts it in.
        _write(self.user / "vlc.yaml", "id: vlc\nname: My VLC\nlaunch: [/bin/vlc]\n")
        profs = profiles_mod.load(self.curated, user_dir=self.user,
                                  generated_path=self.gen, state_path=self.state)
        self.assertFalse(profs["vlc"].enabled)


class LiveReloadTest(unittest.TestCase):
    def test_load_cached_picks_up_an_override_toggle(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="utter-appgate-cache-"))
        curated = _curated(tmp)
        gen = _generated(tmp, ["spotify", "vlc"])
        user = tmp / "user"
        with mock.patch.object(profiles_mod, "PROFILES_DIR", curated), \
                mock.patch.object(profiles_mod, "USER_PROFILES_DIR", user), \
                mock.patch.object(profiles_mod, "GENERATED_PATH", gen), \
                mock.patch.object(profiles_mod, "_PROFILES_CACHE", {}), \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp / "state")}):
            first = profiles_mod.load_cached()
            self.assertFalse(first["vlc"].enabled)
            # A GUI/CLI toggle writes an override; the live cache must refresh.
            _write(user / "vlc.yaml", "id: vlc\nenabled: true\n")
            second = profiles_mod.load_cached()
            self.assertTrue(second["vlc"].enabled)


class DecisionHeadTest(unittest.TestCase):
    def test_disabled_app_never_in_candidates(self):
        from utter.router.decide_candidates import build_candidates
        from utter.types import Context, FocusedWindow

        spotify = AppProfile(id="spotify", name="Spotify", generated=False)
        enabled = profiles_mod.enabled_profiles({"spotify": spotify})
        ctx = Context(focused=FocusedWindow(app_id="firefox", title="x"))
        cands = build_candidates("open spotify", ctx, enabled)
        for cand in cands:
            self.assertNotIn(cand.op, ("ensure_app", "focus_app"),
                             f"disabled app produced {cand}")
        # With the full (enabled) set a non-site app candidate exists.
        cands_on = build_candidates("open code", ctx,
                                    {"code": AppProfile(id="code", name="Code",
                                                        enabled=True, generated=False)})
        self.assertTrue(any(c.op in ("ensure_app", "focus_app") for c in cands_on))


if __name__ == "__main__":
    unittest.main(verbosity=2)
