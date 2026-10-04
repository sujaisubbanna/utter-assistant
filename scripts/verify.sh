#!/usr/bin/env bash
# Verify the utter runner + plugin protocol (M0 + M1).
#
#   scripts/verify.sh
#
# Runs: agent CLI/voice/platform tests, runner unit + socket e2e, guardrails
# (stdlib-only runner, provenance, installer contract), the independent
# conformance suite, M3 (real assistant, dry-run), M5 (assistant CLI) and the
# measurement spike. Hermetic: each run uses a throwaway XDG_RUNTIME_DIR
# so it never collides with a live `utter-runner` service socket.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${UTTER_PY:-$REPO/.venv-agent/bin/python}"
cd "$REPO"

# Accept a bare command (e.g. UTTER_PY=python3) as well as an explicit path.
if [[ "$PY" != */* ]]; then
    PY="$(command -v "$PY" || true)"
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
    echo "python not found at ${UTTER_PY:-<default>} (set UTTER_PY)" >&2
    exit 2
fi

# Isolate the runtime dir so tests never clash with the running service.
RUNTMP="$(mktemp -d)"
cleanup() { rm -rf "$RUNTMP"; }
trap cleanup EXIT
mkdir -p "$RUNTMP/utter"
export XDG_RUNTIME_DIR="$RUNTMP"

rc=0

echo "== agent CLI contract =="
"$PY" tests/test_cli.py || rc=1

echo "== router: rules golden order =="
"$PY" tests/router/test_rules_order.py || rc=1
"$PY" tests/router/test_app_target_rules.py || rc=1
"$PY" tests/router/test_app_enabled.py || rc=1

echo "== router: eval corpus =="
"$PY" tests/eval/run_eval.py || rc=1

echo "== executor: app-targeted focus round-trip =="
"$PY" tests/executor/test_app_target.py || rc=1

echo "== voice: push-to-talk rescan leak =="
"$PY" tests/voice/test_hotkey_rescan.py || rc=1
"$PY" tests/voice/test_clipboard_nontext.py || rc=1
"$PY" tests/voice/test_osd_modes.py || rc=1
"$PY" tests/voice/test_osd_loading.py || rc=1
"$PY" tests/voice/test_daemon_cli.py || rc=1
"$PY" tests/voice/test_daemon_osd.py || rc=1
"$PY" tests/voice/test_linux_dictation.py || rc=1
"$PY" tests/voice/test_dictation_target.py || rc=1
"$PY" tests/voice/test_sleep_mode.py || rc=1
"$PY" tests/voice/test_idle_sleep.py || rc=1
"$PY" tests/voice/test_locale.py || rc=1
"$PY" tests/voice/test_stt_language.py || rc=1
"$PY" tests/voice/test_tts_linux.py || rc=1
"$PY" tests/actions/test_open_url_browser.py || rc=1
"$PY" tests/actions/test_profile_layers.py || rc=1

echo "== platform: macOS detection + backend selection (runs on Linux) =="
"$PY" tests/platform/test_macos_detection.py || rc=1
"$PY" tests/platform/test_macos_runtime.py || rc=1
"$PY" tests/platform/test_macos_wiring.py || rc=1
"$PY" tests/platform/test_macos_background_input.py || rc=1

echo "== platform: compositor detection + KWin backend (no live Plasma needed) =="
"$PY" tests/platform/test_compositor_detection.py || rc=1

echo "== runner unit =="
"$PY" -m runner._selftest || rc=1

echo
echo "== guardrails: runner stdlib, provenance, installer contract =="
"$PY" tests/test_runner_stdlib.py || rc=1
"$PY" tests/test_provenance_invariant.py || rc=1
"$PY" tests/test_app_target_policy.py || rc=1
"$PY" tests/test_gui_profile_contract.py || rc=1
"$PY" tests/test_gui_unwired_config.py || rc=1
"$PY" tests/test_installer_contract.py || rc=1

echo
echo "== runner e2e (socket) =="
"$PY" -m runner._selftest --e2e || rc=1

echo
echo "== plugin: example_quicknote (demo action plugin) =="
"$PY" tests/plugins/test_quicknote.py || rc=1

echo
echo "== conformance suite =="
"$PY" tests/conformance/run.py || rc=1

echo
echo "== M3 (real assistant as a plugin; dry-run only) =="
if [ -f tests/m3/test_decision_head_probe.py ]; then
    # Hermetic probe classification: foreign/offline head skips, ready asserts.
    "$PY" tests/m3/test_decision_head_probe.py || rc=1
fi
if [ -f tests/m3/verify_m3.py ]; then
    # The optional real desktop action is opt-in: pass --real-action or set
    # UTTER_M3_REAL_ACTION=1. By default this never touches the desktop.
    "$PY" tests/m3/verify_m3.py || rc=1
fi

echo
echo "== M5 (assistant CLI: model store, doctor, install-state) =="
if [ -f tests/m5/verify_m5.py ]; then
    "$PY" tests/m5/verify_m5.py || rc=1
fi
if [ -f tests/m5/test_install_state.py ]; then
    "$PY" tests/m5/test_install_state.py || rc=1
fi

echo
echo "== measurement spike =="
"$PY" scripts/m0_spike.py || rc=1

echo
echo "== report.json =="
if [ -f tests/conformance/report.json ]; then
    "$PY" - <<'PY'
import json, pathlib
p = pathlib.Path("tests/conformance/report.json")
try:
    d = json.loads(p.read_text())
except Exception as e:
    print("could not parse report.json:", e); raise SystemExit(0)
for k in ("latency", "backpressure_e2e", "reliable_flow", "invoke",
          "validate_plugin", "handles_fd", "default_deny", "crash_restart"):
    if k in d:
        print(f"{k}: {json.dumps(d[k])[:200]}")
PY
fi

echo
if [ "$rc" -eq 0 ]; then
    echo "VERIFY: OK"
else
    echo "VERIFY: FAILURES (rc=$rc)" >&2
fi
exit "$rc"
