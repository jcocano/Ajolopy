"""Regression: ``@Stream`` is mountable on every primitive that can carry it.

AJ-87. Before the fix, ``AjolopyFactory.create`` only scanned
``compiled.controllers`` for ``@Stream``-decorated methods, so a
``@Stream("/x")`` declared on an ``@Agent`` (or ``@Workflow``) class
was silently never mounted on the Starlette HTTP app. The docsbot
dogfood app and the killer-demo support-agent both ship the
``@Stream`` -on-``@Agent`` idiom, so the bug broke production
deployments of either via bare uvicorn while local ``ajolopy dev``
disguised the gap.

These tests build a real :class:`AjolopyApp`, walk the Starlette
router, and assert the route is present. One assertion per primitive
that can carry ``@Stream``.

A bare ``FakeProvider`` is registered fresh per test (the repo-wide
``isolate_registry`` autouse fixture clears ``_PROVIDERS`` before every
test, so the built-in eager registrations from ``ajolopy/__init__.py``
are not visible here). The fake never reaches the wire — the assertion
is about routing, not LLM behaviour.
"""

from typing import Annotated

import pytest
from pydantic import BaseModel

from ajolopy import (
    Agent,
    AjolopyFactory,
    Module,
    Stream,
    Tool,
    Workflow,
)
from ajolopy.http import Body
from ajolopy.providers import register_provider
from tests.agent.conftest import FakeProvider


@pytest.fixture(autouse=True)
def _register_fake_anthropic() -> None:  # pyright: ignore[reportUnusedFunction]
    """Re-register the ``anthropic`` key after the autouse clear so the
    test agents/workflows below can construct without a real SDK."""
    register_provider("anthropic", FakeProvider, overwrite=True)


class _Msg(BaseModel):
    """Body payload shared across the test agents/workflows below."""

    message: str


def _mounted_paths(app: object) -> set[str]:
    """Collect path strings from the Starlette app's route table."""
    return {getattr(route, "path", "") for route in app.http.routes}  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.asyncio
async def test_stream_on_agent_class_is_mounted() -> None:
    """Regression: ``@Stream`` on an ``@Agent`` class must reach the router."""

    @Agent(model="claude-opus-4-7", system="You are a test agent.")
    class StreamingAgent:
        @Tool
        async def noop(self, x: str) -> str:
            """Tool body never runs in this test — exists so the agent is valid."""
            return x

        @Stream("/agent-stream")
        async def respond(self, body: Annotated[_Msg, Body()]):
            async for chunk in self.stream(body.message):  # pyright: ignore[reportAttributeAccessIssue]
                yield chunk

    @Module(agents=[StreamingAgent])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        paths = _mounted_paths(app)
        assert "/agent-stream" in paths, (
            f"Expected /agent-stream mounted; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_stream_on_workflow_class_is_mounted() -> None:
    """Regression: ``@Stream`` on a ``@Workflow`` class must reach the router."""

    @Agent(model="claude-opus-4-7", system="Specialist 1.")
    class SpecialistA:
        @Tool
        async def noop(self, x: str) -> str:
            return x

    @Agent(model="claude-opus-4-7", system="Specialist 2.")
    class SpecialistB:
        @Tool
        async def noop(self, x: str) -> str:
            return x

    @Workflow(coordinator="claude-opus-4-7", agents=[SpecialistA, SpecialistB])
    class StreamingTeam:
        @Stream("/workflow-stream")
        async def respond(self, body: Annotated[_Msg, Body()]):
            async for chunk in self.stream(body.message):  # pyright: ignore[reportAttributeAccessIssue]
                yield chunk

    @Module(workflows=[StreamingTeam])
    class AppModule:
        pass

    app = await AjolopyFactory.create(AppModule)
    try:
        paths = _mounted_paths(app)
        assert "/workflow-stream" in paths, (
            f"Expected /workflow-stream mounted; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()
