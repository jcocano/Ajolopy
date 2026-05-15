"""Internal helpers shared by every metric in :mod:`ajolopy.eval.metrics`.

The coercion rule "an :class:`EvalOutput` collapses to its ``.text``
field; a ``str`` passes through" is centralised here so every helper
applies it identically and the user-facing error message uses one
template.
"""

from typing import TYPE_CHECKING

from .errors import MetricsConfigError

if TYPE_CHECKING:
    from ajolopy.eval.results import EvalOutput


def coerce_to_text(value: object, *, helper_name: str) -> str:
    """Reduce ``value`` to plain text using the shared metrics rule.

    - :class:`~ajolopy.eval.results.EvalOutput` → ``value.text``.
    - ``str`` → returned verbatim.
    - Anything else → :class:`MetricsConfigError` naming the offending
      helper and the rejected type.

    ``helper_name`` is interpolated into the error message so users
    see ``"exact_match requires str or EvalOutput; got int"`` instead
    of a generic ``"bad type"``.
    """
    # Local import keeps :mod:`ajolopy.eval.metrics` independent of the
    # results module at import time — the latter is fine to load lazily
    # because this function only runs inside helper bodies.
    from ajolopy.eval.results import EvalOutput

    if isinstance(value, EvalOutput):
        return value.text
    if isinstance(value, str):
        return value
    raise MetricsConfigError(
        f"{helper_name} requires str or EvalOutput; got {type(value).__name__}"
    )


def require_eval_output(value: object, *, helper_name: str) -> EvalOutput:
    """Variant for helpers that need the structured output (not just text).

    ``tool_called`` reads ``output.tool_calls``; passing a plain string
    is unambiguously wrong because there is no tool-call list to read.
    """
    from ajolopy.eval.results import EvalOutput

    if isinstance(value, EvalOutput):
        return value
    raise MetricsConfigError(f"{helper_name} requires an EvalOutput (got {type(value).__name__})")


__all__ = ["coerce_to_text", "require_eval_output"]
