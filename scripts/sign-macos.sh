#!/usr/bin/env bash
# sign-macos.sh — re-sign the macOS app bundle and/or the bundled Python runtime
# with a STABLE ad-hoc code identity so TCC (Privacy) grants persist across rebuilds.
#
#   scripts/sign-macos.sh app     <path/to/utter.app>
#   scripts/sign-macos.sh runtime <runtime-dir>
#
# Why: Tauri/linker ad-hoc signatures get a designated requirement of
# `cdhash H"…"`, which changes on every build. TCC keys privacy grants to the DR,
# so every rebuild silently invalidates Microphone / SpeechRecognition /
# ListenEvent / Accessibility / ScreenCapture grants. Re-signing with an explicit
# identifier-based DR fixes that (no certificate needed):
#
#   codesign --force --sign - --identifier org.utter.settings \
#     --requirements '=designated => identifier "org.utter.settings"' \
#     --timestamp=none <path>
#
# Both modes are idempotent and per-file non-fatal: a file that cannot be signed
# is reported and skipped, the run continues. On non-macOS hosts (Linux CI) or
# when `codesign` is absent this prints a warning and exits 0 so builds never break.
#
# See docs/MACOS.md ("Stable ad-hoc identity (TCC)").
set -uo pipefail

IDENT="org.utter.settings"
REQ='=designated => identifier "org.utter.settings"'

CODE_SIGN=(codesign --force --sign - --identifier "$IDENT" --requirements "$REQ" --timestamp=none)

OK=0
FAIL=0

say()  { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

usage() {
    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
}

# --- helpers ---------------------------------------------------------------- #

is_macho_file() {
    # `file` on a directory answers "directory"; only consider regular files.
    [[ -f "$1" ]] || return 1
    file -b "$1" 2>/dev/null | grep -q 'Mach-O'
}

# Run the exact stable-identity codesign invocation on one path. Never aborts.
sign_path() {
    local target="$1" out
    if out=$("${CODE_SIGN[@]}" "$target" 2>&1); then
        OK=$((OK + 1))
        say "  signed: $target"
    else
        FAIL=$((FAIL + 1))
        printf '  FAILED: %s\n' "$target" >&2
        [[ -n "$out" ]] && printf '    %s\n' "$out" >&2
    fi
}

# Recursively sign every Mach-O under a tree, deepest-first.
#   1. dylibs / shared objects
#   2. executables (filtered to Mach-O via `file`)
#   3. *.bundle (may be a directory — codesign handles it)
# A path may be both 1 and 2; those names are excluded from pass 2.
sign_tree() {
    local root="$1" f b
    [[ -d "$root" ]] || return 0

    say "scanning: $root"
    while IFS= read -r -d '' f; do
        is_macho_file "$f" && sign_path "$f"
    done < <(find "$root" -depth -type f \( -name '*.dylib' -o -name '*.so' \) -print0 2>/dev/null)

    while IFS= read -r -d '' f; do
        is_macho_file "$f" && sign_path "$f"
    done < <(find "$root" -depth -type f -perm -u+x \
                ! -name '*.dylib' ! -name '*.so' -print0 2>/dev/null)

    while IFS= read -r -d '' b; do
        if [[ -d "$b" ]]; then
            sign_path "$b"
        elif is_macho_file "$b"; then
            sign_path "$b"
        fi
    done < <(find "$root" -depth -name '*.bundle' -print0 2>/dev/null)
}

print_dr() {
    local target="$1"
    say ""
    say "designated requirement for: $target"
    codesign -d -r- "$target" 2>&1 || true
}

# A runtime dir is not itself a signable bundle, so verify a representative
# Mach-O inside it (the interpreter is the one TCC actually cares about).
print_runtime_dr() {
    local root="$1" probe=""
    for cand in "$root/python/bin/python3.12" "$root/python/bin/python3"; do
        if is_macho_file "$cand"; then probe="$cand"; break; fi
    done
    if [[ -z "$probe" ]]; then
        probe="$(find "$root" -type f -perm -u+x -print 2>/dev/null | while IFS= read -r f; do
            is_macho_file "$f" && { printf '%s\n' "$f"; break; }
        done)"
    fi
    if [[ -n "$probe" ]]; then
        print_dr "$probe"
    else
        say ""
        say "no Mach-O binaries found under: $root"
    fi
}

summary() {
    say ""
    say "signed OK: $OK   failed: $FAIL"
    if (( FAIL > 0 )); then
        warn "$FAIL path(s) could not be signed — see the log above."
        warn "TCC grants may not persist until those are fixed."
    fi
    # Signing must never fail a build (matches the fail-safe policy elsewhere).
    exit 0
}

# --- main ------------------------------------------------------------------- #

mode="${1:-}"
target="${2:-}"

case "$mode" in
    -h|--help|help|"")
        usage
        exit 0
        ;;
    app)
        [[ -n "$target" ]] || { usage >&2; exit 2; }
        [[ -d "$target" ]] || { warn "app bundle not found: $target"; exit 2; }
        ;;
    runtime)
        [[ -n "$target" ]] || { usage >&2; exit 2; }
        [[ -d "$target" ]] || { warn "runtime dir not found: $target"; exit 2; }
        ;;
    *)
        warn "unknown mode: $mode"
        usage >&2
        exit 2
        ;;
esac

if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "not macOS — skipping code signing of $target"
    exit 0
fi
if ! command -v codesign >/dev/null 2>&1; then
    warn "codesign not found — skipping code signing of $target"
    exit 0
fi

say "signing '$target' as ad-hoc identity '$IDENT'"

case "$mode" in
    runtime)
        sign_tree "$target"
        print_runtime_dr "$target"
        ;;
    app)
        # Strip quarantine/finder metadata first so codesign doesn't choke.
        xattr -cr "$target" 2>/dev/null || true
        # Sign nested Mach-O inside-out before sealing the bundle itself; the
        # bundle's main executable (Contents/MacOS/utter) is covered by the
        # final app-level signature, but Frameworks are not.
        [[ -d "$target/Contents/Frameworks" ]] && sign_tree "$target/Contents/Frameworks"
        [[ -d "$target/Contents/MacOS" ]] && sign_tree "$target/Contents/MacOS"
        sign_path "$target"
        print_dr "$target"
        ;;
esac

summary
