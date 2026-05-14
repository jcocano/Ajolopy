"""Observability tests reuse the agent suite's fakes.

The provider-registry isolation fixture comes from the repo-wide
``tests/conftest.py`` (autouse). The agent-runtime tests live in
``tests/agent/`` and define a flexible ``FakeProvider`` plus a registration
fixture for the ``anthropic`` provider key. Re-import the fixture here so
``pytest`` discovers it when the agent module is collected separately.
"""

from tests.agent.conftest import (
    fake_provider_factory,
    register_fake_anthropic,
)

__all__ = ["fake_provider_factory", "register_fake_anthropic"]
