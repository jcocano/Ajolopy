# Sentry

[Sentry](https://sentry.io) is the option when you already pay for Sentry on
the frontend (or for the rest of your backend) and want LLM traces in the
same project, next to errors and performance traces. Sentry's
[AI Monitoring](https://docs.sentry.io/product/insights/agents/) product
consumes OTLP and renders `gen_ai.*` spans as agent invocations, LLM calls,
and tool dispatches — no separate "AI dashboard" to administer.

## What you get

Every `@Agent` invocation lands as a Sentry transaction whose spans mirror
the AJ-28 tree: `agent.invoke {Name}` → `chat {model}` →
`execute_tool {tool}`. The AI Monitoring view surfaces token usage and
`gen_ai.cost_usd` per call; tool errors and unhandled provider exceptions
appear in the **Issues** stream because the runtime records them via
`Span.record_exception` + `Status(StatusCode.ERROR)`. Errors and AI traces
share one project, one issue stream, one alerting backend.

## Prerequisites

- A Sentry account and a project. AI Monitoring is part of the Performance /
  Insights tier — confirm it is enabled for your org.
- The project's **DSN** (Project Settings → Client Keys).
- The OTLP endpoint for your region:
  - US: `https://otel-pipeline.sentry.io/v1/traces`
  - EU: `https://otel-pipeline.de.sentry.io/v1/traces`
- An `x-sentry-auth` header derived from the DSN (see Wire it in).

## Install

```bash
uv pip install "ajolopy[otel]"
```

No backend-specific SDK is required for the OTLP path. If you also want
the classic Sentry SDK error capture in the same process (separate from
the OTLP exporter), `uv pip install sentry-sdk` alongside.

## Wire it in

Sentry's OTLP endpoint authenticates with `x-sentry-auth`. The header value
is the **public key** segment of the DSN, prefixed by
`sentry_key=`:

```env
# .env
# DSN format: https://<public_key>@o<org>.ingest.sentry.io/<project_id>
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://otel-pipeline.sentry.io/v1/traces
OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-sentry-auth=sentry_key=<public_key>
OTEL_SERVICE_NAME=my-agent
```

`AjolopyFactory.create()` calls `setup_tracing_from_env()`; the framework
installs a `TracerProvider` with the OTLP/HTTP exporter and every span the
runtime emits flows to Sentry.

!!! tip "Why `OTEL_EXPORTER_OTLP_TRACES_*`?"
    Sentry's OTLP ingest is **traces-only** today. Using the
    traces-specific env vars instead of the generic
    `OTEL_EXPORTER_OTLP_ENDPOINT` makes it explicit and leaves the door
    open to point logs / metrics at a different backend later.

If you also want classic Sentry SDK behaviour (error breadcrumbs,
release tracking, native source-maps) in the same process, initialise the
Sentry SDK *before* `AjolopyFactory.create()`. Keep the SDK's tracing
**off** (`traces_sample_rate=0.0`) so it does not stomp the
`TracerProvider` AJ-28 installs:

```python
# bootstrap.py
import os

import sentry_sdk

from ajolopy import AjolopyFactory

from my_agent.app_module import AppModule


async def bootstrap() -> None:
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        traces_sample_rate=0.0,   # let the OTLP exporter own tracing
        send_default_pii=False,
    )
    await AjolopyFactory.create(AppModule)
```

## What you should see

- **Performance** → **AI Monitoring**: each request shows up as an agent
  invocation row with model, latency, token totals, and cost.
- **Trace view**: drill into a request to see the `chat` + `execute_tool`
  span tree, with finish reasons, tool names, and call ids.
- **Issues**: tool exceptions and `LLMProviderError` retries appear as
  grouped issues — the `chat` span that raised carries
  `Status(StatusCode.ERROR)` and an exception breadcrumb.
- **Alerts**: build a metric alert on `gen_ai.cost_usd` (sum) per
  release / environment to catch bill spikes.

## Gotchas

- **Privacy.** `gen_ai.prompt` / `gen_ai.completion` are off by default.
  Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` to opt in
  per request — and double-check Sentry's
  [PII scrubbing](https://docs.sentry.io/data-management-concepts/scrubbing/)
  rules before doing so on prod.
- **Two ingest paths.** If you also init `sentry_sdk` and leave
  `traces_sample_rate>0`, the SDK installs its own `TracerProvider` and
  the OTLP exporter never gets a chance. Keep one writer; turn the SDK's
  tracing off when using OTLP.
- **Span attribute cap.** Sentry truncates string attributes at ~8 KB.
  With content capture enabled, long prompts get truncated server-side —
  this affects the UI only, not your bill or scoring.
- **DSN vs OTLP endpoint.** The Sentry DSN is *not* the OTLP endpoint.
  Build the `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` from the documented
  region URL above; do not point it at the DSN host.
- **OTLP ingest is gated.** Confirm OTLP ingest is enabled for your
  Sentry org — older / self-hosted Sentry installs may not have the
  `/v1/traces` endpoint. If exports 404, you need the Sentry team to
  enable AI Monitoring on the project.

## See also

- [`@Agent` reference](../../reference/agent.md) — the primitive whose
  spans land in Sentry.
- [Recipes overview](index.md) — pick a different backend.
- [Install — `otel` extra](../../install.md#optional-extras).
- [Sentry docs · OpenTelemetry support](https://docs.sentry.io/platforms/python/tracing/instrumentation/opentelemetry/).
- [Sentry docs · AI Monitoring](https://docs.sentry.io/product/insights/agents/).
