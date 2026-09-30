#!/usr/bin/env bash
# install-zen-bidi-desktop.sh - add --remote-debugging-port=9222 to the Zen
# desktop entry so the WebDriver BiDi remote agent starts with the browser.
#
# Writes ~/.local/share/applications/zen-browser.desktop (a user override that
# shadows the system entry). Reversible: just delete that file.
#
# Usage: scripts/install-zen-bidi-desktop.sh [--uninstall]
set -euo pipefail

PORT="${ZEN_BIDI_PORT:-9222}"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DEST="$DEST_DIR/zen-browser.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$DEST"
    echo "removed $DEST" >&2
    exit 0
fi

# Locate the installed system desktop file.
SRC=""
for d in /usr/share/applications $HOME/.local/share/applications; do
    if [[ -f "$d/zen.desktop" ]]; then SRC="$d/zen.desktop"; break; fi
    if [[ -f "$d/zen-browser.desktop" && "$d/zen-browser.desktop" != "$DEST" ]]; then
        SRC="$d/zen-browser.desktop"; break
    fi
done
if [[ -z "$SRC" ]] && command -v pacman >/dev/null 2>&1; then
    SRC=$(pacman -Ql zen-browser-bin 2>/dev/null \
        | awk '/\/applications\/.*\.desktop$/{print $2; exit}')
fi
if [[ -z "$SRC" || ! -f "$SRC" ]]; then
    echo "error: could not find the installed Zen .desktop file" >&2
    exit 1
fi

# Identify the binary from the main Exec line (fall back to the known path).
BIN=$(sed -n '0,/^Exec=/{s/^Exec=\([^ ]*\).*/\1/p}' "$SRC")
BIN="${BIN:-/opt/zen-browser-bin/zen-bin}"

mkdir -p "$DEST_DIR"

# Rewrite only the FIRST Exec= line (the main [Desktop Entry]); quote the
# binary for paths containing spaces.
sed "0,/^Exec=/s|^Exec=.*|Exec=\"$BIN\" --remote-debugging-port=$PORT %u|" \
    "$SRC" > "$DEST"

if ! grep -q -- "--remote-debugging-port=$PORT" "$DEST"; then
    echo "error: failed to inject --remote-debugging-port=$PORT" >&2
    rm -f "$DEST"
    exit 1
fi

echo "installed $DEST (Exec: $BIN --remote-debugging-port=$PORT)" >&2
echo "undo with: $0 --uninstall" >&2
