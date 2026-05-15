"""Smoke test — verifies the example imports and the decorators land.

The test deliberately does NOT call any LLM provider, does NOT
``monkeypatch`` the SDK, and does NOT spin up the HTTP server. It only
asserts decoration-time metadata is in place plus the stdlib-only
``lint_function`` tool's two branches — enough to catch import-time
regressions when the upstream framework moves.
"""

import asyncio
from typing import Any, cast

from local_ollama.agents.reviewer import CodeReviewer, ReviewRequest


def test_reviewer_agent_is_decorated() -> None:
    """``CodeReviewer`` survives import and exposes ``run`` / ``stream``."""
    assert hasattr(CodeReviewer, "_agent_runtime")
    assert callable(getattr(CodeReviewer, "run", None))
    assert callable(getattr(CodeReviewer, "stream", None))


def test_cross_provider_fallback_is_lazy() -> None:
    """Primary is ``ollama:*`` (eager), fallback is ``claude-*`` (lazy).

    AJ-72 wires ``fallback="claude-haiku-4-5"`` onto ``CodeReviewer`` to
    demonstrate Ajolopy's cross-provider fallback. AJ-69 made fallback
    provider construction lazy, so this example boots cleanly with no
    ``ANTHROPIC_API_KEY`` set — the Anthropic provider is only built
    when the local primary fails.

    The test reaches into ``AgentRuntime._models`` (private surface) to
    confirm both halves of the contract: primary is eagerly built, fallback
    is ``None`` at decoration time. ``getattr`` indirection sidesteps
    pyright's attribute-access checks for the decorator-injected
    ``_agent_runtime`` field without touching the framework's public types.
    """
    runtime: Any = getattr(CodeReviewer, "_agent_runtime")  # noqa: B009
    models = cast("list[tuple[str, object | None, str]]", runtime._models)
    assert len(models) == 2, "expected primary + fallback chain"

    assert models[0][0] == "ollama:llama3.3"
    assert models[0][1] is not None, "primary must be eagerly instantiated"
    assert models[1][0] == "claude-haiku-4-5"
    assert models[1][1] is None, (
        "fallback provider must be None at decoration time (AJ-69 lazy build)"
    )


def test_lint_function_tool_is_registered() -> None:
    """``CodeReviewer.lint_function`` carries the ``@Tool`` marker."""
    assert hasattr(CodeReviewer.lint_function, "__ajolopy_tool__")


def test_review_request_is_a_pydantic_model() -> None:
    """The ``ReviewRequest`` body validates against the expected shape."""
    request = ReviewRequest.model_validate({"code": "def f(): pass\n"})
    assert request.code == "def f(): pass\n"


def test_stream_route_is_registered() -> None:
    """``CodeReviewer.respond`` carries ``@Stream("/chat")`` metadata."""
    method = CodeReviewer.respond
    metadata = getattr(method, "_ajolopy_stream", None)
    assert metadata is not None, "expected @Stream metadata on CodeReviewer.respond"
    assert metadata.path == "/chat"
    assert metadata.method == "POST"


def test_lint_function_accepts_valid_code() -> None:
    """The stdlib ``ast.parse`` branch returns ``ok=True`` on valid code."""

    async def run() -> None:
        reviewer = CodeReviewer()
        result = await reviewer.lint_function("def add(a, b):\n    return a + b\n")
        assert result == {"ok": True, "error": ""}

    asyncio.run(run())


def test_lint_function_flags_syntax_error() -> None:
    """The stdlib ``ast.parse`` branch returns ``ok=False`` on broken code."""

    async def run() -> None:
        reviewer = CodeReviewer()
        result = await reviewer.lint_function('def greet(name):\n    return f"Hi, {name}\n')
        assert result["ok"] is False
        # Don't pin the exact wording — Python tweaks SyntaxError messages
        # between minor versions. Asserting on the structure is enough.
        assert isinstance(result["error"], str)
        assert result["error"], "expected a non-empty error message"

    asyncio.run(run())
