"""Tests for definition-time configuration validation.

Covers the "Configuration validation" acceptance group: a provider whose
constructor needs an env var fails the agent at decoration time, not at
first request.
"""

from typing import TYPE_CHECKING

import pytest

from ajolopy import Agent
from ajolopy.agent import AgentConfigError

if TYPE_CHECKING:
    from .conftest import _ConfigErrorProviderCls


def test_provider_constructor_failure_raises_agent_config_error(
    register_config_error_anthropic: type[_ConfigErrorProviderCls],
) -> None:
    _ = register_config_error_anthropic
    with pytest.raises(AgentConfigError, match="ANTHROPIC_API_KEY"):

        @Agent(model="claude-sonnet-4-7", system="…")
        class _Demo:
            pass
