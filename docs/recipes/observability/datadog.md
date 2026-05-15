# Datadog

[Datadog](https://www.datadoghq.com) is the option when the rest of the
company already runs on Datadog, or when corp pays the bill and "one pane
of glass for infra + APM + logs" is the brief. Datadog ingests OTLP/HTTP
directly via its **OTLP intake**, so the same `setup_tracing_from_env()`
path that lights up Langfuse / Honeycomb works here — only the endpoint and
auth header change. The `gen_ai.*` attributes flow through unchanged and
appear under Datadog's **LLM Observability** product.

## What you get

- Every `agent.invoke {Name}` root span lands as an APM trace with the AJ-28
  child span tree (`chat {model}` → `execute_tool {tool}`). Tools that
  raise surface as errored spans (`Status = error` + exception event).
- **LLM Observability** view renders `chat` spans as model calls with token
  usage, latency, and `gen_ai.cost_usd`. Per-model and per-agent
  dashboards are built-in.
- **Cost** rolled up across spans by tag (model, agent, environment, user)
  so you can answer "who spent $4k this month" without exporting to a
  spreadsheet.
- **Errors** stream picks up tool exceptions and provider failures because
  the framework records them on the span before re-raising.

## Prerequisites

- A Datadog account.
- A Datadog **API key** (Organization Settings → API Keys).
- Your Datadog site:
  - US1: `https://api.datadoghq.com`
  - US3: `https://api.us3.datadoghq.com`
  - US5: `https://api.us5.datadoghq.com`
  - EU: `https://api.datadoghq.eu`
  - AP1: `https://api.ap1.datadoghq.com`
- LLM Observability enabled for your org (Settings → Subscriptions). The
  OTLP intake itself works without it; LLM-specific dashboards need it.

## Install

```bash
uv pip install "ajolopy[otel]"
```

The OTLP intake consumes the same OTLP HTTP exporter the `otel` extra
installs. The classic `ddtrace` SDK is **not** required for this recipe; if
you also want runtime / profiling / live processes, install
`uv pip install ddtrace` and run the app via `ddtrace-run` — keep
`DD_TRACE_OTEL_ENABLED=true` so the SDK does not stomp the OTLP exporter.

## Wire it in

Datadog's OTLP intake authenticates with `DD-API-KEY`:

```env
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.datadoghq.com
OTEL_EXPORTER_OTLP_HEADERS=DD-API-KEY=<your-datadog-api-key>
OTEL_SERVICE_NAME=my-agent
OTEL_RESOURCE_ATTRIBUTES=env=production,service.version=1.0.0
```

`AjolopyFactory.create()` runs `setup_tracing_from_env()`; the framework
installs a `TracerProvider` against
`https://api.datadoghq.com/api/intake/otlp/v1/traces` (the OTLP exporter
appends `/v1/traces` to the base endpoint) and every span starts flowing.
`OTEL_SERVICE_NAME` becomes Datadog's `service` tag;
`OTEL_RESOURCE_ATTRIBUTES` translates to additional resource tags like
`env` and `version` — those are the columns the per-environment dashboards
key off.

!!! warning "Pick the right site"
    Datadog's OTLP endpoint is **regional**. Pointing US1 credentials at
    the EU endpoint (or vice versa) silently returns `403` and no spans
    land. Confirm your site from
    `Account → Personal Settings → Default Site` before pasting.

### Power-user: agent-side OTLP intake

If you already run the **Datadog Agent** on each host, send OTLP at the
agent (port `4318`) instead of the API. The agent buffers, retries, and
adds host-level resource tags automatically:

```env
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=my-agent
OTEL_RESOURCE_ATTRIBUTES=env=production
```

No API key needed in the app — the agent owns auth. This is the
recommended shape for Kubernetes / VM deployments where the agent is a
DaemonSet / sidecar.

### Power-user: custom provider

For dual exporters (Datadog + a regional Tempo, say) or a tuned
`BatchSpanProcessor` config, build your own `TracerProvider` and install
it before `AjolopyFactory.create()`. The framework detects the existing
provider and skips its own setup:

```python
# bootstrap.py
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ajolopy import AjolopyFactory

from my_agent.app_module import AppModule


def _install_datadog_provider() -> None:
    resource = Resource.create(
        {
            "service.name": "my-agent",
            "deployment.environment": "production",
            "service.version": os.environ.get("APP_VERSION", "dev"),
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint="https://api.datadoghq.com/api/intake/otlp/v1/traces",
                headers={"DD-API-KEY": os.environ["DD_API_KEY"]},
            )
        )
    )
    trace.set_tracer_provider(provider)


async def bootstrap() -> None:
    _install_datadog_provider()
    await AjolopyFactory.create(AppModule)
```

## What you should see

- **APM** → **Traces**: traces tagged `service:my-agent` with the agent
  invoke → chat → execute_tool tree.
- **APM** → **LLM Observability**: model calls with tokens, latency, and
  `gen_ai.cost_usd` per call; per-model and per-agent breakdowns
  pre-built.
- **Dashboards**: build a widget on
  `sum:trace.agent.invoke.cost_usd_total{*} by {agent}` to see
  cost-per-agent rolling up from `ajolopy.cost_usd.total`.
- **Monitors**: anomaly / threshold monitors on
  `gen_ai.cost_usd` aggregations to page on bill spikes.
- **Errors**: tool exceptions and provider failures appear on the trace
  with the standard OTel error markers (Datadog renders them in red).

## Gotchas

- **Privacy.** `gen_ai.prompt` / `gen_ai.completion` are off by default.
  Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` to opt
  in — and review
  [Datadog's Sensitive Data Scanner](https://docs.datadoghq.com/sensitive_data_scanner/)
  rules before doing so. Datadog will index the text and bill against
  ingested bytes.
- **Custom metric cardinality.** Tags like `user_id` /
  `gen_ai.tool.call.id` are *very* high-cardinality. Keep them in trace
  attributes (queryable via APM); do not promote them to Datadog custom
  metrics — your bill will spike.
- **Site routing.** US1, US3, US5, EU, AP1 are separate environments.
  Confirm `OTEL_EXPORTER_OTLP_ENDPOINT` matches your account's site or
  spans silently 403 / drop.
- **`ddtrace` vs OTLP.** If you also run `ddtrace-run`, leave
  `DD_TRACE_OTEL_ENABLED=true` so the SDK adopts the OTLP-installed
  `TracerProvider`. With the default off, `ddtrace` installs its own
  provider and the framework's OTLP exporter never gets called.
- **Endpoint path quirk.** The intake URL is
  `<site>/api/intake/otlp/v1/traces`. With
  `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.datadoghq.com`, the exporter
  appends `/v1/traces` automatically — that is correct for the agent
  intake but **wrong** for the API intake. If you target the API
  directly, set the full URL (or use
  `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://api.datadoghq.com/api/intake/otlp/v1/traces`).
- **Cost catalog drift.** `gen_ai.cost_usd` comes from the embedded
  LiteLLM snapshot. For brand-new / custom / on-prem models, register
  overrides via `AjolopyFactory.create(..., pricing_overrides=...)` —
  see [`@Agent`](../../reference/agent.md).

## See also

- [`@Agent` reference](../../reference/agent.md) — the primitive whose
  spans land in Datadog.
- [Recipes overview](index.md) — pick a different backend.
- [Install — `otel` extra](../../install.md#optional-extras).
- [Datadog docs · Send OTLP traces](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest/).
- [Datadog docs · LLM Observability](https://docs.datadoghq.com/llm_observability/).
