#!/usr/bin/env python3
"""Enumerate installed GUI apps from .desktop files.

Produces two artefacts (both committed):

* ``~/.local/share/utter/apps.json`` — the raw catalog: one entry per desktop file,
  keyed by desktop-file basename (without ``.desktop``).
* ``~/.local/share/utter/generated.yaml`` — a bulk set of minimal ``AppProfile``
  entries keyed by the same id, so *every* installed app is resolvable by
  spoken name even when it has no hand-written curated profile.

Only the standard library is required for parsing; PyYAML is used to emit the
generated profile file (it is already a runtime dependency of utter).

Run::

    scripts/gen_app_catalog.py            # write both files
    scripts/gen_app_catalog.py --dry-run  # print counts, write nothing
"""
from __future__ import annotations

import argparse
import os
import json
import shlex
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a declared dependency
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
# Machine-specific output: the catalogue describes *this* computer's apps, so it
# lives in the user's data dir, not in the repo.
_DATA = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share")) / "utter"
DEFAULT_OUT = _DATA / "apps.json"
DEFAULT_PROFILES_DIR = _DATA / "generated.yaml"

# Highest precedence first (XDG_DATA_DIRS order, user dirs before system).
DESKTOP_DIRS = [
    Path.home() / ".local/share/applications",
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
]

# Field codes stripped from Exec. %u/%U mean "accepts URLs"; %f/%F files.
FIELD_CODES = {"%f", "%F", "%u", "%U", "%i", "%c", "%k", "%d", "%%"}

# Entries that are really plumbing (MIME/url handlers, plugins, daemons).
HELPER_IDS = {
    "avahi-discover",
    "bssh",
    "bvnc",
    "cmake-gui",
    "gcr-prompter",
    "gcr-viewer",
}
HELPER_SUBSTRINGS = ("-url-handler", "-uri-handler", "-geo-handler", "-plugin-")
HELPER_PREFIXES = ("wine-extension-",)


def _cli_agent_names() -> set[str]:
    """Spoken CLI-agent names that must not become keyword aliases.

    A desktop entry's Keywords may include "codex" (e.g. ChatGPT), which would
    otherwise make a generated profile shadow the real ``codex`` CLI agent.
    """
    path = REPO_ROOT / "utter" / "data" / "cli_agents.json"
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    return {str(k).strip().lower() for k in data if k != "terminal" and str(k).strip()}


# Ordered so the first matching category wins.
KIND_CATEGORIES = [
    ("browser", {"WebBrowser"}),
    ("terminal", {"TerminalEmulator"}),
    ("filemanager", {"FileManager"}),
    ("editor", {"TextEditor", "IDE", "Development"}),
    ("media", {"AudioVideo", "Player", "AudioVideoEditing", "Recorder"}),
    ("game", {"Game"}),
    ("office", {"Office"}),
    ("utility", {"Utility"}),
]


def _desktop_dirs(extra: list[str] | None = None) -> list[Path]:
    dirs = list(DESKTOP_DIRS)
    if extra:
        dirs = [Path(p) for p in extra] + dirs
    return dirs


def parse_desktop_file(path: Path) -> dict | None:
    """Parse the ``[Desktop Entry]`` group of a .desktop file.

    Returns a dict of bare keys (locale suffixes like ``Name[de]`` ignored),
    or ``None`` if there is no usable Desktop Entry section.
    """
    entry: dict[str, str] = {}
    in_section = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line == "[Desktop Entry]"
            continue
        if not in_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if "[" in key:  # localized / action key -> skip
            continue
        # keep the first occurrence of duplicate bare keys
        entry.setdefault(key, value.strip())

    if not entry:
        return None
    return entry


def clean_exec(exec_line: str) -> tuple[list[str], bool, bool]:
    """Tokenize an Exec line and strip field codes.

    Returns ``(argv, accepts_urls, accepts_files)``. ``%%`` becomes a literal
    ``%`` in the token it appeared in.
    """
    accepts_urls = any(code in exec_line for code in ("%u", "%U"))
    accepts_files = any(code in exec_line for code in ("%f", "%F"))
    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        tokens = exec_line.split()

    argv: list[str] = []
    for tok in tokens:
        # Flathub file-forwarding markers.
        if tok in ("@@", "@@u", "@@f"):
            continue
        if tok in FIELD_CODES:
            continue
        tok = tok.replace("%%", "%").strip()
        if tok:
            argv.append(tok)
    return argv, accepts_urls, accepts_files


def _first_bare(entry: dict, key: str) -> str:
    return entry.get(key, "").strip()


def derive_app_ids(entry: dict, argv: list[str], desktop_id: str) -> list[str]:
    """Best-effort compositor app_id candidates (niri app_id / WM class)."""
    ids: list[str] = []
    wm = _first_bare(entry, "StartupWMClass")
    if wm:
        ids.append(wm)
        if wm.lower() != wm:
            ids.append(wm.lower())
    flatpak = _first_bare(entry, "X-Flatpak")
    if flatpak:
        ids.append(flatpak)

    base = ""
    if argv:
        i = 0
        if Path(argv[0]).name == "env":  # skip env VAR=VAL ...
            i = 1
            while i < len(argv) and "=" in argv[i] and not argv[i].startswith("-"):
                i += 1
        if i < len(argv):
            if Path(argv[i]).name == "flatpak" and "run" in argv[i:]:
                # flatpak run ... <app-id>
                j = i + 2
                while j < len(argv) and argv[j].startswith("-"):
                    j += 1
                if j < len(argv):
                    base = argv[j]
            else:
                base = Path(argv[i]).name
    if base:
        ids.append(base)
        if base.lower() != base:
            ids.append(base.lower())
    ids.append(desktop_id)

    seen: set[str] = set()
    out: list[str] = []
    for x in ids:
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def infer_kind(categories: list[str]) -> str:
    cats = {c for c in categories if c}
    for kind, wanted in KIND_CATEGORIES:
        if cats & wanted:
            return kind
    return "other"


