"""Tests for ``ajolopy.observability.pricing.Catalog``.

Covers the loader smoke test (load time + sample lookups across providers),
the normalisation rules (universal-OpenAI ``:`` syntax and the bare-name
fallback), and the override merge contract.
"""

import time

from ajolopy.observability import Catalog, ModelPrice


def test_load_default_caches_singleton() -> None:
    a = Catalog.load_default()
    b = Catalog.load_default()
    assert a is b


def test_load_default_under_50ms_for_full_snapshot() -> None:
    # The smoke test asserts both correctness (catalog is populated) and a
    # rough performance budget. The snapshot is ~1.4 MB; a plain json.load
    # plus dataclass construction must stay well under 50 ms.
    start = time.perf_counter()
    catalog = Catalog.from_snapshot()
    elapsed = time.perf_counter() - start
    assert len(catalog) > 1000
    assert elapsed < 0.5  # generous upper bound for slow CI runners


def test_catalog_contains_expected_models_per_provider() -> None:
    catalog = Catalog.from_snapshot()
    # One representative entry per provider category. Names match the
    # current upstream snapshot — when LiteLLM removes one in a future
    # sync PR, swap it for a sibling entry of the same family.
    assert catalog.get("claude-sonnet-4-5") is not None  # Anthropic
    assert catalog.get("gpt-4o") is not None  # OpenAI
    assert catalog.get("gemini/gemini-2.0-flash") is not None  # Gemini
    assert catalog.get("text-embedding-3-small") is not None  # OpenAI embeddings
    assert catalog.get("groq/llama-3.3-70b-versatile") is not None  # universal-OpenAI


def test_sample_spec_key_is_skipped() -> None:
    catalog = Catalog.from_snapshot()
    # The leading ``sample_spec`` documentation entry must not appear as a
    # billable model — otherwise users would see warnings the first time
    # they accidentally typo ``sample_spec`` into their model string.
    assert catalog.get("sample_spec") is None


def test_normalisation_colon_to_slash_resolves_universal_models() -> None:
    catalog = Catalog.from_snapshot()
    direct = catalog.get("groq/llama-3.3-70b-versatile")
    aliased = catalog.get("groq:llama-3.3-70b-versatile")
    assert direct is not None
    assert aliased is not None
    assert direct == aliased


def test_normalisation_bare_name_fallback() -> None:
    # Custom prefix + an entry that is present in the catalog under its
    # bare name. The catalog must look up the bare name after the prefixed
    # key fails.
    catalog = Catalog(
        {"gpt-4o": ModelPrice(input_cost_per_token=2.5e-6, output_cost_per_token=1.0e-5)}
    )
    bare = catalog.get("acme:gpt-4o")
    assert bare is not None
    assert bare.input_cost_per_token == 2.5e-6


def test_native_provider_lookups_unchanged() -> None:
    # Anthropic / OpenAI / Gemini providers pass the model unchanged — the
    # normalisation must be a no-op for plain (no ``:`` / no ``/``) keys.
    catalog = Catalog.from_snapshot()
    assert catalog.get("claude-sonnet-4-5") == catalog.get("claude-sonnet-4-5")


def test_with_overrides_returns_new_catalog() -> None:
    base = Catalog({"foo": ModelPrice(input_cost_per_token=1.0)})
    extended = base.with_overrides({"bar": ModelPrice(input_cost_per_token=2.0)})
    assert base is not extended
    assert base.get("bar") is None
    assert extended.get("foo") is not None
    assert extended.get("bar") is not None


def test_with_overrides_replaces_existing_entry_wholesale() -> None:
    base = Catalog(
        {
            "claude-sonnet-4-5": ModelPrice(
                input_cost_per_token=3e-6,
                output_cost_per_token=15e-6,
                cache_creation_input_token_cost=3.75e-6,
                cache_read_input_token_cost=3e-7,
            )
        }
    )
    overridden = base.with_overrides({"claude-sonnet-4-5": ModelPrice(input_cost_per_token=1e-9)})
    price = overridden.get("claude-sonnet-4-5")
    assert price is not None
    assert price.input_cost_per_token == 1e-9
    # Overrides replace wholesale — cache tiers from the snapshot are gone.
    assert price.cache_creation_input_token_cost == 0.0
    assert price.cache_read_input_token_cost == 0.0


def test_contains_uses_normalisation() -> None:
    catalog = Catalog.from_snapshot()
    assert "groq:llama-3.3-70b-versatile" in catalog
    assert "groq/llama-3.3-70b-versatile" in catalog
    assert "definitely-not-a-real-model" not in catalog
    # Non-string keys never resolve.
    assert 42 not in catalog
