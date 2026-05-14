"""Private bridge between the pricing math and the OTel chat-span attributes.

Public surface is intentionally tiny:

- :func:`set_chat_cost_attrs` — reads tokens off a :class:`Response` or
  :class:`ChunkUsage`, looks up the model in the active :class:`Catalog`,
  computes the per-tier breakdown, and writes the five
  ``gen_ai.cost_usd*`` attrs to the span. Returns the total (or ``None``)
  so the caller can collect it for the root roll-up.

- :func:`set_root_cost_total` — sums the (non-``None``) child totals and
  writes ``ajolopy.cost_usd.total`` on the ``agent.invoke`` span. When
  *every* child was unknown (no cost), the attr is omitted entirely so
  dashboards never confuse an absent value with a real $0.

This module is **not** part of the public package surface — :mod:`ajolopy.agent.runtime`
is its only caller. The public cost-math entry point is
:func:`ajolopy.observability.compute_cost_usd`.
"""

# `Span` is used only in annotations, so ruff's TC002 prefers it under
# TYPE_CHECKING — but CodeQL flags TYPE_CHECKING imports referenced via
# string forward refs as "unused" (the static analyser does not trace
# string quotes back to the import). Keeping the import at runtime is the
# tie-break that satisfies both tools; noqa pins the rationale.
from opentelemetry.trace import (
    Span,  # noqa: TC002 — runtime import keeps CodeQL happy; see note below
)

from ajolopy.observability.conventions import (
    AJOLOPY_COST_USD_TOTAL,
    GEN_AI_COST_USD,
    GEN_AI_COST_USD_CACHE_CREATION,
    GEN_AI_COST_USD_CACHE_READ,
    GEN_AI_COST_USD_INPUT,
    GEN_AI_COST_USD_OUTPUT,
)
from ajolopy.observability.pricing import (
    Catalog,
    compute_cost_usd,
    get_active_catalog,
)
from ajolopy.providers.types import ChunkUsage, Response

# `Response` and `ChunkUsage` are imported at runtime (not under
# TYPE_CHECKING) so the `UsageSource` alias below resolves immediately
# without string forward refs. CodeQL's intra-procedural analyser does not
# trace string-quoted references back to TYPE_CHECKING imports; reading the
# imports normally avoids the false positive without changing runtime
# behaviour (these are plain dataclasses with no heavy deps).
UsageSource = Response | ChunkUsage
"""The two wire types the chat span can pull tokens from."""


def set_chat_cost_attrs(
    span: Span,
    *,
    model: str,
    usage: UsageSource | None,
    catalog: Catalog | None = None,
) -> float | None:
    """Set ``gen_ai.cost_usd*`` attrs on a ``chat`` span; return the total.

    The function is a no-op (returns ``None``) when:

    - ``usage`` is ``None`` — the provider call did not emit usage at all
      (some OpenAI-compatible servers stream no terminal usage chunk).
    - the model is not in the catalog — :func:`compute_cost_usd` returns
      ``None``, the warning fires once, and no attrs land on the span.

    Otherwise the five tier attrs (``input``, ``output``, ``cache_creation``,
    ``cache_read``, plus the top-level total) are written verbatim — even
    when individual tiers contribute 0 — so dashboards can rely on the
    schema being stable per call.
    """
    if usage is None:
        return None
    if catalog is None:
        catalog = get_active_catalog()

    input_tokens = int(getattr(usage, "tokens_in", None) or getattr(usage, "input_tokens", 0))
    output_tokens = int(getattr(usage, "tokens_out", None) or getattr(usage, "output_tokens", 0))
    cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)

    total = compute_cost_usd(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
        catalog=catalog,
    )
    if total is None:
        return None

    price = catalog.get(model)
    if price is None:
        # Defensive — compute_cost_usd returns None when the model is unknown,
        # so by this point ``price`` should always be present. Guard anyway
        # so the type checker sees the narrowing.
        return None

    span.set_attribute(GEN_AI_COST_USD, float(total))
    span.set_attribute(GEN_AI_COST_USD_INPUT, input_tokens * price.input_cost_per_token)
    span.set_attribute(GEN_AI_COST_USD_OUTPUT, output_tokens * price.output_cost_per_token)
    span.set_attribute(
        GEN_AI_COST_USD_CACHE_CREATION,
        cache_creation * price.cache_creation_input_token_cost,
    )
    span.set_attribute(
        GEN_AI_COST_USD_CACHE_READ,
        cache_read * price.cache_read_input_token_cost,
    )
    return float(total)


def set_root_cost_total(span: Span, child_costs: list[float | None]) -> None:
    """Set ``ajolopy.cost_usd.total`` on the ``agent.invoke`` span.

    Filters ``None`` entries (children whose model was unknown) before
    summing. When *every* child was unknown — and therefore the filtered
    list is empty — the attr is omitted entirely. Dashboards distinguish
    "no cost data" from "real $0" by the attribute's presence.
    """
    known = [c for c in child_costs if c is not None]
    if not known:
        return
    span.set_attribute(AJOLOPY_COST_USD_TOTAL, float(sum(known)))


__all__ = [
    "UsageSource",
    "set_chat_cost_attrs",
    "set_root_cost_total",
]
