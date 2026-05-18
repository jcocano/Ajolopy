# Langfuse

[Langfuse](https://langfuse.com) is the AI-native observability backend with
the lightest-touch setup of the five recipes. It speaks OTLP natively, so no
SDK swap is required — point `OTEL_EXPORTER_OTLP_ENDPOINT` at the Langfuse
endpoint, set the auth header, and your `chat`, `execute_tool`,
`agent.invoke`, and `workflow.invoke` spans show up as LLM traces with
prompts, completions, models, tokens, and cost on the same screen.

## What you get

A live AI-specific trace view: every `@Agent` invocation surfaces as a
trace, every LLM call as a generation with its model + token usage, every
tool dispatch as a child span, every fallback retry as a sibling
generation. The framework already emits `gen_ai.cost_usd` per `chat` span
via the [pricing catalog](../../reference/agent.md), so Langfuse's
cost-by-user / cost-by-model dashboards work without any extra wiring. The
root `agent.invoke` span carries `ajolopy.cost_usd.total` so a single trace
row tells you the request's blended cost.

## Prerequisites

- A [Langfuse Cloud](https://cloud.langfuse.com) account (free tier
  available) or a self-hosted Langfuse instance.
- A project with a **Public Key** and a **Secret Key** (Project Settings →
  API Keys).
- The OTLP endpoint of your project — `https://cloud.langfuse.com/api/public/otel`
  for Langfuse Cloud (EU), `https://us.cloud.langfuse.com/api/public/otel`
  for Langfuse Cloud (US), or `<self-host>/api/public/otel` if you are
  self-hosting.

## Install

```bash
uv pip install "ajolopy[otel]"
```

Langfuse needs no backend-specific SDK — it consumes the same OTLP/HTTP
exporter that the `otel` extra installs.

## Wire it in

The OTLP `Authorization` header uses **Basic** auth with the public + secret
keys, base64-encoded. Build the header once and paste it into `.env`:

```bash
# Generate the value once (replace pk-... and sk-... with your keys).
printf 'pk-lf-...:sk-lf-...' | base64
# -> cGstbGYtLi4uOnNrLWxmLS4uLg==
```

Then:

```env
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20cGstbGYtLi4uOnNrLWxmLS4uLg==
OTEL_SERVICE_NAME=my-agent
```

That is the whole bootstrap. When `AjolopyFactory.create()` runs, it calls
`setup_tracing_from_env()`, sees the endpoint, installs a `TracerProvider`
with the OTLP exporter, and every span the framework emits flows to
Langfuse from the next request onward. No code change.

!!! tip "URL-encode the header value"
    The OTLP env var parser splits on `,`, so an unencoded space breaks it.
    `Basic` and the base64 string are joined with `%20`. URL-encode any
    other special characters the same way.

If you prefer to set things up in code (for example to pin a custom
`Resource`, run multi-exporter, or load the keys from a vault), build your
own `TracerProvider` and install it **before** `AjolopyFactory.create()`
runs. The framework detects the existing provider and leaves it alone:

```python
# bootstrap.py
import os
from base64 import b64encode

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ajolopy import AjolopyFactory

from my_agent.app_module import AppModule


def _install_langfuse_provider() -> None:
    creds = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
    header = "Basic " + b64encode(creds.encode()).decode()
    exporter = OTLPSpanExporter(
        endpoint="https://cloud.langfuse.com/api/public/otel/v1/traces",
        headers={"Authorization": header},
    )
    provider = TracerProvider(resource=Resource.create({"service.name": "my-agent"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


async def bootstrap() -> None:
    _install_langfuse_provider()
    await AjolopyFactory.create(AppModule)
```

## What you should see

After a single `curl` against your `@Stream` endpoint:

- **Traces** view: one trace per request, named `agent.invoke <YourAgent>`,
  with one or more `chat <model>` child spans (one per LLM call in the tool
  loop). Tool calls land as `execute_tool <tool_name>` grandchildren.
- **Generations** view: each `chat` span surfaces as a generation row with
  the model name, latency, input / output tokens, and cost (USD).
- **Cost** dashboard: `gen_ai.cost_usd` aggregated by model, by trace, and
  by user when you attach `user_id` to a span (see Gotchas).

## Gotchas

- **Privacy.** Prompt and completion text are **not** exported by default.
  Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` to opt in;
  Langfuse will then show the messages on the generation detail view.
- **Auth header format.** It is `Basic <base64(pk:sk)>` — not `Bearer`. A
  wrong scheme returns `401` from the OTLP endpoint with no exported spans
  (and the framework logs an export failure once per minute).
- **`user_id` / `session_id`.** Langfuse keys its per-user dashboards off
  custom span attributes. Set them via the documented OTel
  [Baggage](https://opentelemetry.io/docs/concepts/signals/baggage/) or
  `Span.set_attribute("user.id", ...)` inside your code; the framework
  does not infer them.
- **Endpoint region.** `cloud.langfuse.com` is the EU region; the US
  region is `us.cloud.langfuse.com`. Pick the one your project lives in,
  otherwise the upload silently lands in the wrong region.
- **Cost catalog drift.** `gen_ai.cost_usd` comes from the embedded
  LiteLLM snapshot. For brand-new / custom / on-prem models, register
  overrides via `AjolopyFactory.create(..., pricing_overrides=...)` — see
  [`@Agent`](../../reference/agent.md).

## See also

- [`@Agent` reference](../../reference/agent.md) — the primitive whose
  spans land in Langfuse.
- [Recipes overview](index.md) — pick a different backend.
- [Install — `otel` extra](../../install.md#optional-extras).
- [Langfuse docs · OpenTelemetry](https://langfuse.com/docs/opentelemetry/get-started)
- [OpenTelemetry spec · GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
