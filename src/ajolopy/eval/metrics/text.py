"""Text-shape helpers: ``exact_match``, ``contains``, ``not_contains``, ``intent_match``.

Every helper coerces its ``output`` / ``text`` argument through
:func:`_resolve.coerce_to_text` so the behaviour is identical: an
:class:`~ajolopy.eval.results.EvalOutput` reduces to its ``.text``
field, a ``str`` passes through, and anything else raises
:class:`MetricsConfigError`.

All helpers return a ``float`` in ``[0.0, 1.0]``.
"""

from typing import TYPE_CHECKING, Literal

from ._resolve import coerce_to_text
from .errors import MetricsConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence


def exact_match(
    output: object,
    expected: object,
    *,
    case_insensitive: bool = False,
) -> float:
    """Return ``1.0`` if ``output`` and ``expected`` match exactly after stripping.

    - ``output`` is coerced through :func:`coerce_to_text`.
    - ``expected`` is coerced via :func:`str` (so ``exact_match("42", 42)``
      returns ``1.0``).
    - Leading / trailing whitespace is stripped on BOTH sides before
      comparison.
    - Case-sensitive by default; pass ``case_insensitive=True`` to
      lowercase both sides first.
    """
    text = coerce_to_text(output, helper_name="exact_match")
    expected_text = str(expected)
    if case_insensitive:
        text = text.lower()
        expected_text = expected_text.lower()
    return 1.0 if text.strip() == expected_text.strip() else 0.0


def contains(
    text: object,
    needles: str | Sequence[str],
    *,
    mode: Literal["any", "all"] = "any",
    case_sensitive: bool = False,
) -> float:
    """Return ``1.0`` if ``text`` contains the configured needle(s).

    - ``text`` is coerced through :func:`coerce_to_text`.
    - ``needles`` is a single ``str`` or a ``Sequence[str]``.
    - ``mode="any"`` (default): at least one needle must be present.
    - ``mode="all"``: every needle must be present.
    - Case-insensitive by default; override with ``case_sensitive=True``.
    - An empty needles list raises :class:`MetricsConfigError`.
    """
    text_str = coerce_to_text(text, helper_name="contains")
    needle_list = _normalise_needles(needles, helper_name="contains")
    return 1.0 if _match_contains(text_str, needle_list, mode, case_sensitive) else 0.0


def not_contains(
    text: object,
    needles: str | Sequence[str],
    *,
    mode: Literal["any", "all"] = "any",
    case_sensitive: bool = False,
) -> float:
    """Return ``1.0`` iff :func:`contains` would return ``0.0`` for the same args.

    Useful for safety checks like ``not_contains(output, ["api_key", "ssn"])``.
    """
    text_str = coerce_to_text(text, helper_name="not_contains")
    needle_list = _normalise_needles(needles, helper_name="not_contains")
    return 0.0 if _match_contains(text_str, needle_list, mode, case_sensitive) else 1.0


def intent_match(
    output: object,
    intent: str | Sequence[str],
    *,
    mode: Literal["substring", "exact"] = "substring",
) -> float:
    """Return ``1.0`` if any configured intent appears in ``output``.

    Deterministic heuristic — no LLM call:

    - Case-insensitive on both sides.
    - ``intent`` is a single ``str`` or a ``Sequence[str]``. Multi-intent
      cases match if ANY entry matches (any-of).
    - ``mode="substring"`` (default): the intent string appears anywhere
      in the output text.
    - ``mode="exact"``: whole-string equality after strip.

    An empty intent list raises :class:`MetricsConfigError`.
    """
    text = coerce_to_text(output, helper_name="intent_match").lower()
    intents = _normalise_needles(intent, helper_name="intent_match")
    intents_lower = [item.lower() for item in intents]
    if mode == "exact":
        text_stripped = text.strip()
        return 1.0 if any(text_stripped == item.strip() for item in intents_lower) else 0.0
    return 1.0 if any(item in text for item in intents_lower) else 0.0


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _normalise_needles(needles: str | Sequence[str], *, helper_name: str) -> list[str]:
    """Coerce a ``str | Sequence[str]`` argument to a non-empty ``list[str]``.

    A bare ``str`` becomes ``[needles]``. ``Sequence[str]`` is materialised
    to a list. An empty list raises :class:`MetricsConfigError`.
    """
    # A string is technically a ``Sequence[str]`` of single characters;
    # the helper API treats the bare-string case as "one needle".
    result = [needles] if isinstance(needles, str) else list(needles)
    if not result:
        raise MetricsConfigError(f"{helper_name}: needles is empty")
    return result


def _match_contains(
    text: str,
    needles: list[str],
    mode: Literal["any", "all"],
    case_sensitive: bool,
) -> bool:
    """Return whether the needles match ``text`` under the configured mode."""
    if case_sensitive:
        haystack = text
        candidates = needles
    else:
        haystack = text.lower()
        candidates = [needle.lower() for needle in needles]
    if mode == "all":
        return all(candidate in haystack for candidate in candidates)
    # ``"any"`` is the default and the contract for invalid modes — the
    # ``Literal`` annotation rejects other values at type-check time.
    return any(candidate in haystack for candidate in candidates)


__all__ = [
    "contains",
    "exact_match",
    "intent_match",
    "not_contains",
]
