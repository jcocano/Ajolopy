"""Tests for the magical-default path of `@Agent`.

Covers the "Magical-default path" acceptance group.
"""

from typing import TYPE_CHECKING

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentConfigError

if TYPE_CHECKING:
    from .conftest import FakeProvider


@pytest.mark.asyncio
async def test_decorator_makes_instances_callable_via_run(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    @Agent(model="claude-opus-4-7", system="You are a test agent.")
    class Demo:
        pass

    instance = Demo()
    answer = await instance.run("hello world")  # type: ignore[attr-defined]
    assert isinstance(answer, str)
    assert "claude-opus-4-7" in answer  # FakeProvider echoes the model


def test_decorator_returns_same_class_object(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic

    class Demo:
        custom = "preserved"

    decorated = Agent(model="claude-opus-4-7", system="…")(Demo)
    # The decorator must monkey-patch in place, not wrap the class.
    assert decorated is Demo
    assert decorated.custom == "preserved"


def test_unknown_model_raises_agent_config_error_at_decoration_time(
    register_fake_anthropic: type[FakeProvider],
) -> None:
    _ = register_fake_anthropic
    with pytest.raises(AgentConfigError, match="Unknown model"):

        @Agent(model="bogus-model", system="…")
        class _Demo:
            pass
