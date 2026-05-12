"""Tests that `@Agent` consumes the provider registry, not concrete classes.

Covers the "Multi-provider routing" acceptance group.
"""

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentConfigError
from ajolopy.providers import register_provider

from .conftest import FakeProvider


def _provider_key(cls: type) -> str:
    # AgentRuntime is bound as a class-level attribute by the decorator; the
    # tests reach into framework internals on purpose.
    return str(cls._agent_runtime._primary_provider_key)


def test_claude_model_resolves_to_anthropic_provider(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-sonnet-4-7", system="…")
    class Demo:
        pass

    assert _provider_key(Demo) == "anthropic"


def test_gpt_model_resolves_to_openai_when_registered() -> None:
    register_provider("openai", FakeProvider)

    @Agent(model="gpt-4o-mini", system="…")
    class Demo:
        pass

    assert _provider_key(Demo) == "openai"


def test_ollama_prefix_resolves_to_universal_openai_when_registered() -> None:
    register_provider("universal-openai", FakeProvider)

    @Agent(model="ollama:llama3.3", system="…")
    class Demo:
        pass

    assert _provider_key(Demo) == "universal-openai"


def test_unregistered_provider_raises_agent_config_error() -> None:
    # gpt-* routes to "openai" but no provider is registered → fail fast.
    with pytest.raises(AgentConfigError, match="openai"):

        @Agent(model="gpt-4o-mini", system="…")
        class _Demo:
            pass
