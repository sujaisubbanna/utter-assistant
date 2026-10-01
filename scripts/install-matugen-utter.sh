#!/usr/bin/env bash
# install-matugen-utter.sh — idempotently wire utter into matugen.
#
# Copies the utter matugen template into ~/.config/matugen/templates/ and
# adds a [templates.utter] block to ~/.config/matugen/config.toml. matugen
# then renders the palette to ~/.local/share/utter/colors.css, which the
# Tauri settings app reads.
#
#   scripts/install-matugen-utter.sh                 # install (no clobber)
#   scripts/install-matugen-utter.sh --force         # overwrite template + block
#   scripts/install-matugen-utter.sh --dry-run       # show what would happen
#   scripts/install-matugen-utter.sh --wall ~/wall.png --mode dark
#
# Safe by design: the config.toml is backed up once to config.toml.bak-utter
# before the first edit, only the [templates.utter] block is touched, and no
# other content is ever removed.

set -euo pipefail

usage() {
	cat <<'EOF'
Usage: install-matugen-utter.sh [--force] [--dry-run] [--wall PATH] [--mode MODE]

  --force        Overwrite an existing template / [templates.utter] block.
  --dry-run      Print actions without changing anything.
  --wall PATH    Run `matugen image PATH -m MODE` once after installing.
  --mode MODE    matugen mode for --wall (light|dark|smart). Default: dark.
  -h, --help     Show this help.
EOF
}

FORCE=0
DRY_RUN=0
WALL=""
MODE="dark"

while [[ $# -gt 0 ]]; do
	case "$1" in
		--force) FORCE=1; shift ;;
		--dry-run) DRY_RUN=1; shift ;;
		--wall) WALL="${2:-}"; shift 2 ;;
		--mode) MODE="${2:-}"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
	esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_SRC="$REPO_ROOT/gui-tauri/theme/utter-colors.css.tmpl"

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/matugen"
TEMPLATE_DIR="$CONFIG_DIR/templates"
TEMPLATE_DST="$TEMPLATE_DIR/utter-colors.css"
CONFIG_FILE="$CONFIG_DIR/config.toml"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/utter"
OUTPUT_CSS="$DATA_DIR/colors.css"
BACKUP="$CONFIG_FILE.bak-utter"
KEY="templates.utter"

say() { printf '%s\n' "$*"; }
note() { printf '  would: %s\n' "$*"; }

# Run a command, or print it under --dry-run.
doit() {
	if [[ "$DRY_RUN" == 1 ]]; then
		note "$*"
	else
		"$@"
	fi
}

[[ -f "$TEMPLATE_SRC" ]] || {
	echo "template not found: $TEMPLATE_SRC" >&2
	exit 1
}

say "utter + matugen installer"
if [[ "$DRY_RUN" == 1 ]]; then
	say "  dry-run: no files will be changed"
fi
say "  template  : $TEMPLATE_SRC"
say "  matugen   : $CONFIG_FILE"
say "  palette   : $OUTPUT_CSS"
say ""

# 1. directories -------------------------------------------------------------
doit mkdir -p "$TEMPLATE_DIR"
doit mkdir -p "$DATA_DIR"

# 2. template ----------------------------------------------------------------
if [[ -f "$TEMPLATE_DST" && "$FORCE" != 1 ]]; then
	say "template already present: $TEMPLATE_DST (use --force to overwrite)"
else
	say "installing template -> $TEMPLATE_DST"
	doit cp "$TEMPLATE_SRC" "$TEMPLATE_DST"
fi

# 3. config.toml [templates.utter] ---------------------------------------
has_key=0
if [[ -f "$CONFIG_FILE" ]] && grep -qE "^[[:space:]]*\[${KEY//./\\.}\][[:space:]]*$" "$CONFIG_FILE"; then
	has_key=1
fi

if [[ "$has_key" == 1 && "$FORCE" != 1 ]]; then
	say "config block [$KEY] already present: $CONFIG_FILE (use --force to replace)"
else
	if [[ "$has_key" == 1 ]]; then
		say "replacing config block [$KEY] in $CONFIG_FILE"
	else
		say "adding config block [$KEY] to $CONFIG_FILE"
	fi

	if [[ "$DRY_RUN" == 1 ]]; then
		if [[ ! -f "$CONFIG_FILE" ]]; then
			note "create $CONFIG_FILE with a [config] section + [$KEY]"
		else
			note "back up $CONFIG_FILE -> $BACKUP (once)"
			note "strip existing [$KEY] block and append the utter block"
		fi
	else
		# Back up once, before the first edit ever touches the file.
		if [[ -f "$CONFIG_FILE" && ! -f "$BACKUP" ]]; then
			cp "$CONFIG_FILE" "$BACKUP"
			say "backed up -> $BACKUP"
		fi

		tmp="$(mktemp "${CONFIG_FILE}.XXXXXX")"
		trap 'rm -f "$tmp"' EXIT

		if [[ -f "$CONFIG_FILE" ]]; then
			# Drop only the [templates.utter] section (until the next [header]).
			awk -v key="$KEY" '
				/^# utter: matugen/ { next }
				{
					if ($0 ~ /^[[:space:]]*\[/) {
						line = $0
						gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
						if (line == "[" key "]") { skip = 1; next }
						skip = 0
					}
					if (skip) next
					lines[++n] = $0
					if ($0 != "") last = n
				}
				END { for (i = 1; i <= last; i++) print lines[i] }
			' "$CONFIG_FILE" >"$tmp"
		else
			printf '[config]\nversion_check = false\n' >"$tmp"
		fi

		{
			printf '\n# utter: matugen -> GTK4/libadwaita + Tauri palette\n'
			printf '[%s]\n' "$KEY"
			printf 'input_path = "%s"\n' "$TEMPLATE_DST"
			printf 'output_path = "%s"\n' "$OUTPUT_CSS"
		} >>"$tmp"

		cp "$tmp" "$CONFIG_FILE"
		rm -f "$tmp"
		trap - EXIT
	fi
fi

# 4. optionally re-render ----------------------------------------------------
say ""
if [[ -n "$WALL" ]]; then
	if command -v matugen >/dev/null 2>&1; then
		say "rendering palette from $WALL (mode: $MODE)"
		doit matugen image "$WALL" -m "$MODE"
	else
		say "matugen not found on PATH; skipping render" >&2
	fi
elif command -v matugen >/dev/null 2>&1; then
	say "matugen is installed — re-run your normal matugen to generate the palette:"
	say "    matugen image <wallpaper> -m $MODE"
else
	say "matugen not found on PATH — install it, then re-run matugen."
fi

say ""
say "next steps:"
say "  1. run matugen as usual (or pass --wall <path> to this script)"
say "  2. confirm the palette exists: $OUTPUT_CSS"
say "  3. open utter Settings — it re-themes live when the palette changes"
say "done."
