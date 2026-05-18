"""Smoke test — verifies the example imports and the decorators land.

The test deliberately does NOT call any LLM provider, does NOT
``monkeypatch`` the SDK, and does NOT spin up the HTTP server. It only
asserts the decoration-time metadata is in place plus a boot-level
regression: ``AjolopyFactory.create(AppModule)`` succeeds and mounts
``/chat``. The latter catches the AJ-98 class of failure — a
``@Stream`` handler whose ``AsyncGenerator`` return annotation lives
under ``if TYPE_CHECKING:`` blows up at boot via
``NameError: name 'AsyncGenerator' is not defined`` once PEP 649 +
the framework's ``mount_streams`` evaluate the forward ref.
"""

import pytest
from support_agent.agents.support import ChatRequest, Support
from support_agent.agents.team import (
    Billing,
    Integrations,
    SupportTeam,
    Technical,
    Triage,
)

from ajolopy import AjolopyFactory


def test_support_agent_is_decorated() -> None:
    """The Step 1 ``Support`` class survives import and exposes ``run`` / ``stream``."""
    assert hasattr(Support, "_agent_runtime")
    assert callable(getattr(Support, "run", None))
    assert callable(getattr(Support, "stream", None))


def test_support_tool_is_registered() -> None:
    """``Support.lookup_order`` carries the ``@Tool`` marker."""
    assert hasattr(Support.lookup_order, "__ajolopy_tool__")


def test_chat_request_is_a_pydantic_model() -> None:
    """The Step 1 ``ChatRequest`` body validates against the expected shape."""
    request = ChatRequest.model_validate({"message": "hello"})
    assert request.message == "hello"


def test_team_agents_are_decorated() -> None:
    """Each Step 3 specialist class survives import and is ``@Agent``-decorated."""
    for cls in (Triage, Billing, Technical):
        assert hasattr(cls, "_agent_runtime")
        assert callable(getattr(cls, "run", None))


def test_billing_tool_is_registered() -> None:
    """``Billing.issue_refund`` carries the ``@Tool`` marker."""
    assert hasattr(Billing.issue_refund, "__ajolopy_tool__")


def test_integrations_mcp_metadata_is_present() -> None:
    """``Integrations`` carries the ``@MCP`` metadata stamp."""
    assert hasattr(Integrations, "_ajolopy_mcp")


def test_workflow_is_decorated() -> None:
    """The Step 3 ``SupportTeam`` workflow exposes ``run`` / ``stream``."""
    assert hasattr(SupportTeam, "_workflow_runtime")
    assert callable(getattr(SupportTeam, "run", None))
    assert callable(getattr(SupportTeam, "stream", None))


@pytest.mark.asyncio
async def test_team_mode_app_mounts_chat_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """AJ-98 regression: ``AjolopyFactory.create`` must boot + mount ``/chat``.

    Forces ``SUPPORT_AGENT_MODE=team`` (the default) so the workflow's
    ``@Stream("/chat")`` handler — whose ``AsyncGenerator`` return
    annotation is the one that previously crashed under PEP 649 — goes
    through the framework's ``mount_streams`` path. The assertion is
    that the route lands on ``app.http``; without the AJ-98 fix the
    factory raises ``NameError`` before we ever get here.
    """
    monkeypatch.setenv("SUPPORT_AGENT_MODE", "team")
    # Re-import the module under the new env to pick up the team module.
    import importlib

    from support_agent import app_module as app_module_pkg

    app_module_pkg = importlib.reload(app_module_pkg)

    app = await AjolopyFactory.create(app_module_pkg.AppModule)
    try:
        paths = {getattr(route, "path", "") for route in app.http.routes}
        assert "/chat" in paths, (
            f"Expected /chat mounted on team-mode app; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()


@pytest.mark.asyncio
async def test_single_mode_app_mounts_chat_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """AJ-98 regression: single-agent mode also boots and mounts ``/chat``."""
    monkeypatch.setenv("SUPPORT_AGENT_MODE", "single")
    import importlib

    from support_agent import app_module as app_module_pkg

    app_module_pkg = importlib.reload(app_module_pkg)

    app = await AjolopyFactory.create(app_module_pkg.AppModule)
    try:
        paths = {getattr(route, "path", "") for route in app.http.routes}
        assert "/chat" in paths, (
            f"Expected /chat mounted on single-mode app; got {sorted(p for p in paths if p)}"
        )
    finally:
        await app.aclose()
