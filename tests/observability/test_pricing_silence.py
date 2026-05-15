"""Tests for AJ-70 unknown-model warning silence behaviour.

Covers the three silencing sources documented in
``specs/pricing-catalog-silence-local-models.md``:

1. Default silent prefixes (``_DEFAULT_SILENT_PREFIXES``) — currently
   only ``ollama``. The framework's wedge user (local-LLM onboarding via
   AJ-66's Ollama example) gets a quiet startup with zero ceremony.
2. Exact model strings in :attr:`Catalog._silence_models`.
3. Prefix tokens in :attr:`Catalog._silence_models`.

The chat-span emission contract is unchanged in every silenced case:
unknown models still omit ``gen_ai.cost_usd*``. Only the log line goes
away.
"""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import Agent
from ajolopy.observability import Catalog, ModelPrice
from ajolopy.observability.pricing import (
    _DEFAULT_SILENT_PREFIXES,
    _prefix_segment,
    set_default_catalog,
)
from ajolopy.providers import register_provider
from tests.agent.conftest import FakeProvider
from tests.observability.conftest import ensure_session_provider


@pytest.fixture
def tracer_provider() -> Iterator[InMemorySpanExporter]:
    exporter = ensure_session_provider()
    exporter.clear()
    try:
        yield exporter
    finally:
        exporter.clear()


@pytest.fixture
def reset_active_catalog() -> Iterator[None]:
    try:
        yield
    finally:
        set_default_catalog(None)


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


# ---------------------------------------------------------------------------
# Default silent-prefix list (Option A half of the AJ-70 design)
# ---------------------------------------------------------------------------


def test_default_silent_prefixes_includes_ollama() -> None:
    """v0.1 ships exactly one silent prefix; future additions are spec'd."""
    assert "ollama" in _DEFAULT_SILENT_PREFIXES


def test_ollama_prefix_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    catalog = Catalog({})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        assert catalog.get("ollama:llama3.3") is None
        assert catalog.get("ollama:qwen3-coder-30b-a3b-instruct-mlx") is None

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    # Both models are silenced — zero log lines on the pricing logger.
    assert warnings == []


def test_ollama_prefix_still_omits_cost_attrs() -> None:
    # The silence covers the warning, NOT the cost math. compute_cost via
    # ``catalog.get`` still returns None for an unknown ollama model.
    catalog = Catalog({})
    assert catalog.get("ollama:llama3.3") is None


# ---------------------------------------------------------------------------
# Default cloud-model behaviour is preserved
# ---------------------------------------------------------------------------


def test_unknown_cloud_model_still_warns(caplog: pytest.LogCaptureFixture) -> None:
    catalog = Catalog({})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        assert catalog.get("claude-foo-99") is None

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "claude-foo-99" in message
    assert "pricing_overrides" in message


def test_dedup_still_holds_for_unknown_cloud_model(caplog: pytest.LogCaptureFixture) -> None:
    catalog = Catalog({})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        catalog.get("gpt-foo-99")
        catalog.get("gpt-foo-99")
        catalog.get("gpt-foo-99")

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    # First call warns; subsequent calls dedupe.
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# ``silence_models`` kwarg — exact model match
# ---------------------------------------------------------------------------


def test_silence_models_exact_match_skips_warning(caplog: pytest.LogCaptureFixture) -> None:
    catalog = Catalog({}, silence_models={"my-custom-model"})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        assert catalog.get("my-custom-model") is None
        assert catalog.get("my-other-model") is None

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    # Only ``my-other-model`` should fire — the silenced one stays quiet.
    assert len(warnings) == 1
    assert "my-other-model" in warnings[0].getMessage()


# ---------------------------------------------------------------------------
# ``silence_models`` kwarg — prefix-token match
# ---------------------------------------------------------------------------


def test_silence_models_prefix_token_silences_all_models_under_prefix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = Catalog({}, silence_models={"vllm"})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        assert catalog.get("vllm:foo") is None
        assert catalog.get("vllm:bar") is None
        assert catalog.get("vllm/baz") is None

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    assert warnings == []


def test_silence_models_accepts_arbitrary_iterables() -> None:
    # list, set, tuple, generator — Catalog normalises to a frozen set.
    Catalog({}, silence_models=["a", "b"])
    Catalog({}, silence_models={"a", "b"})
    Catalog({}, silence_models=("a", "b"))
    Catalog({}, silence_models=(x for x in ("a", "b")))


