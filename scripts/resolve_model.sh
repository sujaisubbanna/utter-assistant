#!/usr/bin/env bash
# Model-path resolution for the vLLM serving scripts.
#
# Sourced by scripts/serve_planner.sh and scripts/serve_vision.sh. Requires
# $REPO_ROOT to be set. Order:
#
#   1. the UTTER_*_MODEL_PATH override, verbatim;
#   2. the model store (``assistant models pull``) — but the store keeps files
#      content-addressed (``blobs/sha256-<hex>``), not as a loadable directory,
#      so a store-only hit is reported and we fall through;
#   3. a full local checkout at ``$REPO_ROOT/models/<name>``;
#   4. the Hugging Face repo id, which vLLM downloads as a complete repo.
#
# resolve_model <override> <envvar> <name> <hf_repo_id>
resolve_model() {
    local override="$1" envvar="$2" name="$3" hfid="$4"
    local store="${UTTER_MODELS:-${XDG_DATA_HOME:-$HOME/.local/share}/utter-models}"
    local blob

    if [[ -n "$override" ]]; then
        printf '%s' "$override"
        return 0
    fi

    blob="$(_store_manifest_blob "$store" "$name" 2>/dev/null || true)"
    if [[ -n "$blob" ]]; then
        {
            echo "[resolve_model] note: '$name' is in the model store, but as a single"
            echo "  content-addressed file; vLLM needs the complete repo directory:"
            echo "    $blob"
            echo "  Falling back to a checkout / Hugging Face. Set $envvar or run"
            echo "  scripts/install_inference.sh for a full local copy."
        } >&2
    fi

    if [[ -d "$REPO_ROOT/models/$name" ]]; then
        printf '%s' "$REPO_ROOT/models/$name"
        return 0
    fi

    if [[ -n "$hfid" ]]; then
        printf '%s' "$hfid"
        return 0
    fi

    echo "[resolve_model] error: no model for '$name'." >&2
    echo "  Set $envvar, or place a full checkout at $REPO_ROOT/models/$name." >&2
    return 1
}

# _store_manifest_blob <store_root> <model_name> — first blob path in a manifest
# whose name matches (store manifest name or its directory name).
_store_manifest_blob() {
    local store="$1" name="$2"
    [[ -d "$store/manifests" ]] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    python3 - "$store/manifests" "$name" <<'PY'
import json
import sys
from pathlib import Path

manifests, name = sys.argv[1], sys.argv[2]
for path in sorted(Path(manifests).glob("*/*/*/*.json")):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if str(data.get("name") or "") != name and path.parent.name != name:
        continue
    for entry in data.get("files") or []:
        if entry.get("path"):
            print(entry["path"])
            sys.exit(0)
PY
}
