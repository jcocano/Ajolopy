"""Step 1 — the single ``Support`` agent.

Mirrors the code block in
[`docs/tutorial/step-1-hello.md`](../../../../docs/tutorial/step-1-hello.md):
one ``@Agent`` + one ``@Tool`` + one ``@Stream`` endpoint, with a Pydantic
``ChatRequest`` model on the wire and a model-level fallback.

Drift note — observability:
    The tutorial mentions ``trace=True`` as a knob; in the v0.1 source the
    kwarg has been removed and OpenTelemetry instrumentation is always-on
    (the spans are cheap no-ops without ``ajolopy[otel]`` installed).
    Backend selection happens at the SDK layer via standard OTel env vars
    (``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``). See the
    ``@Agent`` reference page for the canonical list of supported kwargs.
"""

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class ChatRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint."""

    message: str


@Agent(
    model="claude-sonnet-4-7",
    system="You are Acme Support. Be concise, friendly, and accurate.",
    fallback="claude-haiku-4-5",
)
class Support:
    """The on-call assistant."""

    @Tool
    async def lookup_order(self, order_id: str) -> dict[str, str]:
        """Look up an order's current state by id.

        Production support would call into the order-tracking service here.
        The stub returns a deterministic answer so the example boots
        without any external dependency.
        """
        return {"order_id": order_id, "status": "in_transit", "eta": "tomorrow"}

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[str]:
        """Stream a reply for the user's message over SSE."""
        # ``self.stream`` is injected by ``@Agent`` at decoration time;
        # static analysers cannot see the attribute, so we silence the
        # missing-attribute warning here. Same pattern as the framework's
        # own composability tests.
        async for chunk in self.stream(body.message):  # type: ignore[attr-defined]
            yield chunk
