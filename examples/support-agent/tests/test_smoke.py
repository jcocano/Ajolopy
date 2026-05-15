"""Smoke test — verifies the example imports and the decorators land.

The test deliberately does NOT call any LLM provider, does NOT
``monkeypatch`` the SDK, and does NOT spin up the HTTP server. It only
asserts the decoration-time metadata is in place — enough to catch
import-time regressions when the upstream framework moves.
"""

from support_agent.agents.support import ChatRequest, Support
from support_agent.agents.team import (
    Billing,
    Integrations,
    SupportTeam,
    Technical,
    Triage,
)


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
