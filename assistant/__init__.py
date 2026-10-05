"""utter assistant CLI (M5): doctor, model store, recommend, install state.

Stdlib only. The installer lane calls these frozen entry points::

    python -m assistant doctor [--json]
    python -m assistant models list|show <name>|pull <source>|rm <name>|prune [--json]
    python -m assistant recommend [--json]
    python -m assistant inference install|status|check [--json]
    python -m assistant status [--json]
    python -m assistant install-state record|show
"""

from pathlib import Path

__all__ = ["__version__"]


def _resolve_version() -> str:
    """Resolve from ``pyproject.toml`` in a checkout, else distribution metadata."""
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
