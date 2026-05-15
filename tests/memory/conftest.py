"""Fixtures local to ``tests/memory/``.

Re-exports ``register_fake_anthropic`` (defined in
``tests/agent/conftest.py``) so the agent-integration tests in this
package can register a fake LLM provider without duplicating the
fixture body.
"""

from tests.agent.conftest import (
    fake_provider_factory as fake_provider_factory,
)
from tests.agent.conftest import (
    register_fake_anthropic as register_fake_anthropic,
)
