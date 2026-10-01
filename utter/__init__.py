"""utter - context-aware local voice -> desktop action sidecar.

Tiered execution (cheapest wins):
    T0 APP      app/context rules, no perception
    T1 A11Y     accessibility tree
    T2 KEYBOARD app shortcuts
    T3 VISION   UI-TARS-2B screenshot grounding (fallback only)
"""

from pathlib import Path


def _resolve_version() -> str:
    """Single source of truth: the project version in ``pyproject.toml``.

    A source checkout reads ``pyproject.toml`` directly so the reported version
    can never drift from the release; an installed wheel falls back to its
    distribution metadata.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib

            return str(tomllib.loads(pyproject.read_text())["project"]["version"])
        except Exception:
            pass
    try:
        from importlib.metadata import version

        return version("utter")
    except Exception:
        return "0.0.0+unknown"


__version__ = _resolve_version()
