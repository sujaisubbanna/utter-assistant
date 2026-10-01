#!/usr/bin/env bash
# build-macos-runtime.sh — assemble the Python runtime bundled inside utter.app.
#
#   scripts/build-macos-runtime.sh [--version <ver>] [--out <dir>] [--python 3.12]
#
# Produces (default out dir: gui-tauri/src-tauri/resources/):
#   runtime.tar.gz      runtime/python/  relocatable CPython (python-build-standalone)
#                                        with numpy, sounddevice, PyObjC, pywhispercpp…
#                       runtime/core/    the assistant (utter/, runner/, assistant/, plugins/…)
#                       runtime/VERSION
#   runtime.version     the same version string, read by the app to detect updates
#
# Tauri picks both up through gui-tauri/src-tauri/tauri.macos.conf.json, and the
# app unpacks the tarball into ~/Library/Application Support/utter/runtime on
# first launch (gui-tauri/src-tauri/src/macos_setup.rs). Run this on macOS with
# the same architecture you are bundling for (CI: macos-14 / arm64).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPO/gui-tauri/src-tauri/resources"
VERSION=""
PY_SERIES="3.12"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="${2:-}"; shift 2 ;;
        --out)     OUT_DIR="${2:-}"; shift 2 ;;
        --python)  PY_SERIES="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done

[[ "$(uname -s)" == "Darwin" ]] || { echo "build-macos-runtime.sh must run on macOS" >&2; exit 2; }
case "$(uname -m)" in
    arm64) PBS_ARCH="aarch64-apple-darwin" ;;
    x86_64) PBS_ARCH="x86_64-apple-darwin" ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 2 ;;
esac

if [[ -z "$VERSION" ]]; then
    VERSION="$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || echo 0.0.0)"
fi
VERSION="${VERSION#v}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd -- "$OUT_DIR" && pwd)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
RT="$STAGE/runtime"
mkdir -p "$RT"

# --------------------------------------------------------------------------- #
# 1. relocatable CPython (astral-sh/python-build-standalone, install_only_stripped)
# --------------------------------------------------------------------------- #
echo "resolving python-build-standalone ($PY_SERIES, $PBS_ARCH)"
API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
AUTH=()
[[ -n "${GITHUB_TOKEN:-}" ]] && AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")
PBS_URL="$(curl -fsSL "${AUTH[@]}" -H "Accept: application/vnd.github+json" "$API" \
    | python3 -c "
import json, sys
series, arch = sys.argv[1], sys.argv[2]
for a in json.load(sys.stdin)['assets']:
    n = a['name']
    if n.startswith(f'cpython-{series}.') and n.endswith(f'-{arch}-install_only_stripped.tar.gz'):
        print(a['browser_download_url']); break
" "$PY_SERIES" "$PBS_ARCH")"
[[ -n "$PBS_URL" ]] || { echo "no python-build-standalone asset for $PY_SERIES/$PBS_ARCH" >&2; exit 1; }
echo "downloading $PBS_URL"
curl -fsSL "$PBS_URL" -o "$STAGE/python.tar.gz"
tar -xzf "$STAGE/python.tar.gz" -C "$RT"          # -> runtime/python/
PY="$RT/python/bin/python3"
"$PY" --version

# --------------------------------------------------------------------------- #
# 2. the assistant core
# --------------------------------------------------------------------------- #
CORE="$RT/core"
mkdir -p "$CORE"
for rel in protocol runner assistant plugins utter macos config.default.toml config.m3.toml \
           pyproject.toml README.md LICENSE; do
    if [[ -e "$REPO/$rel" ]]; then
        cp -a "$REPO/$rel" "$CORE/$rel"
    else
        echo "  skip (absent): $rel"
    fi
done
find "$CORE" -type d \( -name '__pycache__' -o -name '.venv*' -o -name 'node_modules' -o -name 'target' \) \
    -prune -exec rm -rf {} + 2>/dev/null || true

# --------------------------------------------------------------------------- #
# 3. python packages (wheels only: no compiler needed on the user's Mac)
# --------------------------------------------------------------------------- #
"$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$PY" -m pip install --no-cache-dir --upgrade pip >/dev/null
echo "installing python packages"
"$PY" -m pip install --no-cache-dir \
    "numpy>=1.26" "sounddevice>=0.4" "requests>=2.31" "PyYAML>=6.0" \
    "pyobjc-framework-Cocoa>=10.0" "pyobjc-framework-Quartz>=10.0" \
    "pyobjc-framework-Speech>=10.0" "pyobjc-framework-AVFoundation>=10.0" \
    "pyobjc-framework-ApplicationServices>=10.0"
# whisper.cpp fallback: best effort (Apple Speech works without it).
if ! "$PY" -m pip install --no-cache-dir --only-binary=:all: "pywhispercpp>=1.2"; then
    echo "::warning::pywhispercpp wheel unavailable; whisper.cpp fallback not bundled"
fi

# trim what nobody needs at runtime
rm -rf "$RT/python/lib/python${PY_SERIES}/test" "$RT/python/lib/python${PY_SERIES}/idlelib"
find "$RT/python" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
# make sure the runtime still imports what the daemon needs
"$PY" -c "import numpy, sounddevice, AppKit, Quartz, Speech, AVFoundation, ApplicationServices; print('runtime imports ok')"
( cd "$CORE" && "$PY" -m assistant --help >/dev/null && echo "assistant --help ok" )

printf '%s\n' "$VERSION" > "$RT/VERSION"

# --------------------------------------------------------------------------- #
# 4. pack
# --------------------------------------------------------------------------- #
echo "packing runtime.tar.gz"
COPYFILE_DISABLE=1 tar -czf "$OUT_DIR/runtime.tar.gz" -C "$STAGE" runtime
printf '%s\n' "$VERSION" > "$OUT_DIR/runtime.version"
ls -lh "$OUT_DIR/runtime.tar.gz"
echo "runtime version: $VERSION"
