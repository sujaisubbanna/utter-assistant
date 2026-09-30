//! Per-app action profiles, read through the assistant's own loader.
//!
//! The GUI never parses YAML itself: it runs the repo's interpreter with a
//! fixed script (arguments as a list, never a shell string) so the list shows
//! exactly what `utter.router.profiles.load()` sees. Edits are written as
//! *user overrides* to `~/.config/utter/profiles/<id>.yaml`; the curated
//! files in the repo are never modified.

/// argv: user_dir. Prints `{profiles:[…], user_dir, loader_reads_user}`.
pub const LIST_SCRIPT: &str = r##"
import json, sys
from dataclasses import asdict
from pathlib import Path
from utter.router import profiles as P

user_dir = Path(sys.argv[1])
base = P.load()
curated = set(P._collect_overrides(P.PROFILES_DIR))
user = P._collect_overrides(user_dir) if user_dir.is_dir() else {}
out = []
for pid, prof in base.items():
    d = asdict(prof)
    u = user.get(pid)
    eff = P._merge_entry(d, u) if u else d
    out.append({
        "id": pid,
        "name": eff.get("name") or pid,
        "kind": eff.get("kind") or "other",
        "aliases": eff.get("aliases") or [],
        "launch": eff.get("launch") or [],
        "search_url": eff.get("search_url"),
        "shortcuts": eff.get("shortcuts") or {},
        "builtin_shortcuts": d.get("shortcuts") or {},
        "app_ids": eff.get("app_ids") or [],
        "curated": pid in curated,
        "user": u or None,
        # a full profile you keep yourself (vs. a small edit saved by the settings app)
        "own": bool(u) and pid not in curated and ("launch" in u or "name" in u),
    })
json.dump({
    "profiles": out,
    "user_dir": str(user_dir),
    "loader_reads_user": hasattr(P, "USER_PROFILES_DIR"),
}, sys.stdout)
"##;

/// argv: user_dir, id, json. Validates and writes one override file.
pub const SAVE_SCRIPT: &str = r##"
import json, os, re, sys, tempfile
from pathlib import Path
import yaml

user_dir, pid, payload = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
if not pid or len(pid) > 120 or "/" in pid or pid.startswith(".") or any(ord(c) < 32 for c in pid):
    sys.exit("invalid profile id")
out = {"id": pid}
aliases = payload.get("aliases")
if aliases is not None:
    out["aliases"] = [str(a).strip()[:60] for a in aliases if str(a).strip()][:32]
shortcuts = payload.get("shortcuts") or {}
clean = {}
for name, chord in shortcuts.items():
    name, chord = str(name).strip(), str(chord).strip()
    if not re.fullmatch(r"[a-z0-9_]{1,40}", name):
        sys.exit(f"invalid action name: {name}")
    if not re.fullmatch(r"[A-Za-z0-9_+\-]{1,40}", chord):
        sys.exit(f"invalid key combination for {name}: {chord}")
    clean[name] = chord
if clean:
    out["shortcuts"] = clean
url = payload.get("search_url")
if url:
    url = str(url).strip()
    if not re.match(r"https?://", url) or "{q}" not in url or len(url) > 500:
        sys.exit("search address must start with http(s):// and contain {q}")
    out["search_url"] = url
user_dir.mkdir(parents=True, exist_ok=True)
target = user_dir / (re.sub(r"[^A-Za-z0-9._-]", "_", pid) + ".yaml")
fd, tmp = tempfile.mkstemp(dir=user_dir, suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("# Written by the utter settings app. Overrides the built-in profile.\n")
    yaml.safe_dump(out, fh, sort_keys=False, allow_unicode=True)
os.replace(tmp, target)
print(json.dumps({"ok": True, "path": str(target)}))
"##;

/// Accept only a plain profile id (no path separators or control chars).
pub fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 120
        && !id.contains('/')
        && !id.starts_with('.')
        && !id.chars().any(|c| c.is_control())
}

/// File name used for a profile's override (mirrors SAVE_SCRIPT).
pub fn override_file(id: &str) -> String {
    let safe: String = id
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || "._-".contains(c) { c } else { '_' })
        .collect();
    format!("{safe}.yaml")
}
