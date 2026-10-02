"""Spoken-language resolution, shared by STT and TTS.

The spoken language is deliberately **independent of the settings-app UI
language** (the i18n dictionaries are a separate axis): ``[stt] language`` /
``[tts] language`` describe what the user *speaks and hears*, while the UI
language only translates the settings window.

``"auto"`` (the default) resolves from the process environment in the usual
POSIX precedence order (``LC_ALL`` → ``LC_MESSAGES`` → ``LANG``). When nothing
resolvable is set, :func:`resolve` returns ``None``: STT then lets Whisper
auto-detect rather than guessing English, and TTS uses the engine's default
voice.

Examples::

    en_GB.UTF-8  -> en-GB
    de_DE        -> de-DE
    pt_BR.utf8   -> pt-BR
    C / POSIX    -> None

Pure module: :func:`resolve` accepts an injected ``env`` mapping so tests never
touch the real environment.
"""
from __future__ import annotations

import os
import re
from typing import Mapping, Optional

#: Sentinel meaning "detect from the system locale, else let the engine decide".
AUTO = "auto"

_ENV_ORDER = ("LC_ALL", "LC_MESSAGES", "LANG")

# language [ _script ] [ _region ] with 2-3 letter language, 4 letter script
# and a 2-letter or 3-digit region. Separators are normalised to "-".
_LOCALE_RE = re.compile(
    r"^(?P<lang>[A-Za-z]{2,3})"
    r"(?:[_-](?P<script>[A-Za-z]{4}))?"
    r"(?:[_-](?P<region>[A-Za-z]{2}|[0-9]{3}))?$"
)


def normalize_locale(raw: Optional[str]) -> Optional[str]:
    """Normalise a POSIX locale or BCP-47 tag to ``lang[-Script][-REGION]``.

    Strips the ``.encoding`` and ``@modifier`` parts. Returns ``None`` for the
    C/POSIX locale, empty input or anything that does not look like a locale.
    """
    if not raw:
        return None
    value = str(raw).split("@", 1)[0].split(".", 1)[0].strip()
    if not value or value.upper() in ("C", "POSIX"):
        return None
    match = _LOCALE_RE.match(value)
    if match is None:
        return None
    lang = match.group("lang").lower()
    parts = [lang]
    script = match.group("script")
    if script:
        parts.append(script.title())
    region = match.group("region")
    if region:
        parts.append(region.upper() if region.isalpha() else region)
    return "-".join(parts)


def language_from_env(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Resolve the system locale to a BCP-47-ish code, or ``None`` if unknown."""
    source: Mapping[str, str] = os.environ if env is None else env
    for key in _ENV_ORDER:
        code = normalize_locale(source.get(key))
        if code:
            return code
    return None


def resolve(value: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Resolve a configured language value to a code, or ``None`` when unknown.

    ``"auto"``/empty delegates to :func:`language_from_env`; anything else is
    normalised (:data:`AUTO` is never returned here). An explicit but invalid
    value resolves to ``None`` so callers fall back to engine auto-detection
    instead of guessing English.
    """
    text = (value or "").strip()
    if not text or text.lower() == AUTO:
        return language_from_env(env)
    return normalize_locale(text)


def base_language(code: Optional[str]) -> Optional[str]:
    """Primary subtag for engines that want a bare code (``en-GB`` → ``en``)."""
    if not code:
        return None
    head = str(code).split("-", 1)[0].strip().lower()
    return head or None


def is_english(code: Optional[str]) -> bool:
    """True when ``code`` resolves to English (``en`` base subtag)."""
    return base_language(code) == "en"


__all__ = [
    "AUTO",
    "base_language",
    "is_english",
    "language_from_env",
    "normalize_locale",
    "resolve",
]