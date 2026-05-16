"""Tests for the ``route()`` override path on ``@Workflow``.

Covers the "route() override path" acceptance group: when the decorated
class declares an async ``route(self, message, context)`` method, the
framework calls it once, validates the chosen class against ``agents=``,
delegates via ``agent_instance.run(message)``, and emits exactly one
``handoff`` -> ``agent_result`` -> ``done`` triple.
"""

from typing import Any

import pytest

from ajolopy import Agent, Workflow
from ajolopy.providers import Response, register_provider
from ajolopy.workflow import WorkflowRouteError

from .conftest import ScriptedStreamProvider


def _register_anthropic() -> None:
    register_provider("anthropic", ScriptedStreamProvider, overwrite=True)


def _make_agents() -> tuple[type[Any], type[Any], type[Any]]:
    _register_anthropic()

    @Agent(model="claude-opus-4-7", system="…")
    class Triage:
        """Triage requests."""

    @Agent(model="claude-opus-4-7", system="…")
    class Billing:
        """Billing."""

    @Agent(model="claude-opus-4-7", system="…")
    class Technical:
        """Technical."""

    return Triage, Billing, Technical


def _prime_agent_response(agent_cls: type[Any], text: str) -> None:
    """Queue a fixed response on the agent's underlying provider."""
    provider: ScriptedStreamProvider = agent_cls._agent_runtime._models[0][1]
    provider.responses = [Response(text=text, finish_reason="stop")]


@pytest.mark.asyncio
async def test_route_returns_agent_and_delegates_to_it() -> None:
    triage, billing, technical = _make_agents()
    _prime_agent_response(billing, "billing reply")

    @Workflow(agents=[triage, billing, technical])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return billing

    instance: Any = Team()
    text: str = await instance.run("refund please")
    assert text == "billing reply"


@pytest.mark.asyncio
async def test_route_emits_exactly_handoff_agent_result_done() -> None:
    triage, billing, technical = _make_agents()
    _prime_agent_response(billing, "billing reply")

    @Workflow(agents=[triage, billing, technical])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return billing

    events: list[dict[str, object]] = []
    async for event in Team().stream("refund please"):  # type: ignore[attr-defined]
        events.append(dict(event))

    types_only = [e["type"] for e in events]
    assert types_only == ["handoff", "agent_result", "done"]
    assert events[0]["agent"] == "Billing"
    assert events[0]["message"] == "refund please"
    assert events[1]["output"] == "billing reply"
    assert events[2]["text"] == "billing reply"


@pytest.mark.asyncio
async def test_route_receives_kwargs_as_context_dict() -> None:
    triage, billing, technical = _make_agents()
    _prime_agent_response(triage, "triage reply")

    captured: dict[str, object] = {}

    @Workflow(agents=[triage, billing, technical])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            captured.update(context)
            _ = message
            return triage

    await Team().run("hi", tenant="acme", priority=1)  # type: ignore[attr-defined]
    assert captured == {"tenant": "acme", "priority": 1}


@pytest.mark.asyncio
async def test_route_returning_class_not_in_agents_raises() -> None:
    triage, billing, _technical = _make_agents()

    @Agent(model="claude-opus-4-7", system="…")
    class Outsider:
        """Not registered with the workflow."""

    @Workflow(agents=[triage, billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return Outsider

    with pytest.raises(WorkflowRouteError, match="Outsider"):
        await Team().run("hi")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_route_returning_none_raises() -> None:
    triage, billing, _technical = _make_agents()

    @Workflow(agents=[triage, billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return None  # type: ignore[return-value]

    with pytest.raises(WorkflowRouteError):
        await Team().run("hi")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_route_raising_user_exception_wraps_as_workflow_route_error() -> None:
    triage, billing, _technical = _make_agents()

    @Workflow(agents=[triage, billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            raise ValueError("boom")

    with pytest.raises(WorkflowRouteError) as info:
        await Team().run("hi")  # type: ignore[attr-defined]
    # The original exception is preserved via __cause__ for telemetry.
    assert isinstance(info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_route_path_does_not_emit_token_events() -> None:
    triage, billing, _technical = _make_agents()
    _prime_agent_response(billing, "answer")

    @Workflow(agents=[triage, billing])
    class Team:
        async def route(self, message: str, context: dict[str, object]) -> type[Any]:
            _ = (message, context)
            return billing

    types_only: list[str] = []
    async for event in Team().stream("hi"):  # type: ignore[attr-defined]
        types_only.append(event["type"])
    assert "token" not in types_only
