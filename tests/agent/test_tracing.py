"""Tests for the OpenTelemetry tracing knob.

Covers the "Observability" acceptance group. The provider layer's spans
remain untouched — this test only checks the `@Agent` wrapper-span.
"""

from typing import TYPE_CHECKING, Any

import pytest
from opentelemetry import trace
from opentelemetry.trace import NoOpTracerProvider

from ajolopy import Agent

if TYPE_CHECKING:
    from .conftest import FakeProvider


class _CapturingTracerProvider(NoOpTracerProvider):
    """Tracer provider that records every span created via it."""

    def __init__(self) -> None:
        super().__init__()
        self.spans: list[_CapturingSpan] = []

    def get_tracer(  # type: ignore[override]
        self,
        instrumenting_module_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> trace.Tracer:
        return _CapturingTracer(self)


class _CapturingTracer(trace.Tracer):
    def __init__(self, provider: _CapturingTracerProvider) -> None:
        self._provider = provider

    def start_span(self, name: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        span = _CapturingSpan(name)
        self._provider.spans.append(span)
        return span

    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        span = _CapturingSpan(name)
        self._provider.spans.append(span)
        return span


class _CapturingSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def __enter__(self) -> _CapturingSpan:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


@pytest.fixture
def capturing_tracer(monkeypatch: pytest.MonkeyPatch) -> _CapturingTracerProvider:
    """Patch the agent module's tracer with a capturing tracer."""
    provider = _CapturingTracerProvider()
    tracer = provider.get_tracer("ajolopy.agent")
    # The runtime caches _TRACER at import time; replace it for the test.
    from ajolopy.agent import runtime as agent_runtime

    monkeypatch.setattr(agent_runtime, "_TRACER", tracer)
    return provider


@pytest.mark.asyncio
async def test_trace_true_emits_span_with_agent_attributes(
    register_fake_anthropic: type[FakeProvider],
    capturing_tracer: _CapturingTracerProvider,
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…", trace=True)
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]
    assert len(capturing_tracer.spans) == 1
    span = capturing_tracer.spans[0]
    assert span.name == "agent.run"
    assert span.attributes["agent.name"] == "Demo"
    assert span.attributes["agent.model"] == "claude-sonnet-4-7"
    assert "agent.provider" in span.attributes


@pytest.mark.asyncio
async def test_trace_false_emits_no_spans(
    register_fake_anthropic: type[FakeProvider],
    capturing_tracer: _CapturingTracerProvider,
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]
    assert capturing_tracer.spans == []
