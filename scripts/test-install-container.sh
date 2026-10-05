#!/usr/bin/env bash
# test-install-container.sh — verify the Linux installer's Python-environment
# behaviour on clean distros, inside throwaway Docker containers.
#
# Usage:
#   scripts/test-install-container.sh [IMAGE ...]
#   scripts/test-install-container.sh --skip-deps [IMAGE ...]
#   scripts/test-install-container.sh -h
#
# Defaults to ubuntu:24.04. For each image it runs a `docker run --rm`
# container with this repo mounted read-only at /src, installs the distro
# prerequisites (unless --skip-deps), copies the repo to a writable path, runs
# the local installer non-interactively, and asserts the installed Python
# environment. Prints one PASS/FAIL line per image and exits non-zero if any
# image failed.
#
# Nothing is written on the host outside Docker. The same file is mounted into
# the container and re-executed there; INSTALL_TEST_INSIDE=1 selects that path.
set -uo pipefail

usage() {
    cat <<'USAGE'
Usage: scripts/test-install-container.sh [IMAGE ...]

Run the Linux installer inside throwaway Docker containers and assert the
resulting Python environment. Default image: ubuntu:24.04.

Options:
  --skip-deps   assume the distro prerequisites are already present in the image
  -h, --help    show this help

Environment:
  UTTER_VERSION, UTTER_BASE_URL, GITHUB_TOKEN, GH_TOKEN
                forwarded to the installer (pin a release / avoid API limits)

Asserts (per image):
  1. ~/.local/share/utter/.venv-agent/pyvenv.cfg has
     include-system-site-packages = true
  2. that venv can import gi/Atspi and yaml, requests, numpy, evdev,
     sounddevice, pywhispercpp
  3. the installed `assistant doctor --json` runs and prints valid JSON
  4. both user units are installed (utter-runner.service + utter.service)
     with the @REPO@ placeholder substituted
USAGE
}

# --------------------------------------------------------------------------- #
# in-container path
# --------------------------------------------------------------------------- #
container_pkg_manager() {
    local c
    for c in apt-get dnf pacman zypper; do
        command -v "$c" >/dev/null 2>&1 || continue
        case "$c" in
            apt-get) echo apt ;;
            *)       echo "$c" ;;
        esac
        return 0
    done
    return 1
}

install_deps() {
    local mgr="$1"
    echo "  installing distro prerequisites via $mgr"
    case "$mgr" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq --no-install-recommends \
                curl tar ca-certificates python3 python3-venv python3-gi \
                gir1.2-atspi-2.0 at-spi2-core libportaudio2 \
                build-essential linux-libc-dev cmake python3-dev
            ;;
        dnf)
            dnf install -y --setopt=install_weak_deps=False \
                curl tar ca-certificates python3 python3-pip python3-gobject \
                at-spi2-core portaudio gcc gcc-c++ make kernel-headers cmake \
                python3-devel
            ;;
        pacman)
            pacman -Sy --noconfirm --needed \
                curl tar ca-certificates python python-pip python-gobject \
                at-spi2-core portaudio base-devel cmake
            ;;
        zypper)
            zypper --non-interactive install \
                curl tar ca-certificates python3 python3-pip python3-gobject \
                at-spi2-core portaudio gcc gcc-c++ make linux-glibc-devel \
                cmake python3-devel
            ;;
        *)
            echo "  unknown package manager: $mgr" >&2
            return 1
            ;;
    esac
}

