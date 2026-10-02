#!/usr/bin/env bash
# build-macos-app.sh — build the Tauri settings app on macOS and give it a
# stable ad-hoc code identity so TCC (Privacy) grants survive rebuilds.
#
#   scripts/build-macos-app.sh [-- <extra tauri build args>]
#
# Runs `pnpm tauri build` in gui-tauri/ (the repo convention; `tauri.macos.conf.json`
# adds the "app"/"dmg" bundle targets on macOS), then re-signs the produced
# bundle with scripts/sign-macos.sh. Never changes tauri.conf.json's
# signingIdentity: no Developer ID certificate is assumed on this machine.
#
# macOS-only: on other platforms this is a no-op so Linux CI keeps passing.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
GUI_DIR="$REPO/gui-tauri"
APP="$GUI_DIR/src-tauri/target/release/bundle/macos/utter.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "build-macos-app.sh: not macOS — nothing to do" >&2
    exit 0
fi

if ! command -v pnpm >/dev/null 2>&1; then
    echo "build-macos-app.sh: pnpm not found on PATH" >&2
    exit 1
fi

echo "building Tauri app (pnpm tauri build)…"
( cd "$GUI_DIR" && pnpm tauri build "$@" )

if [[ ! -d "$APP" ]]; then
    echo "build-macos-app.sh: expected bundle not found: $APP" >&2
    exit 1
fi

echo "re-signing $APP with the stable TCC identity…"
"$SCRIPT_DIR/sign-macos.sh" app "$APP"

echo "done: $APP"
echo "next steps (see docs/MACOS.md): re-register with lsregister, reset TCC for"
echo "org.utter.settings, reopen utter and grant the prompts again."
