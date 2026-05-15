"""LLM-as-judge helper and its in-memory cache.

``llm_judge`` is the only async helper. It builds a deterministic
judge prompt, calls an :class:`~ajolopy.providers.LLMProvider`, and
parses the response back to a ``float`` in ``[0.0, 1.0]``.

Caching is opt-in:

- ``cache=False`` (default): every call hits the provider.
- ``cache=True``: hits a module-level :data:`_DEFAULT_JUDGE_CACHE`
  shared across all calls in the process.
- ``cache=<JudgeCache instance>``: hits the caller-owned cache. This
  is the documented escape hatch when isolation matters (e.g. unit
  tests, or scoped sharing across two ``@Eval`` suites).
"""

import hashlib
import re
from typing import Literal

from ajolopy.providers import (
    LLMProvider,
    Message,
    get_provider_class,
    resolve_provider,
)

from ._resolve import coerce_to_text
from .errors import MetricsRuntimeError

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


class JudgeCache:
    """In-memory cache for :func:`llm_judge`.

    A thin wrapper around a ``dict[str, float]`` so the user-facing
    type is stable across releases. The cache key is the sha256 of
    ``(criterion, output_text, expected_text_or_empty, model, scale)``;
    see :func:`_cache_key` for the exact format.
    """

    def __init__(self) -> None:
        self._store: dict[str, float] = {}

    def get(self, key: str) -> float | None:
        """Return the cached score for ``key``, or ``None`` if absent."""
        return self._store.get(key)

    def set(self, key: str, value: float) -> None:
        """Store ``value`` under ``key``."""
        self._store[key] = value

    def clear(self) -> None:
        """Empty the cache."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: object) -> bool:
        return key in self._store


# Module-level cache used when ``cache=True``. Shared across every
# call in the process; pass a fresh :class:`JudgeCache` instance to
# scope cache state per-suite / per-test.
_DEFAULT_JUDGE_CACHE: JudgeCache = JudgeCache()


async def llm_judge(
    output: object,
    *,
    criterion: str,
    model: str,
    expected: str | None = None,
    scale: Literal["0-1", "1-5"] = "0-1",
    cache: bool | JudgeCache = False,
    provider: LLMProvider | None = None,
) -> float:
    """Score ``output`` against ``criterion`` using an LLM judge.

    See ``specs/eval-metrics-builtin.md`` for the full prompt template
    and parsing rules. Highlights:

    - ``output`` is reduced via :func:`coerce_to_text`.
    - ``criterion`` and ``model`` are required.
    - ``expected=None`` omits the "ideal response" block from the
      prompt; non-``None`` includes it.
    - ``scale="0-1"`` (default) clamps responses to ``[0, 1]``;
      ``scale="1-5"`` rescales via ``(value - 1) / 4`` then clamps.
    - ``cache=True`` uses a shared module-level cache;
      ``cache=<JudgeCache>`` uses the supplied instance.
    - ``provider=None`` resolves through the registry; pass an
      instance to bypass the registry (the test seam).

    Raises :class:`MetricsRuntimeError` if no numeric content can be
    parsed from the LLM response. Provider failures bubble up as
    :class:`~ajolopy.providers.LLMProviderError` (NOT wrapped).
    """
    output_text = coerce_to_text(output, helper_name="llm_judge")
    cache_store = _select_cache(cache)
    key = _cache_key(
        criterion=criterion,
        output_text=output_text,
        expected_text=expected or "",
        model=model,
        scale=scale,
    )
    if cache_store is not None:
        cached = cache_store.get(key)
        if cached is not None:
            return cached

    prompt = _build_prompt(
        criterion=criterion,
        output_text=output_text,
        expected=expected,
        scale=scale,
    )
    judge_provider = provider if provider is not None else _resolve_default_provider(model)
    response = await judge_provider.complete(
        model=model,
        messages=[Message(role="user", content=prompt)],
        tools=None,
        temperature=0.0,
        max_tokens=50,
        cache=False,
    )
    score = _parse_score(response.text, scale=scale)
    if cache_store is not None:
        cache_store.set(key, score)
    return score


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _select_cache(cache: bool | JudgeCache) -> JudgeCache | None:
    """Resolve the ``cache=`` kwarg to a concrete :class:`JudgeCache` or ``None``."""
    if isinstance(cache, JudgeCache):
        return cache
    if cache:
        return _DEFAULT_JUDGE_CACHE
    return None


def _cache_key(
    *,
    criterion: str,
    output_text: str,
    expected_text: str,
    model: str,
    scale: str,
) -> str:
    """Build the sha256 cache key for an :func:`llm_judge` call.

    The order matches the documented contract:
    ``(criterion, output_text, expected_text_or_empty, model, scale)``.
    Components are joined by NUL bytes so two distinct ``(a, b)``
    pairs cannot collide with one ``(a + delimiter + b)`` value.
    """
    parts = "\x00".join([criterion, output_text, expected_text, model, scale])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def _build_prompt(
    *,
    criterion: str,
    output_text: str,
    expected: str | None,
    scale: Literal["0-1", "1-5"],
) -> str:
    """Construct the judge prompt per the spec template.

    The expected-block is included only when ``expected is not None`` so
    tests can assert on its presence/absence by substring.
    """
    scale_explanation = _scale_explanation(scale)
    expected_block = (
        f'Ideal/Expected response:\n"""\n{expected}\n"""\n\n' if expected is not None else ""
    )
    return (
        "You are an evaluation judge. Given an output and a criterion, score the\n"
        f"output on the scale {scale}. {scale_explanation}\n\n"
        f"Criterion: {criterion}\n\n"
        f"{expected_block}"
        "Output to score:\n"
        '"""\n'
        f"{output_text}\n"
        '"""\n\n'
        "Respond with ONLY a number on the scale; do not explain."
    )


def _scale_explanation(scale: Literal["0-1", "1-5"]) -> str:
    if scale == "1-5":
        return "1 is worst; 5 is best."
    return (
        "0 means the output fails the criterion completely. "
        "1 means it fully satisfies the criterion."
    )


def _parse_score(response_text: str, *, scale: Literal["0-1", "1-5"]) -> float:
    """Extract a number from the LLM response and project it onto ``[0, 1]``.

    Raises :class:`MetricsRuntimeError` (NOT a silent ``0.0``) when no
    numeric token is present — the user wants to see this in their
    eval output rather than a misleading score.
    """
    match = _NUMBER_PATTERN.search(response_text)
    if match is None:
        truncated = response_text[:80]
        raise MetricsRuntimeError(f"llm_judge could not parse a number from {truncated!r}")
    raw = float(match.group(0))
    rescaled = (raw - 1.0) / 4.0 if scale == "1-5" else raw
    return max(0.0, min(1.0, rescaled))


def _resolve_default_provider(model: str) -> LLMProvider:
    """Resolve ``model`` to a provider instance via the registry.

    Each call instantiates a fresh provider; the helper is a one-off
    (unlike :class:`~ajolopy.agent.runtime.AgentRuntime`, which caches
    its provider for the lifetime of the decorated class).
    """
    key = resolve_provider(model)
    provider_cls = get_provider_class(key)
    return provider_cls()


__all__ = ["JudgeCache", "llm_judge"]
