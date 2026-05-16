"""Tests for the `cache='prompt'` knob.

Covers the "Prompt caching" acceptance group.
"""

from typing import TYPE_CHECKING

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentConfigError

if TYPE_CHECKING:
    from .conftest import FakeProvider


@pytest.mark.asyncio
async def test_cache_prompt_with_static_system_forwards_flag(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(
        model="claude-opus-4-7",
        system="You are concise.",
        cache="prompt",
    )
    class Demo:
        pass

    await Demo().run("hello")  # type: ignore[attr-defined]
    runtime = Demo._agent_runtime  # type: ignore[attr-defined]
    provider = runtime._models[0][1]
    assert provider.complete_calls[-1]["cache"] is True


def test_cache_prompt_with_callable_system_raises_config_error(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    def dynamic_system(_msg: str) -> str:
        return "dynamic prompt"

    with pytest.raises(AgentConfigError, match="static system prompt"):

        @Agent(
            model="claude-opus-4-7",
            system=dynamic_system,
            cache="prompt",
        )
        class _Demo:
            pass
