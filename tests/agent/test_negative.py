"""Negative-path tests for `@Agent`.

Covers the "Negative cases" acceptance group: unknown prefix surfaces a
clear error, exhausted providers raise a typed AgentError instead of a
raw provider exception, and tool_use responses raise
AgentToolUseUnsupportedError.
"""

import pytest

from ajolopy import Agent
from ajolopy.agent import (
    AgentConfigError,
    AgentProviderError,
    AgentToolUseUnsupportedError,
)
from ajolopy.providers import (
    LLMProviderError,
    Response,
    ToolCall,
    register_provider,
)

from .conftest import FakeProvider


def test_unknown_model_prefix_raises_config_error_with_supported_patterns(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic
    with pytest.raises(AgentConfigError) as info:

        @Agent(model="bogus-foo", system="…")
        class _Demo:
            pass

    message = str(info.value)
    assert "bogus-foo" in message
    assert "claude-*" in message  # supported pattern hint propagates


@pytest.mark.asyncio
async def test_network_error_after_retries_raises_typed_agent_error() -> None:
    class _AlwaysFails(FakeProvider):
        async def complete(self, **kwargs: object) -> Response:  # type: ignore[override]
            raise LLMProviderError("connection refused")

    register_provider("anthropic", _AlwaysFails, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    with pytest.raises(AgentProviderError):
        await Demo().run("hello")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_tool_use_response_raises_unsupported_error_until_aj2() -> None:
    class _ToolUseProvider(FakeProvider):
        async def complete(self, **kwargs: object) -> Response:  # type: ignore[override]
            return Response(
                text="",
                tool_calls=[ToolCall(id="tool_1", name="lookup", arguments={})],
                tokens_in=1,
                tokens_out=1,
                finish_reason="tool_calls",
            )

    register_provider("anthropic", _ToolUseProvider, overwrite=True)

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    with pytest.raises(AgentToolUseUnsupportedError, match="AJ-2"):
        await Demo().run("hello")  # type: ignore[attr-defined]
