"""Step 3 — the ``SupportTeam`` workflow and its specialists.

Mirrors the code blocks in
[`docs/tutorial/step-3-team.md`](../../../../docs/tutorial/step-3-team.md):

- Three specialists (``Triage`` / ``Billing`` / ``Technical``) — two of them
  on Opus, the cheap classifier on Haiku.
- One ``@MCP`` block (``Integrations``) declaring the GitHub MCP server.
- One ``@Workflow`` (``SupportTeam``) wired with an LLM ``coordinator=``,
  the three specialists, and the integrations.
- One ``@Stream("/chat")`` handler that keeps the wire contract identical
  to Step 1 — clients do not need to know the team grew under them.

Drift note — observability:
    Neither ``@Agent`` nor ``@Workflow`` accept ``trace=`` in v0.1; OTel
    instrumentation is always-on and cheap when no SDK is installed.

Drift note — ``@MCP`` runtime requirements:
    Connecting to the GitHub MCP server requires the optional extra
    ``ajolopy[mcp]`` and a ``GITHUB_TOKEN`` env var. Without those, the
    decorator still validates at import time and the workflow still boots;
    the server simply stays unhealthy and its tools are not advertised.
"""

# NOTE: ``AsyncGenerator`` MUST be imported at runtime (not under
# ``if TYPE_CHECKING:``). Python 3.14 + PEP 649 defers annotation
# evaluation until something calls ``get_annotations()`` /
# ``inspect.signature()``; the framework's ``@Stream`` mount path does
# exactly that on the ``handle`` handler below to wire up the route.
# If this symbol is only visible to static analysers, the mount step
# explodes with ``NameError: name 'AsyncGenerator' is not defined`` at
# server boot — a regression that first surfaced post-AJ-87.
from collections.abc import AsyncGenerator  # noqa: TC003
from typing import Annotated, Any

from pydantic import BaseModel

from ajolopy import MCP, Agent, Stream, Tool, Workflow
from ajolopy.http import Body


@Agent(
    model="claude-haiku-4-5",
    system=(
        "You triage incoming support messages. "
        "Classify each message into exactly one of: billing, technical, general."
    ),
)
class Triage:
    """Cheap, fast classifier that decides who answers."""


@Agent(
    model="claude-opus-4-7",
    system="You handle billing: refunds, invoices, subscriptions.",
)
class Billing:
    """Refunds, invoices, subscriptions."""

    @Tool
    async def issue_refund(self, order_id: str, reason: str) -> dict[str, str]:
        """Issue a refund for an order.

        Production billing would call into Stripe / the internal ledger.
        The stub returns a deterministic answer so the example boots
        without any external dependency.
        """
        return {"order_id": order_id, "reason": reason, "status": "ok"}


@Agent(
    model="claude-opus-4-7",
    system="You handle technical issues: bugs, errors, integration help.",
)
class Technical:
    """Bugs, errors, integration help."""


@MCP(
    servers={
        "github": "stdio:npx -y @modelcontextprotocol/server-github",
    },
    auth={
        "github": {"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}},
    },
)
class Integrations:
    """External MCP servers shared across the support team.

    The class body is intentionally empty — ``@MCP`` is a declaration, not
    a runtime. Tools are discovered at factory boot and injected wherever
    a class lists ``integrations=[Integrations]``.
    """


class ChatRequest(BaseModel):
    """Same wire shape as Step 1 — clients do not need to know about the team.

    The optional ``user_id`` propagates as a context kwarg into the
    workflow's ``stream(...)`` call and is observable on the spans the
    framework emits per case.
    """

    message: str
    user_id: str | None = None


@Workflow(
    coordinator="claude-opus-4-7",
    agents=[Triage, Billing, Technical],
    integrations=[Integrations],
    max_steps=8,
)
class SupportTeam:
    """Route a support request to the right specialist."""

    @Stream("/chat")
    async def handle(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[dict[str, Any]]:
        """Stream the team's response as SSE JSON events.

        ``self.stream(...)`` yields ``WorkflowEvent`` dicts (``handoff``,
        ``agent_result``, ``token``, ``done``) instead of raw strings —
        the framework serialises each one as a separate SSE ``data:``
        line. Forward-compatibly, clients must ignore unknown event
        ``type`` values.
        """
        # ``self.stream`` is injected by ``@Workflow`` at decoration time.
        async for event in self.stream(  # type: ignore[attr-defined]
            body.message, user_id=body.user_id
        ):
            yield event
