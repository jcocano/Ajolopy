"""Tests for ``compute_cost_usd`` math.

Asserts the per-tier sum, the unknown-model behaviour, the float precision
on billing-scale inputs, and the public embeddings entry point.
"""

import pytest

from ajolopy.observability import Catalog, ModelPrice, compute_cost_usd


@pytest.fixture
def sonnet_catalog() -> Catalog:
    """A tiny catalog with the real Sonnet 4.7 rates for math assertions."""
    return Catalog(
        {
            "claude-sonnet-4-7": ModelPrice(
                input_cost_per_token=3e-6,
                output_cost_per_token=15e-6,
                cache_creation_input_token_cost=3.75e-6,
                cache_read_input_token_cost=3e-7,
            )
        }
    )


def test_returns_none_for_unknown_model() -> None:
    catalog = Catalog({})
    assert compute_cost_usd("missing", input_tokens=100, catalog=catalog) is None


def test_returns_zero_when_known_model_has_no_tokens(sonnet_catalog: Catalog) -> None:
    assert compute_cost_usd("claude-sonnet-4-7", catalog=sonnet_catalog) == 0.0


def test_input_tier_sonnet_baseline(sonnet_catalog: Catalog) -> None:
    # 1000 input tokens * $3.00 / 1M = $0.003.
    cost = compute_cost_usd("claude-sonnet-4-7", input_tokens=1000, catalog=sonnet_catalog)
    assert cost == pytest.approx(0.003)


def test_cache_read_tier_sonnet_baseline(sonnet_catalog: Catalog) -> None:
    # 1000 cache-read tokens * $0.30 / 1M = $0.0003.
    cost = compute_cost_usd(
        "claude-sonnet-4-7",
        cache_read_input_tokens=1000,
        catalog=sonnet_catalog,
    )
    assert cost == pytest.approx(0.0003)


def test_all_tiers_sum_independently(sonnet_catalog: Catalog) -> None:
    cost = compute_cost_usd(
        "claude-sonnet-4-7",
        input_tokens=1000,
        output_tokens=500,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=300,
        catalog=sonnet_catalog,
    )
    expected = 1000 * 3e-6 + 500 * 15e-6 + 200 * 3.75e-6 + 300 * 3e-7
    assert cost == pytest.approx(expected)


def test_missing_tier_contributes_zero_not_none() -> None:
    # OpenAI-style entry: no cache_creation tier. Asking for cache creation
    # tokens should not turn the call into ``None``.
    catalog = Catalog(
        {
            "gpt-4o": ModelPrice(
                input_cost_per_token=2.5e-6,
                output_cost_per_token=1e-5,
                cache_read_input_token_cost=1.25e-6,
            )
        }
    )
    cost = compute_cost_usd(
        "gpt-4o",
        input_tokens=1000,
        cache_creation_input_tokens=10_000,
        catalog=catalog,
    )
    assert cost == pytest.approx(1000 * 2.5e-6)


def test_float_precision_billion_input_tokens(sonnet_catalog: Catalog) -> None:
    # 1 billion tokens * $3 / 1M = $3000.0 exactly in IEEE-754.
    cost = compute_cost_usd("claude-sonnet-4-7", input_tokens=1_000_000_000, catalog=sonnet_catalog)
    assert cost == 3000.0


def test_compute_cost_usd_resolves_active_catalog_by_default() -> None:
    # No explicit catalog → falls back to the process-wide default. Use a
    # model from the embedded snapshot to prove the wiring; rely on it
    # being non-zero so the assertion is robust to upstream price updates.
    cost = compute_cost_usd("gpt-4o", input_tokens=1000)
    assert cost is not None
    assert cost > 0


def test_embeddings_model_resolvable_via_compute_cost_usd() -> None:
    cost = compute_cost_usd("text-embedding-3-small", input_tokens=1000)
    assert cost is not None
    assert cost > 0


@pytest.mark.asyncio
async def test_provider_embed_emits_no_spans() -> None:
    """The spec puts embeddings under ``compute_cost_usd`` math only —
    ``provider.embed()`` does NOT open its own span in v0.1. Guard with
    a regression assertion against the shared in-memory exporter."""
    from tests.agent.conftest import FakeProvider
    from tests.observability.conftest import ensure_session_provider

    exporter = ensure_session_provider()
    exporter.clear()
    provider = FakeProvider()
    out = await provider.embed(model="text-embedding-3-small", text="hello")
    assert out
    spans = list(exporter.get_finished_spans())
    assert not spans
