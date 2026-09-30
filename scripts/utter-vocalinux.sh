#!/bin/bash
# Launch Vocalinux with the utter screen-action bridge installed.
#
# Utterances that begin with "computer" or "utter" are routed to utter
# (which may click/type/act on screen); every other utterance is dictated
# normally. This replaces the stock vocalinux launcher in XDG autostart so the
# bridge lives inside the single vocalinux process.
#
# To revert: restore the backup of ~/.config/autostart/vocalinux.desktop.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VOCALINUX_VENV:-${HOME}/.local/share/vocalinux/venv}"

export PYTHONNOUSERSITE=1
export GI_TYPELIB_PATH=/usr/lib/girepository-1.0
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"

# utter profiles need PyYAML; install once into the vocalinux venv if absent.
if ! "$VENV/bin/python" -c "import yaml" 2>/dev/null; then
    uv pip install --python "$VENV/bin/python" pyyaml >/dev/null 2>&1 || true
fi

# --- native lib paths for pywhispercpp (same logic as the stock wrapper) ---
PYWHISPERCPP_LIBRARY_PATH=""
PY_SITE_PATHS=$("$VENV/bin/python" - <<'PY' 2>/dev/null
import sysconfig
paths = []
for key in ("platlib", "purelib"):
    path = sysconfig.get_paths().get(key)
    if path and path not in paths:
        paths.append(path)
print(" ".join(paths))
PY
)
for PY_SITE in $PY_SITE_PATHS; do
    for PY_LIB_DIR in "$PY_SITE/pywhispercpp.libs" "$PY_SITE/pywhispercpp/.libs" "$PY_SITE/pywhispercpp/lib"; do
        if [ -d "$PY_LIB_DIR" ]; then
            PYWHISPERCPP_LIBRARY_PATH="${PYWHISPERCPP_LIBRARY_PATH:+$PYWHISPERCPP_LIBRARY_PATH:}$PY_LIB_DIR"
        fi
    done
done
if [ -n "$PYWHISPERCPP_LIBRARY_PATH" ]; then
    export LD_LIBRARY_PATH="$PYWHISPERCPP_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

EXEC_CMD="$VENV/bin/python -m utter.daemon --bridge --config $REPO/config.default.toml"
if grep -q "^input:.*\b$(whoami)\b" /etc/group 2>/dev/null && ! groups | grep -q "\binput\b" && command -v sg &>/dev/null; then
    exec sg input -c "$EXEC_CMD"
else
    exec $EXEC_CMD
fi
