#!/usr/bin/env python3
"""App profiles layer as: installed-app catalogue < curated < yours.

Your profiles (~/.config/utter/profiles) are ordered first, and a small edit
file saved by the settings app merges into a full profile instead of replacing it.

Usage::

    .venv-agent/bin/python tests/actions/test_profile_layers.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utter.router import profiles as P  # noqa: E402

ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(f"{'ok ' if cond else 'BAD'} {name}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    curated, user = root / "curated", root / "user"
    curated.mkdir(); user.mkdir()
    (curated / "_defaults.yaml").write_text("defaults: {}\n")
    (curated / "browser_firefox.yaml").write_text(
        "id: firefox\nname: Firefox\naliases: [firefox, browser]\nlaunch: [firefox]\n"
        "shortcuts: {new_tab: ctrl+t}\napp_ids: [firefox]\nkind: browser\n")
    (user / "browser_zen.yaml").write_text(
        "id: zen\nname: Zen\naliases: [zen, browser]\nlaunch: [zen-bin]\n"
        "shortcuts: {new_tab: ctrl+t, close_tab: ctrl+w}\napp_ids: [zen]\nkind: browser\n")
    (user / "zen.yaml").write_text("id: zen\nshortcuts: {close_tab: ctrl+shift+w}\n")        # an edit
    (user / "firefox.yaml").write_text("id: firefox\nshortcuts: {reload: F5}\n")              # edit a curated app
    gen = root / "generated.yaml"
    gen.write_text("profiles:\n  gimp:\n    id: gimp\n    name: GIMP\n    aliases: [gimp]\n    launch: [gimp]\n")

    profs = P.load(curated, user_dir=user, generated_path=gen)
    check("'browser' resolves to your Zen, not curated Firefox", P.resolve("browser", profs).id == "zen")
    check("edit merged into your full Zen profile", profs["zen"].shortcuts == {"new_tab": "ctrl+t", "close_tab": "ctrl+shift+w"})
    check("edit kept Zen's launch command", profs["zen"].launch == ["zen-bin"])
    check("edit merged into curated Firefox", profs["firefox"].shortcuts == {"new_tab": "ctrl+t", "reload": "F5"})
    check("catalogue app still available", "gimp" in profs)
    check("your profiles come first", list(profs)[0] == "zen")

print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
