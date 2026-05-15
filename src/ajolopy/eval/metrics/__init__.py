"""Public surface of :mod:`ajolopy.eval.metrics` — built-in metric helpers.

The seven helpers are plain functions; users wrap them inside their
own ``@Metric`` methods on an ``@Eval`` suite. None of them is
re-exported at the top-level ``ajolopy`` namespace — the surface
stays under :mod:`ajolopy.eval.metrics` so the package-root reads as
"primitives only".

Importing this module is cheap: no network calls, no I/O. ``llm_judge``
lazily resolves a provider only when first invoked.
"""

from .errors import MetricsConfigError, MetricsError, MetricsRuntimeError
from .judge import JudgeCache, llm_judge
from .structured import json_match
from .text import contains, exact_match, intent_match, not_contains
from .tools import tool_called

__all__ = [
    "JudgeCache",
    "MetricsConfigError",
    "MetricsError",
    "MetricsRuntimeError",
    "contains",
    "exact_match",
    "intent_match",
    "json_match",
    "llm_judge",
    "not_contains",
    "tool_called",
]
