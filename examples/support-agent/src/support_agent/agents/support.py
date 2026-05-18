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

# NOTE: ``AsyncGenerator`` MUST be imported at runtime (not under
# ``if TYPE_CHECKING:``). Python 3.14 + PEP 649 defers annotation
# evaluation until something calls ``get_annotations()`` /
# ``inspect.signature()``; the framework's ``@Stream`` mount path does
# exactly that on the ``respond`` handler below to wire up the route.
# If this symbol is only visible to static analysers, the mount step
# explodes with ``NameError: name 'AsyncGenerator' is not defined`` at
# server boot — a regression that first surfaced post-AJ-87.
from collections.abc import AsyncGenerator  # noqa: TC003
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body


class ChatRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint."""

    message: str


@Agent(
    model="claude-opus-4-7",
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
