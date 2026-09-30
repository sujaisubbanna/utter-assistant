"""utter - context-aware local voice -> desktop action sidecar.

Tiered execution (cheapest wins):
    T0 APP      app/context rules, no perception
    T1 A11Y     accessibility tree
    T2 KEYBOARD app shortcuts
    T3 VISION   UI-TARS-2B screenshot grounding (fallback only)
"""

__version__ = "0.1.0"
