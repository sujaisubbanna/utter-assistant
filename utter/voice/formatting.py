"""Optional local dictation formatting (post-STT rewrite).

The dictation lane types what you say verbatim by default. When
``[dictation] format = "local"`` it first sends the raw transcript to the
**same local LLM the router already uses** (``[router] llm_base_url`` on Linux,
``[macos.runtime]`` on macOS, resolved by :func:`utter.runtime.resolve_router`)
and types the cleaned-up text instead.

This is a *reformat only* pass: punctuation, capitalisation and filler removal.
It must never change meaning, answer the text or translate it, so the prompt is
strict and the reply is sanity-checked.

Offline-safe by design. Any failure at all — ``requests`` missing, connection
error, timeout, non-200, empty/malformed body, or a wildly long reply — returns
the ORIGINAL transcript. :func:`format_transcript` never raises and never blocks
dictation for longer than its short timeout, so the user's words are never lost.
"""
from __future__ import annotations

import logging

log = logging.getLogger("utter")

# Formatting is on the critical path of a PTT release: keep it short.
_TIMEOUT_S = 5.0
_MIN_MAX_TOKENS = 32
_MAX_MAX_TOKENS = 256
_DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL = "qwen3-4b"

_SYSTEM = (
    "You clean up a dictated transcript. Rewrite the same words in the same "
    "language, adding punctuation and capitalisation and removing filler words "
    "such as \"um\" and \"uh\". Do not answer the text, do not translate, do "
    "not summarise, and do not add or remove meaning. Output only the cleaned "
    "transcript, with no quotes and no commentary."
)


def _enabled(cfg) -> bool:
    """True only for an explicit ``[dictation] format = "local"``.

    Unknown/missing values are treated as ``"off"``.
    """
    value = getattr(getattr(cfg, "dictation", None), "format", "off")
    return str(value or "").strip().lower() == "local"


def format_transcript(text: str, cfg) -> str:
    """Return ``text`` reformatted locally, or the ORIGINAL on any failure.

    Never raises. Runs only when ``cfg.dictation.format == "local"`` and the
    transcript has non-whitespace content.
    """
    original = text or ""
    try:
        if not _enabled(cfg) or not original.strip():
            return original

        from .. import runtime
        # Per-platform endpoint/model: Linux [router], macOS [macos.runtime].
        resolved = runtime.resolve_router(cfg)
        base_url = (getattr(resolved, "llm_base_url", None)
                    or _DEFAULT_BASE_URL).rstrip("/")
        model = getattr(resolved, "llm_model", None) or _DEFAULT_MODEL

        try:
            import requests  # lazy: importing this module must work offline
        except Exception:  # noqa: BLE001 - no requests = no formatting
            return original

        # Bound the reply to roughly the input length: a cleanup never needs to
        # be much longer, and the cap stops a model that starts answering.
        max_tokens = max(_MIN_MAX_TOKENS,
                         min(_MAX_MAX_TOKENS, len(original) // 2 + 16))
        payload = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": original},
            ],
        }
        resp = requests.post(f"{base_url}/chat/completions", json=payload,
                             timeout=_TIMEOUT_S)
        if getattr(resp, "status_code", None) != 200:
            return original
        data = resp.json()
        out = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        out = (out or "").strip()
        if not out:
            return original
        # Defensive: a cleanup may grow a little (punctuation, casing); a much
        # longer reply is the model answering or rambling. Keep the user's words.
        if len(out) > max(len(original) * 3, len(original) + 240):
            log.debug("dictation formatting reply looked implausible; using raw")
            return original
        return out
    except Exception:  # noqa: BLE001 - any failure must fall back to raw text
        log.debug("dictation formatting failed; using raw transcript", exc_info=True)
        return original
