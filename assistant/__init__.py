"""utter assistant CLI (M5): doctor, model store, recommend, install state.

Stdlib only. The installer lane calls these frozen entry points::

    python -m assistant doctor [--json]
    python -m assistant models list|show <name>|pull <source>|rm <name>|prune [--json]
    python -m assistant recommend [--json]
    python -m assistant status [--json]
    python -m assistant install-state record|show
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
