"""Install state: ``$XDG_STATE_HOME/utter/install.json`` (reversible).

Shape::

    {"files": [], "units": [], "packages": [], "version": "", "protocol": "1.0"}

The installer lane records what it did here; ``doctor`` compares it against the
running runner to report drift (docs/COMPATIBILITY.md §6).
"""
from __future__ import annotations

from typing import Any, Iterable

from . import util

DEFAULT: dict[str, Any] = {
    "files": [],
    "units": [],
    "packages": [],
    "version": "",
    "protocol": "1.0",
}


def load() -> dict[str, Any]:
    data = util.read_json(util.install_json_path(), default=None)
    if not isinstance(data, dict):
        return dict(DEFAULT)
    merged = dict(DEFAULT)
    for key in DEFAULT:
        if key in data:
            merged[key] = data[key]
    return merged


def save(data: dict[str, Any]) -> dict[str, Any]:
    util.atomic_write_json(util.install_json_path(), data)
    return data


def _merge_unique(existing: Any, new: Iterable[str]) -> list:
    out = list(existing or [])
    for item in new or ():
        if item and item not in out:
            out.append(item)
    return out


def parse_csv(values: Iterable[str]) -> list[str]:
    """Flatten repeatable and/or comma-separated CLI values into a unique list."""
    out: list[str] = []
    for value in values or ():
        for part in str(value).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def record(
    *,
    files: Iterable[str] = (),
    units: Iterable[str] = (),
    packages: Iterable[str] = (),
    version: str | None = None,
    protocol: str | None = None,
) -> dict[str, Any]:
    data = load()
    data["files"] = _merge_unique(data.get("files"), files)
    data["units"] = _merge_unique(data.get("units"), units)
    data["packages"] = _merge_unique(data.get("packages"), packages)
    if version is not None:
        data["version"] = version
    if protocol is not None:
        data["protocol"] = protocol
    return save(data)


def show() -> dict[str, Any]:
    return load()