def is_helper(desktop_id: str) -> bool:
    low = desktop_id.lower()
    if desktop_id in HELPER_IDS or low in HELPER_IDS:
        return True
    if any(s in low for s in HELPER_SUBSTRINGS):
        return True
    if any(low.startswith(p) for p in HELPER_PREFIXES):
        return True
    return False


def collect(dirs: list[Path]) -> dict[str, dict]:
    """Scan dirs (highest precedence first) into an id -> catalog-entry map."""
    catalog: dict[str, dict] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            desktop_id = path.name[: -len(".desktop")]
            if desktop_id in catalog:
                continue  # higher-precedence dir already provided this id
            entry = parse_desktop_file(path)
            if entry is None:
                continue
            if _first_bare(entry, "Type") not in ("", "Application"):
                continue
            if _first_bare(entry, "NoDisplay").lower() == "true":
                continue
            if _first_bare(entry, "Hidden").lower() == "true":
                continue
            exec_raw = _first_bare(entry, "Exec")
            if not exec_raw:
                continue
            argv, accepts_urls, accepts_files = clean_exec(exec_raw)
            if not argv:
                continue

            categories = [c for c in _first_bare(entry, "Categories").split(";") if c]
            keywords = [k.strip() for k in _first_bare(entry, "Keywords").split(";") if k.strip()]
            mime_types = [m for m in _first_bare(entry, "MimeType").split(";") if m]
            name = _first_bare(entry, "Name") or desktop_id

            catalog[desktop_id] = {
                "name": name,
                "generic": _first_bare(entry, "GenericName"),
                "comment": _first_bare(entry, "Comment"),
                "exec": argv,
                "exec_raw": exec_raw,
                "accepts_urls": accepts_urls,
                "accepts_files": accepts_files,
                "icon": _first_bare(entry, "Icon"),
                "terminal": _first_bare(entry, "Terminal").lower() == "true",
                "categories": categories,
                "keywords": keywords,
                "mime_types": mime_types,
                "wm_class": _first_bare(entry, "StartupWMClass"),
                "kind": infer_kind(categories),
                "helper": is_helper(desktop_id),
            }
    return catalog


def build_generated(catalog: dict[str, dict]) -> dict:
    """Build the bulk ``generated.yaml`` payload (every visible entry)."""
    profiles: dict[str, dict] = {}
    reserved = _cli_agent_names()
    for desktop_id in sorted(catalog):
        app = catalog[desktop_id]
        name = app["name"]
        aliases = [name.lower()]
        first = name.split()[0].lower() if name.split() else ""
        if first and first != name.lower():
            aliases.append(first)
        for kw in app["keywords"][:6]:
            kw = kw.strip().lower()
            # Do not let a desktop-entry keyword shadow a CLI-agent name.
            if kw and kw not in aliases and kw not in reserved:
                aliases.append(kw)
        profiles[desktop_id] = {
            "id": desktop_id,
            "name": name,
            "aliases": aliases,
            "launch": app["exec"],
            "terminal": app["terminal"],
            "new_window": None,
            "search_url": None,
            "shortcuts": {},
            "app_ids": derive_app_ids(
                {"StartupWMClass": app.get("wm_class", ""), "X-Flatpak": ""},
                app["exec"],
                desktop_id,
            ),
            "mime_types": app["mime_types"],
            "kind": app["kind"],
        }
    return {"profiles": profiles}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="apps.json output path")
    ap.add_argument(
        "--generated",
        type=Path,
        default=DEFAULT_PROFILES_DIR,
        help="generated.yaml output path",
    )
    ap.add_argument(
        "--desktop-dir",
        action="append",
        default=None,
        help="extra .desktop dir (repeatable), scanned with highest precedence",
    )
    ap.add_argument("--dry-run", action="store_true", help="do not write files")
    args = ap.parse_args(argv)

    catalog = collect(_desktop_dirs(args.desktop_dir))
    generated = build_generated(catalog)

    helpers = sum(1 for a in catalog.values() if a["helper"])
    by_kind: dict[str, int] = {}
    for a in catalog.values():
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1

    if not args.dry_run:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if yaml is None:
            print("PyYAML not available: refusing to write generated.yaml", file=sys.stderr)
            return 1
        args.generated.parent.mkdir(parents=True, exist_ok=True)
        args.generated.write_text(
            yaml.safe_dump(generated, sort_keys=False, allow_unicode=True, width=1000),
            encoding="utf-8",
        )

    print(f"apps enumerated: {len(catalog)}  (helpers marked: {helpers})")
    for kind in sorted(by_kind):
        print(f"  {kind:<12} {by_kind[kind]}")
    if not args.dry_run:
        print(f"wrote {args.out}")
        print(f"wrote {args.generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
