"""Error hierarchy for the built-in metric helpers.

The helpers in :mod:`ajolopy.eval.metrics` distinguish two failure
families that callers want to handle separately:

- :class:`MetricsConfigError` — the caller passed bad arguments
  (empty needles list, ``partial=True`` on ``json_match``, plain string
  fed to ``tool_called``). Always a bug in the caller's code.
- :class:`MetricsRuntimeError` — the helper itself failed at runtime
  (``llm_judge`` could not parse a number from the LLM response).
  Surfaces inside :class:`~ajolopy.eval.EvalCaseResult.error` when the
  helper is used inside a ``@Metric`` body.

LLM provider failures inside ``llm_judge`` bubble up as
:class:`~ajolopy.providers.LLMProviderError` unwrapped — wrapping a
provider error in a metrics-layer exception would erase the original
failure context the user needs to debug their model / API key / quota.
"""


class MetricsError(Exception):
    """Base for built-in metric helper errors."""


class MetricsConfigError(MetricsError):
    """Caller-side misconfiguration (bad args at call time)."""


class MetricsRuntimeError(MetricsError):
    """Helper failed at runtime (e.g. ``llm_judge`` response parse failure)."""


__all__ = [
    "MetricsConfigError",
    "MetricsError",
    "MetricsRuntimeError",
]
