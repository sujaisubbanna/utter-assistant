"""Router package: deterministic rules first, tiny-LLM fallback, vision last."""
from .rules import plan as rules_plan  # noqa: F401
from .planner import plan as llm_plan  # noqa: F401
from .profiles import load as load_profiles  # noqa: F401
