# Step 1 — Hello to prod

> "Twelve lines that hide a hundred-and-fifty."

The [Quickstart](../quickstart.md) shipped a bare-bones agent. In this step
you graduate it to a **production-ready** version — same length, but with
the four knobs that separate a demo from a real service: distributed
tracing, a cross-model fallback, the function-calling loop, and a streaming
endpoint that survives network hiccups.

## What you build

A `Support` agent that answers `POST /chat` over Server-Sent Events,
falls back to a cheaper model on provider failure, looks up real order
state via a tool, and emits one OpenTelemetry span per call.

## The code

Open `src/acme_support/agents/support.py` (replace `acme_support` with your
package name) and replace its contents with:

```python
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool


class ChatRequest(BaseModel):
    """Payload accepted by the /chat endpoint."""

    message: str


@Agent(
    model="claude-sonnet-4-7",
    system="You are Acme Support. Be concise, friendly, and accurate.",
    trace=True,
    fallback="claude-haiku-4-5",
)
class Support:
    """The on-call assistant."""

    @Tool
    async def lookup_order(self, order_id: str) -> dict[str, str]:
        """Look up an order's current state by id."""
        return {"order_id": order_id, "status": "in_transit", "eta": "tomorrow"}

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]):
        """Stream a reply for the user's message over SSE."""
        async for chunk in self.stream(body.message):
            yield chunk
```

You also need to add the `Body` import — it sits on `ajolopy.http`:

```python
from ajolopy.http import Body
```

## What every kwarg buys you

Twelve real lines (without imports). Each token has a job:

| Token                                | What it does                                                                                       | What it replaces                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `@Agent(model="claude-sonnet-4-7")`  | Picks the provider (Anthropic) by prefix, validates the model, wires the SDK at boot.              | ~5 lines of SDK init + provider selection logic.                                 |
| `system="You are Acme Support..."`   | Sets the system prompt once. Static strings unlock prompt caching when you opt in with `cache=`.   | A `messages=[{"role": "system", ...}]` dance on every call.                      |
| `trace=True`                         | Emits one OpenTelemetry span per `run` / `stream` with `gen_ai.*` attributes and `gen_ai.cost_usd`. | ~20 lines: tracer setup, manual span boundaries, token/cost accounting wrappers. |
| `fallback="claude-haiku-4-5"`        | On retriable provider failure, transparently retries on the named model.                            | ~40 lines: retry policy, alternate client, error classification.                  |
| `@Tool` + Python type hints          | Synthesises the JSON Schema, registers the tool, runs the function-calling loop.                    | ~40 lines: hand-written schema, `tool_use` reentry, `tool_result` plumbing.       |
| `@Stream("/chat")`                   | Mounts the method as an SSE endpoint with heartbeats and disconnect cancellation.                   | ~30 lines: Starlette streaming response, keepalives, cancel-on-disconnect.        |
| `Annotated[ChatRequest, Body()]`     | Validates the request body against a Pydantic model before invoking your handler.                   | Manual `await request.json()` plus a hand-rolled validator.                       |

**Twelve lines + one dependency** replaces roughly **150 lines + four
dependencies** in the wild today.

!!! note "Why a real-typed body, not `message: str`?"
    The [Quickstart](../quickstart.md) used `message: str` as a teaching
    convenience. In a real service you almost always want a Pydantic model
    on the wire — it gives you input validation, OpenAPI schema, and a
    stable shape clients can rely on. `Annotated[..., Body()]` is the
    `@Stream` pattern documented in [`@Stream` reference](../reference/stream.md).

## Run it

The `ajolopy dev` server from the Quickstart still works — just relaunch
it:

```bash
ajolopy dev
```

In a second terminal hit the endpoint:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is order 4392? Use the tool."}'
```

You should see the response **stream back token by token** with a
`function_call → tool_result → final_text` round trip in your dev-server
logs. The agent calls `lookup_order("4392")`, gets your stub answer, and
folds it into the streamed reply.

## See the production behaviour at work

The two production knobs you added are easiest to verify by inducing the
condition they protect against.

### Env validation

The framework fails fast when a required variable is missing. Temporarily
remove your API key and restart:

```bash
unset ANTHROPIC_API_KEY
ajolopy dev
```

`ajolopy dev` refuses to boot and points at the missing variable. Put the
key back, the server starts. That is **knob #1** from the
[seven production primitives](../index.md): no more 2 a.m. discovery of an
unset secret in staging.

### Fallback

To see the fallback in action, point `model=` at a temporarily-misnamed
Anthropic model and watch the span emit a `gen_ai.fallback.used` attribute
with the alternative model on retry. (Production fallbacks fire on
*retriable* errors — 5xx, rate limit, timeout — not on a missing model,
but the OTel attribute is the same.)

## What just happened

You have a `Support` agent that:

1. Validates its provider env var **before** accepting traffic.
2. Streams responses over SSE with heartbeats and disconnect cancellation.
3. Runs a tool-calling loop without any JSON Schema you had to write.
4. Falls back to `claude-haiku-4-5` automatically if Sonnet returns a
   retriable error.
5. Emits one OpenTelemetry span per request — ready to land in
   [Langfuse / Sentry / Grafana / Honeycomb / Datadog](../next-steps.md#put-it-in-production)
   the moment you wire an exporter.

That is **production from day one**. Twelve lines, one dependency. No
manual tool-calling loop, no SSE plumbing, no retry policy, no env-var
debugging at deploy time.

## What's next

In [Step 2 — Evals](step-2-evals.md) you keep this same `Support` class
and add the safety net that catches the moment a prompt change, a model
upgrade, or a tool tweak silently regresses your quality.
