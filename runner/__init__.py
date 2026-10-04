"""utter reference runner (M0 spike).

A small Python host that implements the frozen framing + handshake, supervises
plugins, exposes a unix-socket client API and enforces the trust/policy layer.

This is a de-risking spike, not the final Rust port. stdlib only (3.12+).
"""

from pathlib import Path

__all__ = ["__version__"]


def _resolve_version() -> str:
    """Resolve from ``pyproject.toml`` in a checkout/tarball, else distribution metadata.

    Single-sourced with ``assistant.__version__``: ``doctor`` compares the
    installer's recorded release version against this value
    (docs/COMPATIBILITY.md §6), so it must never be a hardcoded constant.
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