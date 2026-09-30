"""App profiles: curated per-app rules merged with the generated catalog.

Every installed GUI app gets a profile: hand-written YAML in ``profiles/`` wins
over the bulk ``generated.yaml`` fallback produced by ``scripts/gen_app_catalog.py``.
Shortcuts that a profile does not declare are inherited from the per-kind
defaults in ``_defaults.yaml``.

Public contract (see DESIGN.md)::

    load() -> dict[str, AppProfile]
    resolve(name, profiles) -> AppProfile | None
    merge_profiles(generated, overrides) -> dict
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or (Path.home() / fallback))


# Your own profiles and edits (the settings app writes here). They win over the
# curated profiles shipped in PROFILES_DIR.
USER_PROFILES_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "utter" / "profiles"
# Catalogue of the apps installed on *this* machine (scripts/gen_app_catalog.py).
GENERATED_PATH = _xdg("XDG_DATA_HOME", ".local/share") / "utter" / "generated.yaml"

# Files that are not per-app profiles.
_RESERVED = {"_defaults.yaml", "generated.yaml"}


@dataclass
class AppProfile:
    """One launchable/actionable application."""

    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    launch: list[str] | str = field(default_factory=list)
    terminal: bool = False
    new_window: Optional[list[str] | str] = None
    search_url: Optional[str] = None  # contains "{q}"
    shortcuts: dict[str, str] = field(default_factory=dict)
    app_ids: list[str] = field(default_factory=list)
    mime_types: list[str] = field(default_factory=list)
    kind: str = "other"


# Fields accepted when constructing an AppProfile from a YAML mapping.
_FIELDS = set(AppProfile.__dataclass_fields__)


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _merge_entry(base: dict, override: dict) -> dict:
    """Field-level merge of two raw profile mappings (override wins)."""
    out = dict(base)
    for key, value in override.items():
        if value is None:
            continue
        if key == "aliases":
            # A curated profile declares its own aliases; do not inherit the
            # noisy keyword-derived aliases from the generated entry.
            aliases: list[str] = []
            for alias in _as_list(value):
                if alias and alias not in aliases:
                    aliases.append(alias)
            out["aliases"] = aliases
        elif key == "shortcuts":
            merged_sc = dict(out.get("shortcuts") or {})
            merged_sc.update(value or {})
            out["shortcuts"] = merged_sc
        else:
            out[key] = value
    return out


def merge_profiles(generated: dict, overrides: dict) -> dict:
    """Merge ``overrides`` onto ``generated``, keyed by profile id.

    Both inputs are mappings of ``id -> profile dict``. A curated override
    replaces individual fields (aliases are unioned, shortcuts are merged).
    """
    merged: dict[str, dict] = {pid: dict(prof) for pid, prof in generated.items()}
    for pid, prof in overrides.items():
        base = merged.get(pid)
        merged[pid] = _merge_entry(base, prof) if base else dict(prof)
    return merged


def _collect_overrides(profiles_dir: Path) -> dict[str, dict]:
    overrides: dict[str, dict] = {}
    for path in sorted(profiles_dir.glob("*.yaml")):
        if path.name in _RESERVED:
            continue
        data = _read_yaml(path)
        if not data:
            continue
        entries = data["profiles"] if isinstance(data.get("profiles"), dict) else (
            {str(data["id"]): data} if "id" in data else {})
        for pid, entry in entries.items():
            # Several files may describe one app (a full profile plus an edit
            # saved by the settings app): merge them instead of replacing.
            overrides[pid] = _merge_entry(overrides[pid], entry) if pid in overrides else dict(entry)
    return overrides


def _apply_defaults(entry: dict, kind: str, defaults: dict) -> dict:
    out = dict(entry)
    kind_defaults = defaults.get(kind) or defaults.get("other") or {}
    merged_sc = dict(kind_defaults.get("shortcuts") or {})
    merged_sc.update(out.get("shortcuts") or {})
    out["shortcuts"] = merged_sc
    if not out.get("search_url") and kind_defaults.get("search_url"):
        out["search_url"] = kind_defaults["search_url"]
    return out


def _to_profile(entry: dict) -> AppProfile:
    kwargs = {k: v for k, v in entry.items() if k in _FIELDS}
    kwargs["launch"] = kwargs.get("launch") or []
    return AppProfile(**kwargs)


def load(
    profiles_dir: str | Path | None = None,
    *,
    user_dir: str | Path | None = None,
    generated_path: str | Path | None = None,
) -> dict[str, AppProfile]:
    """Load all profiles: installed-app catalogue < curated < your own.

    Keyed by profile id. Your profiles (``USER_PROFILES_DIR``) come first so a
    spoken name resolves to them; generic ``generic-*`` fallbacks go last.
    Passing ``profiles_dir`` loads only that directory (tests).
    """
    directory = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    if profiles_dir:
        user = Path(user_dir) if user_dir else None
        gen = Path(generated_path) if generated_path else directory / "generated.yaml"
    else:
        user = Path(user_dir) if user_dir else USER_PROFILES_DIR
        gen = Path(generated_path) if generated_path else GENERATED_PATH

    defaults = _read_yaml(directory / "_defaults.yaml").get("defaults", {}) or {}
    generated = _read_yaml(gen).get("profiles", {}) or {}
    overrides = _collect_overrides(directory)
    mine = _collect_overrides(user) if user and user.is_dir() else {}
    for pid, prof in mine.items():
        overrides[pid] = _merge_entry(overrides[pid], prof) if pid in overrides else dict(prof)
    # Yours first, then curated.
    overrides = {**{k: overrides[k] for k in mine}, **{k: v for k, v in overrides.items() if k not in mine}}

    merged = merge_profiles(generated, overrides)

    # Order curated profiles ahead of generated-only ones so resolve() prefers a
    # hand-written profile for a spoken name; generic-* fallbacks go last.
    override_ids = set(overrides)
    ordered = [k for k in overrides if k in merged and not k.startswith("generic-")]
    ordered += [k for k in merged if k not in override_ids]
    ordered += [k for k in overrides if k in merged and k.startswith("generic-")]

    result: dict[str, AppProfile] = {}
    for pid in ordered:
        entry = merged[pid]
        kind = str(entry.get("kind") or "other")
        entry = _apply_defaults(entry, kind, defaults)
        result[pid] = _to_profile(entry)
    return result


def resolve(name: str, profiles: dict[str, AppProfile]) -> Optional[AppProfile]:
    """Case-insensitive lookup by id, name, alias, then token subset."""
    query = (name or "").strip().lower()
    if not query:
        return None

    for profile in profiles.values():
        if profile.id.lower() == query:
            return profile
    for profile in profiles.values():
        if profile.name.lower() == query:
            return profile
    for profile in profiles.values():
        if any(alias.lower() == query for alias in profile.aliases):
            return profile

    # Loose fallback: every word of the query appears in the profile name.
    query_tokens = set(query.split())
    if query_tokens:
        for profile in profiles.values():
            name_tokens = set(profile.name.lower().split())
            if query_tokens <= name_tokens:
                return profile
    return None
