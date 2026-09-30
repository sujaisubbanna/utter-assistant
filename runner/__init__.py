"""utter reference runner (M0 spike).

A small Python host that implements the frozen framing + handshake, supervises
plugins, exposes a unix-socket client API and enforces the trust/policy layer.

This is a de-risking spike, not the final Rust port. stdlib only (3.12+).
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
