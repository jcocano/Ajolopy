# Honeycomb

[Honeycomb](https://www.honeycomb.io) is the option when you want to slice
agent traces by arbitrary, high-cardinality attributes (`user_id`,
`tenant_id`, `gen_ai.tool.call.id`, `gen_ai.request.model`) and let
**BubbleUp** automatically tell you which dimension makes the outlier slow
or expensive. Honeycomb consumes plain OTLP/HTTP — no SDK swap.

## What you get

- Every `agent.invoke {Name}` root span lands as a trace; every `chat`
  child span as a child event with the full `gen_ai.*` attribute bag and
  `gen_ai.cost_usd`.
- **BubbleUp** on a slow / expensive trace shows which models, agents,
  tools, or users are over-represented in the outlier slice.
- **Triggers** on a derived column (e.g. `SUM(gen_ai.cost_usd)`) page you
  when monthly cost crosses a threshold.
- **Boards** combining latency, token usage, and cost per
  `gen_ai.request.model`, with the wedge user's "who spent $4k this
  month" answerable as one query against `user.id` (you set it in your
  app code) and `gen_ai.cost_usd` (the framework emits it).

## Prerequisites

- A Honeycomb account and an environment (e.g. `production`).
- An **Ingest API key** for that environment
  (Environment settings → API keys). The key must have the
  `Send Events` permission.
- The OTLP endpoint for your region:
  - US: `https://api.honeycomb.io`
  - EU: `https://api.eu1.honeycomb.io`

## Install

```bash
uv pip install "ajolopy[otel]"
```

Honeycomb consumes OTLP directly; no Honeycomb-specific Python SDK is
needed.

## Wire it in

Honeycomb authenticates with the `x-honeycomb-team` header:

```env
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<your-ingest-api-key>
OTEL_SERVICE_NAME=my-agent
```

`AjolopyFactory.create()` runs `setup_tracing_from_env()`, installs a
`TracerProvider` with the OTLP HTTP exporter against
`https://api.honeycomb.io/v1/traces`, and every span starts flowing. The
`OTEL_SERVICE_NAME` becomes Honeycomb's **dataset** name.

!!! tip "Classic vs Environments-and-Services"
    Honeycomb's modern accounts split traces into per-service datasets
    automatically using `service.name`. On legacy Classic accounts, the
    dataset is fixed and you may need to set
    `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<key>,x-honeycomb-dataset=<name>`
    to land on the right dataset. Most accounts are on the new model;
    confirm by checking whether your sidebar shows **Environments**.

### Power-user: enrichment processor

To stamp every span with the requesting `user.id` / `tenant.id` (so
BubbleUp can find them), build your own `TracerProvider` and add a
`SpanProcessor` that reads those values from contextvars. Install it
before `AjolopyFactory.create()` — the framework detects the existing
provider and skips its own setup:

```python
# bootstrap.py
import os
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

from ajolopy import AjolopyFactory

from my_agent.app_module import AppModule


_USER_ID: ContextVar[str | None] = ContextVar("user_id", default=None)


class UserIdAttachingProcessor(SpanProcessor):
    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        user_id = _USER_ID.get()
        if user_id is not None:
            span.set_attribute("user.id", user_id)


def _install_honeycomb_provider() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": "my-agent"}))
    provider.add_span_processor(UserIdAttachingProcessor())
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint="https://api.honeycomb.io/v1/traces",
                headers={"x-honeycomb-team": os.environ["HONEYCOMB_API_KEY"]},
            )
        )
    )
    trace.set_tracer_provider(provider)


async def bootstrap() -> None:
    _install_honeycomb_provider()
    await AjolopyFactory.create(AppModule)
```

Set `_USER_ID` from your auth middleware so every span emitted inside the
request gets the attribute automatically.

## What you should see

- **Home** → your dataset shows traces grouped by `service.name`. Drill
  into a trace to see the `agent.invoke` / `chat` / `execute_tool` tree.
- **Query** view, group by `gen_ai.request.model`, `HEATMAP(duration_ms)`
  → per-model latency distribution.
- **Query** view, group by `user.id` (when you stamp it), aggregate
  `SUM(gen_ai.cost_usd)` → cost-per-user.
- **BubbleUp** on a slow-trace selection → "which dimension is
  over-represented in the slow slice?" answers usually point at a model,
  a tool, or a user.
- **Triggers** on `SUM(gen_ai.cost_usd)` over `last 24h` to alert on cost
  spikes.

## Gotchas

- **Privacy.** `gen_ai.prompt` / `gen_ai.completion` are off by default.
  Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` to opt
  in. Honeycomb charges per event — large prompt strings still ingest
  fine, but consider sampling content capture rather than running it
  always-on.
- **Event quotas.** Honeycomb plans cap events per month. A busy tool
  loop can emit dozens of spans per request; set a head sampler
  (`TraceIdRatioBased`) at the SDK level if you cross the cap.
- **Attribute renaming.** Honeycomb keeps the `gen_ai.*` namespace
  verbatim — no auto-mapping to Honeycomb-specific names. Use the dotted
  names in queries (`gen_ai.usage.input_tokens`, etc.).
- **API key scope.** The ingest key is per-environment. Using a "Classic"
  key against a modern Environments account or vice-versa silently
  drops events. Confirm the key matches the environment you intend.
- **High-cardinality cost.** Honeycomb's pricing scales with event count,
  not cardinality — but BubbleUp's analysis cost on huge result sets can
  grow if you stamp truly per-request unique attributes (e.g. UUID4
  request ids) on every event. Stamp them, but use Boards / Queries to
  aggregate them rather than browsing them individually.

## See also

- [`@Agent` reference](../../reference/agent.md) — the primitive whose
  spans land in Honeycomb.
- [Recipes overview](index.md) — pick a different backend.
- [Install — `otel` extra](../../install.md#optional-extras).
- [Honeycomb docs · OpenTelemetry](https://docs.honeycomb.io/send-data/opentelemetry/).
- [Honeycomb docs · BubbleUp (Identify Outliers)](https://docs.honeycomb.io/investigate/analyze/identify-outliers).
