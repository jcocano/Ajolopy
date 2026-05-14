"""Tests for the observability layer (``ajolopy.observability``).

Uses the OTel SDK's ``InMemorySpanExporter`` to capture spans emitted by the
``AgentRuntime`` and asserts:

- the ``agent.invoke {AgentName}`` root span shape,
- the ``chat {model}`` child span with ``gen_ai.*`` attributes,
- the ``execute_tool {tool_name}`` grandchild span,
- the fallback path producing sibling ``chat`` spans under one root,
- tool exceptions surfaced as ``Status(ERROR)`` + recorded exception,
- the SDK-absent no-op behaviour (smoke-test for
  :func:`setup_tracing_from_env`).

The SDK / exporter come from ``ajolopy[otel]``. The provider layer is faked
out with :class:`tests.agent.conftest.FakeProvider`.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, override

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from ajolopy import Agent
from ajolopy.providers import (
    Chunk,
    ChunkUsage,
    LLMProvider,
    LLMProviderError,
    Response,
    ToolCall,
    register_provider,
)
from tests.agent.conftest import FakeProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# ---------------------------------------------------------------------------
# SDK fixtures
# ---------------------------------------------------------------------------


_session_exporter: InMemorySpanExporter = InMemorySpanExporter()
_session_state: dict[str, bool] = {"installed": False}


def _ensure_session_provider() -> InMemorySpanExporter:
    """Install a shared SDK TracerProvider once per process.

    OTel's api blocks re-installing the global ``TracerProvider`` (so a
    per-test ``set_tracer_provider`` call after the first one is a silent
    no-op with a warning). We work around it by installing the SDK provider
    once for the whole test session and letting each test clear the shared
    exporter via :meth:`InMemorySpanExporter.clear`.
    """
    if not _session_state["installed"]:
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_session_exporter))
        trace.set_tracer_provider(provider)
        _session_state["installed"] = True
    return _session_exporter


@pytest.fixture
def tracer_provider() -> Iterator[InMemorySpanExporter]:
    exporter = _ensure_session_provider()
    exporter.clear()
    try:
        yield exporter
    finally:
        exporter.clear()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find(spans: list[ReadableSpan], name_prefix: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name.startswith(name_prefix)]


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


# ---------------------------------------------------------------------------
# agent.invoke + chat span tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_run_emits_invoke_and_chat_span_tree(
    register_fake_anthropic: type[FakeProvider],
    tracer_provider: InMemorySpanExporter,
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…", temperature=0.5, max_tokens=128)
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]

    spans = list(tracer_provider.get_finished_spans())
    invoke = _find(spans, "agent.invoke ")
    chats = _find(spans, "chat ")
    assert len(invoke) == 1
    assert invoke[0].name == "agent.invoke Demo"
    assert _attrs(invoke[0])["ajolopy.agent.name"] == "Demo"
    assert _attrs(invoke[0])["ajolopy.agent.operation"] == "run"
    assert _attrs(invoke[0])["ajolopy.streaming"] is False

    assert len(chats) == 1
    chat_attrs = _attrs(chats[0])
    assert chats[0].name == "chat claude-sonnet-4-7"
    assert chat_attrs["gen_ai.system"] == "unknown"  # FakeProvider's default
    assert chat_attrs["gen_ai.operation.name"] == "chat"
    assert chat_attrs["gen_ai.request.model"] == "claude-sonnet-4-7"
    assert chat_attrs["gen_ai.request.temperature"] == pytest.approx(0.5)
    assert chat_attrs["gen_ai.request.max_tokens"] == 128
    # FakeProvider's default Response sets tokens_in=1, tokens_out=2.
    assert chat_attrs["gen_ai.usage.input_tokens"] == 1
    assert chat_attrs["gen_ai.usage.output_tokens"] == 2
    # finish_reasons is always set (defaults to ["stop"]).
    assert tuple(chat_attrs["gen_ai.response.finish_reasons"]) == ("stop",)

    # chat span is a descendant of agent.invoke
    chat_parent = chats[0].parent
    invoke_context = invoke[0].context
    assert chat_parent is not None
    assert invoke_context is not None
    assert chat_parent.span_id == invoke_context.span_id


@pytest.mark.asyncio
async def test_agent_stream_marks_streaming_attribute(
    register_fake_anthropic: type[FakeProvider],
    tracer_provider: InMemorySpanExporter,
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    out: list[str] = []
    async for delta in Demo().stream("hi"):  # type: ignore[attr-defined]
        out.append(delta)
    assert "".join(out) == "chunk from claude-sonnet-4-7"

    spans = list(tracer_provider.get_finished_spans())
    invoke = _find(spans, "agent.invoke ")[0]
    assert _attrs(invoke)["ajolopy.agent.operation"] == "stream"
    assert _attrs(invoke)["ajolopy.streaming"] is True


# ---------------------------------------------------------------------------
# gen_ai.system per provider class
# ---------------------------------------------------------------------------


class _AnthropicLikeFake(FakeProvider):
    GEN_AI_SYSTEM = "anthropic"


@pytest.mark.asyncio
async def test_provider_gen_ai_system_label_is_recorded_on_chat_span(
    tracer_provider: InMemorySpanExporter,
) -> None:
    register_provider("anthropic", _AnthropicLikeFake, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("ping")  # type: ignore[attr-defined]

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    assert _attrs(chat)["gen_ai.system"] == "anthropic"


# ---------------------------------------------------------------------------
# fallback shape — sibling chat spans under one invoke
# ---------------------------------------------------------------------------


class _FailingFake(FakeProvider):
    """Override: raises on the FIRST `.complete` call to force fallback."""

    GEN_AI_SYSTEM = "anthropic"

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        if "fail" in model:
            raise LLMProviderError("simulated provider outage")
        return await super().complete(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
        )


@pytest.mark.asyncio
async def test_fallback_creates_two_chat_spans_under_one_invoke(
    tracer_provider: InMemorySpanExporter,
) -> None:
    register_provider("anthropic", _FailingFake, overwrite=True)

    @Agent(
        model="claude-fail-1",
        system="…",
        fallback="claude-ok-2",
    )
    class Demo:
        pass

    text = await Demo().run("hi")  # type: ignore[attr-defined]
    assert "claude-ok-2" in text

    spans = list(tracer_provider.get_finished_spans())
    invoke_spans = _find(spans, "agent.invoke ")
    chat_spans = _find(spans, "chat ")

    assert len(invoke_spans) == 1
    assert len(chat_spans) == 2
    chat_models = {_attrs(s)["gen_ai.request.model"] for s in chat_spans}
    assert chat_models == {"claude-fail-1", "claude-ok-2"}

    # Both chat spans must share the invoke as their parent.
    invoke_context = invoke_spans[0].context
    assert invoke_context is not None
    invoke_span_id = invoke_context.span_id
    assert all(s.parent is not None and s.parent.span_id == invoke_span_id for s in chat_spans)

    # The failing chat span must record an error status + exception event.
    failed = next(s for s in chat_spans if _attrs(s)["gen_ai.request.model"] == "claude-fail-1")
    assert failed.status.status_code == StatusCode.ERROR
    event_names = [event.name for event in failed.events]
    assert "exception" in event_names


# ---------------------------------------------------------------------------
# execute_tool span — error path
# ---------------------------------------------------------------------------


class _ToolRoutingFake(FakeProvider):
    """First call asks for a tool; second call returns a final answer."""

    GEN_AI_SYSTEM = "anthropic"


@pytest.mark.asyncio
async def test_tool_exception_marks_execute_tool_span_with_error_status(
    tracer_provider: InMemorySpanExporter,
) -> None:
    fake = _ToolRoutingFake
    register_provider("anthropic", fake, overwrite=True)

    # First response triggers the tool; second wraps up.
    saved: list[Response] = [
        Response(
            text="",
            tool_calls=[ToolCall(id="t1", name="boom", arguments={})],
            finish_reason="tool_calls",
            tokens_in=3,
            tokens_out=4,
        ),
        Response(text="all done", finish_reason="stop", tokens_in=5, tokens_out=6),
    ]

    # Patch the registry-resolved provider's responses queue before invocation.
    # The Agent decorator instantiates the provider once at decoration time;
    # we reach into the class to seed responses for both calls.

    from ajolopy import Tool as ToolDecorator

    @Agent(model="claude-sonnet-4-7", system="…")
    class DemoAgent:
        @ToolDecorator
        def boom(self) -> str:
            """Bound tool that explodes."""
            raise RuntimeError("expected failure")

    # The provider instance is owned by the runtime; seed it via the
    # decorator-bound singleton.
    provider = DemoAgent._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    assert isinstance(provider, FakeProvider)
    provider.responses = list(saved)

    await DemoAgent().run("explode")  # type: ignore[attr-defined]

    tool_spans = _find(list(tracer_provider.get_finished_spans()), "execute_tool ")
    assert len(tool_spans) == 1
    span = tool_spans[0]
    assert span.name == "execute_tool boom"
    attrs = _attrs(span)
    assert attrs["gen_ai.tool.name"] == "boom"
    assert attrs["gen_ai.tool.call.id"] == "t1"
    assert span.status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in span.events)


# ---------------------------------------------------------------------------
# Stream-path token usage flows from Chunk.usage to span attrs
# ---------------------------------------------------------------------------


class _StreamingUsageFake(FakeProvider):
    GEN_AI_SYSTEM = "anthropic"

    @override
    def stream(
        self,
        *,
        model: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:

        async def _it() -> AsyncIterator[Chunk]:
            yield Chunk(delta="he")
            yield Chunk(delta="llo")
            yield Chunk(
                delta="",
                finish_reason="stop",
                usage=ChunkUsage(input_tokens=42, output_tokens=17),
            )

        return _it()


@pytest.mark.asyncio
async def test_stream_terminal_chunk_usage_attaches_to_chat_span(
    tracer_provider: InMemorySpanExporter,
) -> None:
    register_provider("anthropic", _StreamingUsageFake, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    out: list[str] = []
    async for delta in Demo().stream("hi"):  # type: ignore[attr-defined]
        out.append(delta)
    assert "".join(out) == "hello"

    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert attrs["gen_ai.usage.input_tokens"] == 42
    assert attrs["gen_ai.usage.output_tokens"] == 17


# ---------------------------------------------------------------------------
# Privacy default: content capture off unless env says yes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_capture_default_off_omits_prompt_and_completion_attrs(
    register_fake_anthropic: type[FakeProvider],
    tracer_provider: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]
    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert "gen_ai.prompt" not in attrs
    assert "gen_ai.completion" not in attrs


@pytest.mark.asyncio
async def test_content_capture_env_var_enables_prompt_and_completion_attrs(
    register_fake_anthropic: type[FakeProvider],
    tracer_provider: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]
    chat = _find(list(tracer_provider.get_finished_spans()), "chat ")[0]
    attrs = _attrs(chat)
    assert "gen_ai.prompt" in attrs
    assert "gen_ai.completion" in attrs
    assert "hello" in attrs["gen_ai.prompt"]
    assert "claude-sonnet-4-7" in attrs["gen_ai.completion"]


# ---------------------------------------------------------------------------
# setup_tracing_from_env — graceful no-op when called twice
# ---------------------------------------------------------------------------


def test_setup_tracing_from_env_is_idempotent_when_provider_already_installed(
    tracer_provider: InMemorySpanExporter,
) -> None:
    _ = tracer_provider  # fixture installs a TracerProvider already.
    from ajolopy.observability import setup_tracing_from_env

    # A TracerProvider is already in place via the fixture; subsequent calls
    # must report False and NOT replace it.
    assert setup_tracing_from_env() is False
    assert setup_tracing_from_env() is False


def test_is_content_capture_enabled_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from ajolopy.observability import is_content_capture_enabled

    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    assert is_content_capture_enabled() is False

    for truthy in ("true", "1", "yes", "on", "TRUE", "On"):
        monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", truthy)
        assert is_content_capture_enabled() is True

    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "no")
    assert is_content_capture_enabled() is False


# ---------------------------------------------------------------------------
# Ensure the conftest's _ConfigErrorProviderCls type alias is satisfied so
# the import of FakeProvider above stays useful (silence unused warnings if
# any test fixture changes).
# ---------------------------------------------------------------------------


def test_llm_provider_default_gen_ai_system_is_unknown() -> None:
    """``LLMProvider.GEN_AI_SYSTEM`` is ``unknown`` so test fakes that do not
    override it still emit a defined attribute on the chat span."""
    assert LLMProvider.GEN_AI_SYSTEM == "unknown"
    assert LLMProvider.gen_ai_system_for("any-model") == "unknown"