run_in_container() {
    local skip_deps="${INSTALL_TEST_SKIP_DEPS:-1}"
    local failures=0
    local pretty="unknown"
    # shellcheck disable=SC1091
    [[ -r /etc/os-release ]] && . /etc/os-release && pretty="${PRETTY_NAME:-$pretty}"
    echo "container: $pretty"

    # --- 1. distro prerequisites ------------------------------------------ #
    if [[ "$skip_deps" == "1" ]]; then
        echo "  --skip-deps: not installing distro prerequisites"
    else
        local mgr
        if ! mgr="$(container_pkg_manager)"; then
            echo "FAIL: no supported package manager (apt/dnf/pacman/zypper)" >&2
            return 1
        fi
        if ! install_deps "$mgr"; then
            echo "FAIL: could not install distro prerequisites" >&2
            return 1
        fi
    fi

    # --- 2. copy the repo to a writable path + run the installer ---------- #
    rm -rf /work
    mkdir -p /work
    if ! tar -C /src \
            --exclude='./.git' \
            --exclude='./.venv' \
            --exclude='./.venv-agent' \
            --exclude='./models' \
            --exclude='./gui-tauri' \
            --exclude='./website' \
            --exclude='./dist' \
            --exclude='./.pytest_cache' \
            -cf - . | tar -C /work -xf -; then
        echo "FAIL: could not copy the repo into the container" >&2
        return 1
    fi

    export HOME=/root
    export XDG_DATA_HOME="$HOME/.local/share"
    export XDG_CONFIG_HOME="$HOME/.config"
    export XDG_STATE_HOME="$HOME/.local/state"
    export PATH="$HOME/.local/bin:$PATH"

    echo "  running /work/install.sh --yes --skip models,gui"
    local install_rc=0
    ( cd /work && bash /work/install.sh --yes --skip models,gui ) || install_rc=$?
    if (( install_rc != 0 )); then
        echo "  note: the installer exited $install_rc (assertions still run)"
    fi

    local venv="$XDG_DATA_HOME/utter/.venv-agent"
    local share="$XDG_DATA_HOME/utter"

    # --- 3. assertions ---------------------------------------------------- #
    if [[ -f "$venv/pyvenv.cfg" ]] \
        && grep -qiE '^include-system-site-packages[[:space:]]*=[[:space:]]*true' "$venv/pyvenv.cfg"; then
        echo "  ok: pyvenv.cfg uses include-system-site-packages = true"
    else
        failures=$((failures + 1))
        echo "FAIL: $venv/pyvenv.cfg is missing or has system site packages disabled" >&2
        [[ -f "$venv/pyvenv.cfg" ]] && sed 's/^/        /' "$venv/pyvenv.cfg" >&2
    fi

    local imrc=0 imout=""
    imout="$("$venv/bin/python" - 2>&1 <<'PY'
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
import yaml, requests, numpy, evdev, sounddevice, pywhispercpp
print("imports ok")
PY
)" || imrc=$?
    if (( imrc == 0 )); then
        echo "  ok: venv imports gi/Atspi + yaml, requests, numpy, evdev, sounddevice, pywhispercpp"
    else
        failures=$((failures + 1))
        echo "FAIL: venv cannot import the assistant/voice dependencies:" >&2
        printf '%s\n' "$imout" | sed 's/^/        /' >&2
    fi

    local doc_rc=0 doc_out=""
    if [[ -x "$HOME/.local/bin/assistant" ]]; then
        doc_out="$("$HOME/.local/bin/assistant" doctor --json 2>&1)" || doc_rc=$?
    elif [[ -d "$share/assistant" ]]; then
        doc_out="$(cd "$share" && PYTHONPATH="$share" "$venv/bin/python" -m assistant doctor --json 2>&1)" || doc_rc=$?
    else
        doc_rc=127
        doc_out="assistant CLI not installed"
    fi
    if (( doc_rc == 0 )) && printf '%s' "$doc_out" | python3 -c 'import json,sys; json.load(sys.stdin)' >/dev/null 2>&1; then
        echo "  ok: assistant doctor --json runs and returns valid JSON"
    else
        failures=$((failures + 1))
        echo "FAIL: assistant doctor --json did not return valid JSON (rc=$doc_rc):" >&2
        printf '%s\n' "$doc_out" | sed 's/^/        /' >&2
    fi

    local unit u unin_ok=1
    for u in utter-runner.service utter.service; do
        local f="$XDG_CONFIG_HOME/systemd/user/$u"
        if [[ -f "$f" ]] && ! grep -q '@REPO@' "$f"; then
            echo "  ok: $u installed and substituted"
            continue
        fi
        if [[ -f "$XDG_STATE_HOME/utter/install.json" ]] \
            && grep -q "$u" "$XDG_STATE_HOME/utter/install.json"; then
            echo "  ok: $u recorded in install.json"
            continue
        fi
        unin_ok=0
        failures=$((failures + 1))
        if [[ -f "$f" ]]; then
            echo "FAIL: $f still contains the @REPO@ placeholder" >&2
        else
            echo "FAIL: $u was not installed and is not in install.json" >&2
        fi
    done
    (( unin_ok )) && echo "  ok: both systemd user units present"

    if (( failures > 0 )); then
        echo "RESULT: FAIL ($failures assertion(s) failed)"
        return 1
    fi
    echo "RESULT: PASS"
    return 0
}

# --------------------------------------------------------------------------- #
# host path
# --------------------------------------------------------------------------- #
if [[ "${INSTALL_TEST_INSIDE:-0}" == "1" ]]; then
    run_in_container
    exit $?
fi

set -euo pipefail

SELF="${BASH_SOURCE[0]}"
SELF="$(cd "$(dirname "$SELF")" && pwd)/$(basename "$SELF")"

LABEL="utter-install-test"
cleanup() {
    docker ps -q --filter "label=$LABEL" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

SKIP_DEPS=0
IMAGES=()
while (( $# > 0 )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --skip-deps) SKIP_DEPS=1 ;;
        -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
        *) IMAGES+=("$1") ;;
    esac
    shift
done
(( ${#IMAGES[@]} > 0 )) || IMAGES=(ubuntu:24.04)

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }

REPO="${INSTALL_TEST_REPO:-}"
if [[ -z "$REPO" ]]; then
    REPO="$(git -C "$(dirname "$SELF")" rev-parse --show-toplevel 2>/dev/null || true)"
fi
[[ -n "$REPO" ]] || REPO="$(cd "$(dirname "$SELF")/.." && pwd)"
[[ -d "$REPO/.git" || -f "$REPO/install.sh" ]] || { echo "cannot locate the repo root (set INSTALL_TEST_REPO)" >&2; exit 2; }

echo "repo:   $REPO"
echo "images: ${IMAGES[*]}"
[[ "$SKIP_DEPS" == "1" ]] && echo "deps:   preinstalled (--skip-deps)"
echo

failed=0
for image in "${IMAGES[@]}"; do
    echo "=== $image ==="
    rc=0
    docker run --rm --label "$LABEL" \
        -e INSTALL_TEST_INSIDE=1 \
        -e INSTALL_TEST_SKIP_DEPS="$SKIP_DEPS" \
        -e HOME=/root -e TERM=dumb -e NO_COLOR=1 \
        -e UTTER_VERSION -e UTTER_BASE_URL -e GITHUB_TOKEN -e GH_TOKEN \
        -v "$REPO":/src:ro \
        -v "$SELF":/test-install-container.sh:ro \
        "$image" bash /test-install-container.sh || rc=$?
    if (( rc == 0 )); then
        echo "PASS: $image"
    else
        echo "FAIL: $image (exit $rc)"
        failed=1
    fi
    echo
done

exit "$failed"
