#!/usr/bin/env bash
# build-core-tarball.sh — package the Python core needed to run the assistant.
#
#   scripts/build-core-tarball.sh [--version <ver>] [--out <dir>]
#
# Produces:
#   dist/utter-core-<ver>.tar.gz
#   dist/sha256sums.txt
#
# The tarball contains the runner, the assistant CLI, the protocol contracts,
# the plugins, the systemd unit + Wayland wrapper, and the docs — everything
# needed for `python -m assistant` and `python -m runner` to work from the
# extracted tree. It deliberately excludes virtualenvs, models, caches, the GUI
# and CI.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"

VERSION=""
OUT_DIR="$REPO/dist"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="${2:-}"; shift 2 ;;
        --out)     OUT_DIR="${2:-}"; shift 2 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done

# Version: explicit flag > git describe > VERSION file > 0.0.0
if [[ -z "$VERSION" ]]; then
    if command -v git >/dev/null 2>&1 && git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
        VERSION="$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || true)"
    fi
fi
if [[ -z "$VERSION" && -f "$REPO/VERSION" ]]; then
    VERSION="$(tr -d '[:space:]' < "$REPO/VERSION")"
fi
VERSION="${VERSION:-0.0.0}"
# Strip a leading 'v' for the filename (keep it in the tarball root name).
VERSION_NUM="${VERSION#v}"

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd -- "$OUT_DIR" && pwd)"
TARBALL="$OUT_DIR/utter-core-${VERSION_NUM}.tar.gz"
STAGE_NAME="utter-core-${VERSION_NUM}"

echo "build-core-tarball: version=$VERSION_NUM out=$OUT_DIR"

# --------------------------------------------------------------------------- #
# stage the tree
# --------------------------------------------------------------------------- #
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$STAGE_NAME"
mkdir -p "$ROOT"

copy_path() {
    # copy_path <relative-path> — copy a file or directory if it exists.
    local rel="$1"
    if [[ -e "$REPO/$rel" ]]; then
        mkdir -p "$ROOT/$(dirname "$rel")"
        cp -a "$REPO/$rel" "$ROOT/$rel"
    else
        echo "  skip (absent): $rel"
    fi
}

echo "staging:"
# Python core
copy_path protocol
copy_path runner
copy_path assistant
copy_path plugins
copy_path utter
# optional UI widget package (installed only when the Noctalia step is chosen)
copy_path widgets
# scripts: verify + python helpers + the Wayland wrapper
mkdir -p "$ROOT/scripts"
for f in "$REPO"/scripts/*.py "$REPO"/scripts/verify.sh "$REPO"/scripts/utter-wayland-ready.sh; do
    [[ -e "$f" ]] || continue
    cp -a "$f" "$ROOT/scripts/"
done
# systemd units + the runner unit from install/
copy_path systemd
mkdir -p "$ROOT/install"
[[ -f "$REPO/install/utter-runner.service" ]] && \
    cp -a "$REPO/install/utter-runner.service" "$ROOT/install/"
# configs + top-level docs
copy_path config.default.toml
copy_path config.m3.toml
copy_path AGENTS.md
copy_path README.md
copy_path LICENSE
copy_path pyproject.toml
copy_path docs

# --------------------------------------------------------------------------- #
# prune excluded content
# --------------------------------------------------------------------------- #
echo "pruning:"
find "$ROOT" -type d \( -name '__pycache__' -o -name '.venv' -o -name '.venv-agent' \
    -o -name 'models' -o -name '.git' -o -name '.github' -o -name 'node_modules' \) \
    -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
# never ship the GUI or CI even if copied transitively
rm -rf "$ROOT/gui" "$ROOT/gui-tauri" "$ROOT/.github" 2>/dev/null || true

# --------------------------------------------------------------------------- #
# deterministic-ish tar (sorted, fixed mtime/owner)
# --------------------------------------------------------------------------- #
echo "packing: $TARBALL"
tar --sort=name \
    --mtime='UTC 2020-01-01' \
    --owner=0 --group=0 --numeric-owner \
    -czf "$TARBALL" -C "$STAGE" "$STAGE_NAME"

# --------------------------------------------------------------------------- #
# sha256sums.txt (core tarball; CI appends the GUI assets)
# --------------------------------------------------------------------------- #
SUMS="$OUT_DIR/sha256sums.txt"
( cd "$OUT_DIR" && sha256sum "$(basename "$TARBALL")" > "$SUMS" )
echo "wrote: $SUMS"

# --------------------------------------------------------------------------- #
# verify: extract + run `python -m assistant --help`
# --------------------------------------------------------------------------- #
PY="${UTTER_PY:-$REPO/.venv-agent/bin/python}"
if [[ ! -x "$PY" ]]; then
    PY="$(command -v python3 || true)"
fi
if [[ -n "$PY" && -x "$PY" ]]; then
    VERIFY_DIR="$(mktemp -d)"
    trap 'rm -rf "$STAGE" "$VERIFY_DIR"' EXIT
    tar -xzf "$TARBALL" -C "$VERIFY_DIR"
    echo "verify: extracted to $VERIFY_DIR/$STAGE_NAME"
    if ( cd "$VERIFY_DIR/$STAGE_NAME" && "$PY" -m assistant --help >/dev/null 2>&1 ); then
        echo "verify: python -m assistant --help OK"
    else
        echo "verify: FAILED to run python -m assistant --help" >&2
        ( cd "$VERIFY_DIR/$STAGE_NAME" && "$PY" -m assistant --help ) || true
        exit 1
    fi
else
    echo "verify: no python interpreter found; skipping --help check" >&2
fi

echo
echo "artifact: $TARBALL"
ls -lh "$TARBALL"
echo "sha256:   $(cut -d' ' -f1 "$SUMS")"
