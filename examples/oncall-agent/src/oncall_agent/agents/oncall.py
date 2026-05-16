"""The ``OnCallAgent`` — single ``@Agent`` with a local ``@Tool`` and the
GitHub MCP server attached via ``integrations=``.

The agent handles incoming on-call requests like
*"we're seeing 502s on /events, anything related in the repo?"*. It
classifies the request locally (``summarize_request``) and then leans
on the GitHub MCP server to surface related issues, recent PRs, and
commits before proposing a triage with severity and a next step.

Drift note — observability:
    ``@Agent`` does not accept ``trace=`` in v0.1; OpenTelemetry
    instrumentation is always-on and cheap when no SDK is installed.
    Backend selection happens at the SDK layer via standard OTel env
    vars (``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``).

Drift note — `@MCP` runtime requirements:
    Connecting to the GitHub MCP server requires the optional extra
    ``ajolopy[mcp]`` and a ``GITHUB_TOKEN`` env var. Without those,
    the decorator still validates at import time and the agent still
    serves — the server simply stays unhealthy and its tools are not
    advertised. The local ``summarize_request`` ``@Tool`` keeps
    answering in that mode.
"""

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body
from oncall_agent.integrations import GitHubMCP

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class ChatRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint."""

    message: str


# Severity hints used by the deterministic local stub. The list is
# intentionally short and lowercase — production on-call agents would
# replace this with a real classifier, ideally one that reads recent
# log signals or a runbook.
_HIGH_SIGNALS: tuple[str, ...] = (
    "5xx",
    "502",
    "503",
    "504",
    "outage",
    "down",
    "crash",
    "paging",
    "p0",
)
_MEDIUM_SIGNALS: tuple[str, ...] = (
    "latency",
    "slow",
    "timeout",
    "regression",
    "elevated",
    "spike",
    "p1",
)


def _guess_severity(message: str) -> str:
    """Return a coarse severity label for a request message.

    The stub is deterministic so the example boots even when the
    GitHub MCP server is unhealthy; it is **not** a replacement for a
    real triage classifier.
    """
    text = message.lower()
    if any(signal in text for signal in _HIGH_SIGNALS):
        return "high"
    if any(signal in text for signal in _MEDIUM_SIGNALS):
        return "medium"
    return "low"


@Agent(
    model="claude-opus-4-7",
    system=(
        "You are an engineering on-call assistant. "
        "For every incoming request, call summarize_request first to "
        "normalise the user's report. Then, when the GitHub MCP tools "
        "are available, use them to look up related issues, recent "
        "pull requests, or commits in the team's repositories. "
        "Propose a concise triage: state the severity (low / medium / "
        "high), reference at least one supporting GitHub artifact when "
        "you find one, and end with the next concrete step."
    ),
    fallback="claude-haiku-4-5",
    integrations=[GitHubMCP],
)
class OnCallAgent:
    """The on-call assistant."""

    @Tool
    async def summarize_request(self, message: str) -> dict[str, str]:
        """Normalise an incoming on-call request.

        Returns a small structured summary the model can read back:
        a service hint (``service``) extracted from common URL-path
        signals (``/events``, ``/api/...``) and a coarse severity
        label (``severity``: ``low`` / ``medium`` / ``high``) keyed
        off a short list of well-known prod-incident phrases.

        Production deployments would replace this with a real
        classifier — see the example README for the contract.
        """
        service = "unknown"
        text = message.lower()
        # Cheap, deterministic service extraction. A real classifier
        # would consult a service catalogue.
        if "/events" in text:
            service = "events"
        elif "/api/" in text:
            service = "api"
        elif "/checkout" in text:
            service = "checkout"
        elif "/auth" in text or "login" in text:
            service = "auth"

        return {
            "service": service,
            "severity": _guess_severity(message),
            "summary": message.strip(),
        }

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[str]:
        """Stream a triage answer for the request over SSE."""
        # ``self.stream`` is injected by ``@Agent`` at decoration
        # time; static analysers cannot see the attribute, so we
        # silence the missing-attribute warning here. Same pattern as
        # ``examples/support-agent/src/support_agent/agents/support.py``.
        async for chunk in self.stream(body.message):  # type: ignore[attr-defined]
            yield chunk
