"""Negative-path tests for `@Agent`.

Covers the "Negative cases" acceptance group: unknown prefix surfaces a
clear error and exhausted providers raise a typed AgentError instead of a
raw provider exception.
"""

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentConfigError, AgentProviderError
from ajolopy.providers import LLMProviderError, Response, register_provider

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