# ---------------------------------------------------------------------------
# ``with_silence`` returns a new catalog with the extra models silenced
# ---------------------------------------------------------------------------


def test_with_silence_returns_new_catalog(caplog: pytest.LogCaptureFixture) -> None:
    base = Catalog({})
    extended = base.with_silence("custom-prefix")
    assert base is not extended

    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        # Base catalog still warns for the new prefix.
        base.get("custom-prefix:foo")
        # Extended catalog stays silent.
        extended.get("custom-prefix:bar")

    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    assert len(warnings) == 1
    assert "custom-prefix:foo" in warnings[0].getMessage()


def test_with_overrides_preserves_silence_policy() -> None:
    base = Catalog({}, silence_models={"vllm"})
    overridden = base.with_overrides({"acme-model": ModelPrice(input_cost_per_token=1e-6)})
    # The new catalog keeps the silence policy from the receiver.
    assert "vllm" in overridden._silence_models


def test_with_silence_preserves_pricing_data() -> None:
    base = Catalog({"foo": ModelPrice(input_cost_per_token=1e-6)})
    extended = base.with_silence("vllm")
    # The new catalog keeps the pricing data from the receiver.
    price = extended.get("foo")
    assert price is not None
    assert price.input_cost_per_token == 1e-6


# ---------------------------------------------------------------------------
# Dedup invariant survives the silence-policy mid-process change
# ---------------------------------------------------------------------------


def test_silenced_model_records_in_warned_set(caplog: pytest.LogCaptureFixture) -> None:
    """A silenced lookup still records the model so dedup holds.

    Without this guarantee, a catalog whose silence policy changes
    mid-process could end up logging twice for the same model. The
    pricing module's invariant ("at most one log line per model per
    process") is enforced regardless of policy changes.
    """
    catalog = Catalog({}, silence_models={"vllm"})
    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        catalog.get("vllm:foo")  # silenced
        catalog.get("vllm:foo")  # silenced + already-warned set
    # Internal observation: the model lives in the dedup set even when
    # silenced. Documented behaviour from the spec; assert via the
    # private set to lock the invariant.
    assert "vllm:foo" in catalog._warned_unknown


# ---------------------------------------------------------------------------
# Prefix-segment helper
# ---------------------------------------------------------------------------


def test_prefix_segment_handles_colon_slash_and_bare_names() -> None:
    assert _prefix_segment("ollama:llama3.3") == "ollama"
    assert _prefix_segment("groq/llama-3.3-70b-versatile") == "groq"
    # Mixed separators — earliest wins.
    assert _prefix_segment("groq:foo/bar") == "groq"
    assert _prefix_segment("groq/foo:bar") == "groq"
    # Bare names have no prefix.
    assert _prefix_segment("claude-sonnet-4-5") is None
    # Defensive: an empty prefix (`":foo"`) returns None so an
    # accidentally-empty entry in a silence list never matches everything.
    assert _prefix_segment(":foo") is None


# ---------------------------------------------------------------------------
# Span-level integration: ollama spans stay quiet AND keep their attrs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_chat_span_has_no_cost_and_no_warning(
    tracer_provider: InMemorySpanExporter,
    reset_active_catalog: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end: an unknown ``ollama:*`` model emits zero pricing
    warnings AND keeps every other AJ-28 chat-span attribute intact."""
    _ = reset_active_catalog
    set_default_catalog(Catalog({}))
    # The ``ollama:`` prefix routes through the universal-openai provider;
    # register a FakeProvider so the runtime can stub the chat call.
    register_provider("universal-openai", FakeProvider, overwrite=True)

    @Agent(model="ollama:llama3.3", system="…")
    class Demo:
        pass

    with caplog.at_level(logging.WARNING, logger="ajolopy.observability.pricing"):
        text = await Demo().run("hi")  # type: ignore[attr-defined]
    assert text  # FakeProvider's default reply.

    # Zero warnings on the pricing logger — the wedge user's startup
    # screen stays clean.
    warnings = [r for r in caplog.records if r.name == "ajolopy.observability.pricing"]
    assert warnings == []

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    # Cost attrs absent (unchanged from AJ-30 behaviour for unknown models).
    assert "gen_ai.cost_usd" not in attrs
    # Standard AJ-28 attrs still present.
    assert attrs["gen_ai.request.model"] == "ollama:llama3.3"
    assert attrs["gen_ai.usage.input_tokens"] == 1
    assert attrs["gen_ai.usage.output_tokens"] == 2
