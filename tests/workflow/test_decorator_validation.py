"""Decoration-time validation for ``@Workflow``.

Covers the "Decoration-time validation" acceptance group in
``specs/workflow.md``. Every test asserts the decorator either fails
fast with :class:`WorkflowConfigError` or wires the runtime cleanly,
without any provider call.
"""

import logging
from typing import Any

import pytest

from ajolopy import Agent, Workflow
from ajolopy.workflow import WorkflowConfigError

from .conftest import ScriptedStreamProvider

_ = ScriptedStreamProvider  # imported for type-link clarity in scripted tests


def _register_anthropic() -> None:
    from ajolopy.providers import register_provider

    register_provider("anthropic", ScriptedStreamProvider, overwrite=True)


def _make_agents() -> tuple[type[object], type[object]]:
    _register_anthropic()

    @Agent(model="claude-sonnet-4-7", system="…")
    class _A:
        """Specialist A."""

    @Agent(model="claude-sonnet-4-7", system="…")
    class _B:
        """Specialist B."""

    return _A, _B


def test_decorated_class_exposes_run_and_stream() -> None:
    agent_a, agent_b = _make_agents()

    @Workflow(coordinator="claude-sonnet-4-7", agents=[agent_a, agent_b])
    class Team:
        """Demo team."""

    instance: Any = Team()
    assert callable(instance.run)
    assert callable(instance.stream)


def test_empty_agents_list_raises() -> None:
    with pytest.raises(WorkflowConfigError, match="at least one"):

        @Workflow(coordinator="claude-sonnet-4-7", agents=[])
        class _Team:
            pass


def test_non_agent_entry_raises_naming_the_class() -> None:
    agent_a, _ = _make_agents()

    class NotAgent:
        pass

    with pytest.raises(WorkflowConfigError, match="NotAgent"):

        @Workflow(coordinator="claude-sonnet-4-7", agents=[agent_a, NotAgent])
        class _Team:
            pass


def test_missing_coordinator_and_route_raises_with_helpful_message() -> None:
    agent_a, agent_b = _make_agents()

    with pytest.raises(WorkflowConfigError, match=r"coordinator=.*route"):

        @Workflow(agents=[agent_a, agent_b])
        class _Team:
            pass


def test_max_steps_zero_raises() -> None:
    agent_a, _ = _make_agents()
    with pytest.raises(WorkflowConfigError, match=">= 1"):

        @Workflow(coordinator="claude-sonnet-4-7", agents=[agent_a], max_steps=0)
        class _Team:
            pass


def test_max_steps_negative_raises() -> None:
    agent_a, _ = _make_agents()
    with pytest.raises(WorkflowConfigError, match=">= 1"):

        @Workflow(coordinator="claude-sonnet-4-7", agents=[agent_a], max_steps=-1)
        class _Team:
            pass


def test_unknown_coordinator_model_raises_referencing_registry() -> None:
    agent_a, _ = _make_agents()
    with pytest.raises(WorkflowConfigError, match="Unknown coordinator model"):

        @Workflow(coordinator="not-a-real-model", agents=[agent_a])
        class _Team:
            pass


def test_route_override_shadows_coordinator_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent_a, agent_b = _make_agents()

    caplog.set_level(logging.INFO, logger="ajolopy.workflow")

    @Workflow(coordinator="claude-sonnet-4-7", agents=[agent_a, agent_b])
    class _Team:
        async def route(self, message: str, context: dict[str, object]) -> type[object]:
            _ = (message, context)
            return agent_a

    # The decorator does not raise; the info log mentions both
    # primitives so the user notices the dead coordinator.
    records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("route()" in r.getMessage() for r in records)


def test_route_without_coordinator_is_valid() -> None:
    agent_a, agent_b = _make_agents()

    @Workflow(agents=[agent_a, agent_b])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[object]:
            _ = (message, context)
            return agent_a

    instance: Any = Team()
    assert callable(instance.run)
    assert callable(instance.stream)


def test_duplicate_agent_entries_raise() -> None:
    agent_a, _ = _make_agents()
    with pytest.raises(WorkflowConfigError, match="duplicate"):

        @Workflow(coordinator="claude-sonnet-4-7", agents=[agent_a, agent_a])
        class _Team:
            pass
