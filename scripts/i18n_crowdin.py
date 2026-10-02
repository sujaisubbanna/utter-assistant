#!/usr/bin/env python3
"""Convert between the app's locale sources and Crowdin's JSON format.

Crowdin parses plain JSON, not our TypeScript/Shell locale modules, so this is
the bridge in both directions:

    export  ->  i18n/en.ts + install/i18n/en.sh  ->  crowdin/{ui,installer}-en.json
    import  <-  crowdin/{ui,installer}-<lang>.json -> i18n/<lang>.ts + install/i18n/<lang>.sh

Usage:
    scripts/i18n_crowdin.py export
    scripts/i18n_crowdin.py import            # reads crowdin/*.json, writes locales

The UI source is nested (`app.name`); Crowdin gets a flat dotted-key JSON.
The installer source is keyed by the exact English message; its JSON value is
the same string, and import maps message->translation back into `L10N[...]=...`.

Stdlib only. Run with the repo's Python.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "gui-tauri" / "src" / "i18n"
INST_DIR = REPO / "install" / "i18n"
CROWDIN = REPO / "crowdin"

# Languages Crowdin round-trips. `en` is the source; keep it in sync with
# gui-tauri/src/i18n/index.tsx LANGS and the .crowdin.yml language map.
LANGS = ["es", "de", "fr", "it", "pt", "zh", "ja", "ko", "ru"]

INSTALLER_HEADER = """#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# utter installer locale: {lang}
# MACHINE-DRAFTED / CROWDIN-IMPORTED — unreviewed unless a fluent speaker
# checked it. Corrections go through docs/TRANSLATING.md (Crowdin).
# ---------------------------------------------------------------------------
# Translations are keyed by the exact English message; anything missing falls
# back to English. Values are always printed via %s, never as a printf format.
# `L10N` is declared by install.sh before sourcing this file.
# ---------------------------------------------------------------------------
"""

_SH_LINE = re.compile(r"^L10N\['((?:[^']|'\\'')*)'\]='((?:[^']|'\\'')*)'$")


def _sh_unescape(s: str) -> str:
    return s.replace("'\\''", "'")


def _sh_escape(s: str) -> str:
    return s.replace("'", "'\\''")


# --------------------------------------------------------------------------- #
# UI: en.ts (nested TS) -> flat JSON, and back
# --------------------------------------------------------------------------- #
def _parse_ui_object(lang: str) -> dict:
    """Parse `export const <lang>[: Type] = {…}( as const)?;` out of a UI locale.

    The files are TS modules with unquoted keys and trailing commas, so they are
    not valid JSON. Evaluate the object literal with Node (present in the GUI
    toolchain). Accepts both the `en.ts` shape (`} as const;`) and the locale
    shape (`: Messages = {…};`).
    """
    import shutil
    import subprocess

    src = (UI_DIR / f"{lang}.ts").read_text(encoding="utf-8")
    m = re.search(
        rf"export const {lang}\s*(?::[^=]+)?=\s*([\s\S]*?)\s*(?:as const;|;\s*$)",
        src,
    )
    if not m:
        raise SystemExit(f"could not locate `export const {lang} = {{…}}` in {lang}.ts")
    literal = m.group(1).rstrip()
    if literal.endswith(";"):
        literal = literal[:-1]
    if not shutil.which("node"):
        raise SystemExit("node is required to parse the TS locale files")
    proc = subprocess.run(
        ["node", "-e", f"process.stdout.write(JSON.stringify({literal}))"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"node failed to parse {lang}.ts: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def _ui_en_object() -> dict:
    return _parse_ui_object("en")


def _flatten(obj: dict, prefix: str = "") -> dict:
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = str(v)
    return out


def _unflatten(flat: dict) -> dict:
    root: dict = {}
    for key, value in flat.items():
        node = root
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return root


def _emit_ui_locale(lang: str, flat: dict) -> None:
    # Keep the English structure/order so diffs stay small and key parity holds.
    ordered = {k: flat.get(k, v) for k, v in _flatten(_ui_en_object()).items()}
    tree = _unflatten(ordered)
    header = (
        'import type { Messages } from "./en";\n\n'
        f"/** {lang} — Crowdin-imported. Keys mirror `en.ts`; missing values fall back.\n"
        " *  Unreviewed unless a fluent speaker has checked it (docs/TRANSLATING.md). */\n"
    )
    body = "export const %s: Messages = %s;\n" % (lang, json.dumps(tree, ensure_ascii=False, indent=2))
    (UI_DIR / f"{lang}.ts").write_text(header + body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Installer: en.sh-style keys (English messages) -> JSON, and back to .sh
# --------------------------------------------------------------------------- #
def _installer_english() -> list[str]:
    """The full English installer message set, in a stable order.

    `en` has no locale file (English is inline in install.sh), so the source is
    the **union** of every locale file's keys — not just one file, which may be
    missing entries. Order follows the first file that defines each message so
    the output is deterministic.
    """
    seen: dict[str, None] = {}
    for path in sorted(INST_DIR.glob("*.sh")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _SH_LINE.match(line)
            if m:
                seen.setdefault(_sh_unescape(m.group(1)), None)
    if not seen:
        raise SystemExit(f"no installer messages found in {INST_DIR}")
    return list(seen)


def _emit_installer_locale(lang: str, mapping: dict) -> None:
    lines = [INSTALLER_HEADER.format(lang=lang)]
    for msg in _installer_english():
        value = mapping.get(msg, msg)
        lines.append(f"L10N['{_sh_escape(msg)}']='{_sh_escape(value)}'")
    (INST_DIR / f"{lang}.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
def do_export() -> int:
    CROWDIN.mkdir(exist_ok=True)
    ui = _flatten(_ui_en_object())
    (CROWDIN / "ui-en.json").write_text(json.dumps(ui, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inst = {m: m for m in _installer_english()}
    (CROWDIN / "installer-en.json").write_text(json.dumps(inst, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"exported crowdin/ui-en.json ({len(ui)} strings)")
    print(f"exported crowdin/installer-en.json ({len(inst)} strings)")
    return 0


def do_import() -> int:
    ui_files = sorted(CROWDIN.glob("ui-*.json"))
    inst_files = sorted(CROWDIN.glob("installer-*.json"))
    wrote = 0
    for path in ui_files:
        lang = path.stem.split("-", 1)[1]
        if lang == "en" or lang not in LANGS:
            continue
        _emit_ui_locale(lang, json.loads(path.read_text(encoding="utf-8")))
        print(f"wrote gui-tauri/src/i18n/{lang}.ts")
        wrote += 1
    for path in inst_files:
        lang = path.stem.split("-", 1)[1]
        if lang == "en" or lang not in LANGS:
            continue
        _emit_installer_locale(lang, json.loads(path.read_text(encoding="utf-8")))
        print(f"wrote install/i18n/{lang}.sh")
        wrote += 1
    if wrote == 0:
        print("no non-English crowdin/*.json found; nothing to import", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("export", "import"):
        print("usage: i18n_crowdin.py {export|import}", file=sys.stderr)
        return 2
    return do_export() if argv[1] == "export" else do_import()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
