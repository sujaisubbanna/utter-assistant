#!/usr/bin/env bash
# Install the utter Noctalia plugin (OPTIONAL widget package).
#
# Copies this package (widgets/noctalia) into the Noctalia user plugin directory
# (dir name must match the plugin id suffix: utter), substitutes the checkout
# path into the poller, lints it, and optionally enables it and adds the bar widget.
#
#   widgets/noctalia/install.sh              # install + lint only
#   widgets/noctalia/install.sh --yes        # + enable + add bar widget
#   widgets/noctalia/install.sh --yes --no-widget
#   widgets/noctalia/install.sh --link       # symlink instead of copy
#
# IMPORTANT: Noctalia treats every sibling directory in the plugins dir as an
# overriding copy of a plugin. This script therefore backs up any previous
# install OUTSIDE the plugins directory and never leaves a *.bak* dir behind.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
SRC="$SCRIPT_DIR"

PLUGIN_ID="utter/utter"
WIDGET_NAME="utter"
WIDGET_TYPE="utter/utter:utter"

PLUGINS_DIR="${NOCTALIA_PLUGINS_DIR:-$HOME/.local/share/noctalia/plugins}"
DEST="$PLUGINS_DIR/$WIDGET_NAME"
BACKUP_DIR="${NOCTALIA_PLUGIN_BACKUPS:-$HOME/.local/state/noctalia/plugin-backups}"
SETTINGS="${NOCTALIA_SETTINGS:-$HOME/.local/state/noctalia/settings.toml}"

YES=0
LINK=0
ADD_WIDGET=1

usage() {
	cat <<'EOF'
Usage: install.sh [--yes] [--link] [--no-widget]

  --yes, -y     Enable the plugin and add its widget to the default bar.
  --link        Symlink the plugin directory instead of copying it.
  --no-widget   With --yes, do not add the widget to the bar.
  -h, --help    Show this help.
EOF
}

for arg in "$@"; do
	case "$arg" in
		--yes|-y) YES=1 ;;
		--link) LINK=1 ;;
		--no-widget) ADD_WIDGET=0 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
	esac
done

[[ -f "$SRC/plugin.toml" ]] || { echo "source plugin not found: $SRC" >&2; exit 1; }

mkdir -p "$PLUGINS_DIR"

# Any *.bak* sibling is treated by Noctalia as an overriding copy: refuse.
if compgen -G "$PLUGINS_DIR/$WIDGET_NAME.bak*" >/dev/null 2>&1; then
	echo "refusing: backup copy inside the plugins dir ($PLUGINS_DIR/$WIDGET_NAME.bak*)" >&2
	echo "remove it, then re-run (this is the sibling-copy bug)." >&2
	exit 1
fi

# Move a previous install out of the plugins dir (never a sibling *.bak*).
if [[ -e "$DEST" || -L "$DEST" ]]; then
	mkdir -p "$BACKUP_DIR"
	stamp="$(date +%Y%m%d-%H%M%S)"
	if [[ -L "$DEST" ]]; then
		rm -f "$DEST"
	else
		mv "$DEST" "$BACKUP_DIR/$WIDGET_NAME-$stamp"
		echo "backed up previous install -> $BACKUP_DIR/$WIDGET_NAME-$stamp"
	fi
fi

if [[ "$LINK" == 1 ]]; then
	ln -s "$SRC" "$DEST"
	echo "linked $DEST -> $SRC"
	echo "note: link mode relies on the repo_root plugin setting or UTTER_REPO."
else
	cp -r "$SRC" "$DEST"
	if grep -q '__UTTER_REPO__' "$DEST/poller.luau" 2>/dev/null; then
		python3 - "$DEST/poller.luau" "$REPO_ROOT" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(path.read_text().replace("__UTTER_REPO__", sys.argv[2]))
PY
	fi
	echo "installed -> $DEST"
fi

# Re-check: never leave an overriding sibling behind.
if compgen -G "$PLUGINS_DIR/$WIDGET_NAME.bak*" >/dev/null 2>&1; then
	echo "error: a *.bak* copy is present in $PLUGINS_DIR" >&2
	exit 1
fi

if command -v noctalia >/dev/null 2>&1; then
	echo "==> noctalia plugins lint $DEST"
	if ! noctalia plugins lint "$DEST"; then
		echo "lint failed; not enabling." >&2
		exit 1
	fi
else
	echo "warning: noctalia not found on PATH; skipping lint" >&2
fi

if [[ "$YES" == 1 ]]; then
	if command -v noctalia >/dev/null 2>&1; then
		echo "==> enabling $PLUGIN_ID"
		noctalia msg plugins enable "$PLUGIN_ID"
	fi

	if [[ "$ADD_WIDGET" == 1 ]]; then
		if [[ -f "$SETTINGS" ]] && command -v python3 >/dev/null 2>&1; then
			echo "==> adding widget '$WIDGET_NAME' to the default bar"
			python3 - "$SETTINGS" "$WIDGET_NAME" "$WIDGET_TYPE" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
name, widget_type = sys.argv[2], sys.argv[3]
text = path.read_text()

# 1. Ensure a [widget.<name>] definition exists.
if widget_type not in text:
    if not text.endswith("\n"):
        text += "\n"
    text += f'\n[widget.{name}]\ntype = "{widget_type}"\n'

# 2. Insert the widget name into the [bar.default] start list (idempotent).
lines = text.splitlines()
in_bar = False
done = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("[") and not stripped.startswith("[["):
        in_bar = stripped == "[bar.default]"
    if in_bar and not done and re.match(r"^\s*start\s*=\s*\[", line):
        if f'"{name}"' not in line:
            lines[i] = line.rstrip()[:-1] + f', "{name}"]'
        done = True

path.write_text("\n".join(lines) + "\n")
print("settings updated" if (done or widget_type in text) else
      "warning: [bar.default] start list not found; add the widget manually")
PY
		else
			echo "warning: no settings.toml or python3; add the widget manually" >&2
		fi
	fi

	if command -v noctalia >/dev/null 2>&1; then
		echo "==> noctalia msg config-reload"
		noctalia msg config-reload || true
	fi
fi

echo "done."
