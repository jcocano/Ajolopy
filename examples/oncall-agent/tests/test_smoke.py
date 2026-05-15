"""Smoke test — verifies the on-call example imports and the decorators land.

The test deliberately does NOT call any LLM provider, does NOT
``monkeypatch`` the SDK, and does NOT spin up the HTTP server. It only
asserts the decoration-time metadata is in place — enough to catch
import-time regressions when the upstream framework moves.
"""

from oncall_agent.agents.oncall import ChatRequest, OnCallAgent
from oncall_agent.app_module import AppModule
from oncall_agent.integrations import GitHubMCP


def test_oncall_agent_is_decorated() -> None:
    """``OnCallAgent`` survives import and exposes ``run`` / ``stream``."""
    assert hasattr(OnCallAgent, "_agent_runtime")
    assert callable(getattr(OnCallAgent, "run", None))
    assert callable(getattr(OnCallAgent, "stream", None))


def test_summarize_request_tool_is_registered() -> None:
    """``OnCallAgent.summarize_request`` carries the ``@Tool`` marker."""
    assert hasattr(OnCallAgent.summarize_request, "__ajolopy_tool__")


def test_chat_request_is_a_pydantic_model() -> None:
    """``ChatRequest`` validates against the expected wire shape."""
    request = ChatRequest.model_validate({"message": "auth down"})
    assert request.message == "auth down"


def test_github_mcp_metadata_is_present() -> None:
    """``GitHubMCP`` carries the ``@MCP`` metadata stamp."""
    assert hasattr(GitHubMCP, "_ajolopy_mcp")


def test_github_mcp_namespacing_is_github() -> None:
    """The ``@MCP`` server key namespace is ``github`` (used for tool prefixes)."""
    metadata = getattr(GitHubMCP, "_ajolopy_mcp", None)
    assert metadata is not None, "expected @MCP metadata on GitHubMCP"
    server_keys = [entry.key for entry in metadata.entries]
    assert server_keys == ["github"], (
        f"expected the @MCP block to declare exactly one server keyed 'github', got {server_keys!r}"
    )


def test_oncall_agent_lists_github_mcp_in_integrations() -> None:
    """``OnCallAgent`` references ``GitHubMCP`` via ``integrations=``."""
    runtime = getattr(OnCallAgent, "_agent_runtime", None)
    assert runtime is not None, "expected @Agent runtime on OnCallAgent"
    assert GitHubMCP in runtime.integrations, (
        "expected OnCallAgent.integrations to contain GitHubMCP"
    )


def test_stream_route_is_registered() -> None:
    """``OnCallAgent.respond`` carries ``@Stream("/chat")`` metadata."""
    method = OnCallAgent.respond
    metadata = getattr(method, "_ajolopy_stream", None)
    assert metadata is not None, "expected @Stream metadata on OnCallAgent.respond"
    assert metadata.path == "/chat"
    assert metadata.method == "POST"


def test_app_module_lists_oncall_agent() -> None:
    """``AppModule`` declares ``OnCallAgent`` so the factory picks it up."""
    metadata = getattr(AppModule, "_ajolopy_module", None)
    assert metadata is not None, "expected @Module metadata on AppModule"
    assert OnCallAgent in metadata.agents
