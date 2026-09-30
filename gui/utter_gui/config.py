"""Configuration access for the GUI.

Reads ``~/.config/utter/config.toml`` with :mod:`tomllib`. Writes are
*line-based* edits: only the target key's line changes, so comments, ordering
and unknown keys survive untouched.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def repo_root() -> Path:
    """The utter checkout this GUI lives in (…/gui/utter_gui/config.py)."""
    return Path(__file__).resolve().parents[2]


CONFIG_DIR = _xdg_config_home() / "utter"
CONFIG_PATH = CONFIG_DIR / "config.toml"
GUI_STATE_PATH = CONFIG_DIR / "gui.json"
DEFAULT_CONFIG = repo_root() / "config.default.toml"

_SET_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.\-]+)(?P<ws>\s*)=\s*(?P<rest>.*)$"
)


# --------------------------------------------------------------------------- #
# value serialisation (the subset utter config needs)
# --------------------------------------------------------------------------- #
def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if value is None:
        return '""'
    raise TypeError(f"cannot serialise {type(value).__name__} to TOML")


def _split_comment(rest: str) -> tuple[str, str]:
    """Split ``value  # comment`` -> ("value", "  # comment")."""
    in_str = False
    escape = False
    for i, ch in enumerate(rest):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
        elif ch == "#" and not in_str:
            return rest[:i].rstrip(), rest[i:]
    return rest.strip(), ""


def _set_key(text: str, section: str, key: str, value: Any) -> str:
    val = toml_value(value)
    lines = text.splitlines()
    header = f"[{section}]"

    sec_start: Optional[int] = None
    for i, line in enumerate(lines):
        if line.strip().split("#", 1)[0].strip() == header:
            sec_start = i
            break

    if sec_start is None:  # append a brand new section
        out = list(lines)
        if out and out[-1].strip():
            out.append("")
        out.append(header)
        out.append(f"{key} = {val}")
        return "\n".join(out) + "\n"

    sec_end = len(lines)
    for i in range(sec_start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            sec_end = i
            break

    for i in range(sec_start + 1, sec_end):
        m = _SET_RE.match(lines[i])
        if m and m.group("key") == key:
            _old, comment = _split_comment(m.group("rest"))
            suffix = ("  " + comment.lstrip()) if comment else ""
            lines[i] = f"{m.group('indent')}{key} = {val}{suffix}"
            return "\n".join(lines) + "\n"

    # insert at the end of the section, before trailing blank lines
    insert_at = sec_end
    while insert_at - 1 > sec_start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"{key} = {val}")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# the file object
# --------------------------------------------------------------------------- #
class TomlConfig:
    """Read/write access to a single TOML file, comment-preserving on write."""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)

    # -- lifecycle ------------------------------------------------------- #
    def ensure(self) -> None:
        """Create the user config from config.default.toml when missing."""
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULT_CONFIG.exists():
            shutil.copyfile(DEFAULT_CONFIG, self.path)
        else:
            self.path.write_text(
                "# utter configuration (created by utter-gui)\n",
                encoding="utf-8",
            )

    def read_text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    # -- reading --------------------------------------------------------- #
    def data(self) -> dict:
        try:
            return tomllib.loads(self.read_text())
        except (tomllib.TOMLDecodeError, ValueError):
            return {}

    def section(self, name: str) -> dict:
        value = self.data().get(name, {})
        return value if isinstance(value, dict) else {}

    def get(self, section: str, key: str, default: Any = None) -> Any:
        value = self.section(section).get(key, default)
        return default if value is None else value

    def get_list(self, section: str, key: str) -> list:
        value = self.section(section).get(key)
        return list(value) if isinstance(value, list) else []

    # -- writing --------------------------------------------------------- #
    def set(self, section: str, key: str, value: Any) -> None:
        self.ensure()
        text = self.read_text()
        if not text.endswith("\n") and text:
            text += "\n"
        _atomic_write(self.path, _set_key(text, section, key, value))

    def set_many(self, section: str, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(section, key, value)

    def add_to_list(self, section: str, key: str, item: Any, present: bool) -> None:
        items = self.get_list(section, key)
        if present and item not in items:
            items.append(item)
        elif not present and item in items:
            items = [x for x in items if x != item]
        self.set(section, key, items)


# --------------------------------------------------------------------------- #
# small GUI state (window size + last page) — not part of the assistant config
# --------------------------------------------------------------------------- #
def load_gui_state() -> dict:
    try:
        return json.loads(GUI_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_gui_state(state: dict) -> None:
    try:
        _atomic_write(GUI_STATE_PATH, json.dumps(state, indent=2) + "\n")
    except OSError:
        pass
