# Grafana stack

The Grafana stack — **Tempo** for traces, **Loki** for logs, **Prometheus**
for metrics, **Grafana** for the UI — is the option when you self-host (data
residency, cost control, "we already run Grafana"). The same configuration
also works against **Grafana Cloud**: only the endpoint and auth change. The
framework emits the same `gen_ai.*` shape either way.

## What you get

- **Tempo**: distributed traces. `agent.invoke {Name}` →
  `chat {model}` → `execute_tool {tool}` spans, with `gen_ai.*` attributes,
  `gen_ai.cost_usd` per call, and `ajolopy.cost_usd.total` on the root.
- **Loki**: structured logs (when you also wire structlog through OTLP or a
  Loki driver — out of scope for this page; see the
  [`@Agent` reference](../../reference/agent.md) for the structlog hook).
- **Grafana**: dashboards over the traces (TraceQL) and over the
  numeric attributes derived from them (Tempo metrics generator or
  Prometheus recording rules on `gen_ai.cost_usd` / `gen_ai.usage.*`).

Self-hosted means: no per-trace fee, full retention control, full
data-residency control — at the cost of running the four containers.

## Prerequisites

- A Tempo instance reachable from your app. Locally that is the
  `grafana/tempo` Docker image; in prod typically Tempo running in
  Kubernetes or on Grafana Cloud.
- A Grafana instance configured with a Tempo datasource.
- Optionally Loki + Prometheus, both pre-configured as datasources in
  Grafana.
- For Grafana Cloud: the **Tempo OTLP endpoint** from your stack details and
  a Grafana Cloud **Access Policy token** with the `traces:write` scope.

## Install

```bash
uv pip install "ajolopy[otel]"
```

Tempo accepts the standard OTLP/HTTP and OTLP/gRPC formats. The framework
ships the HTTP exporter under the `otel` extra; no Grafana-specific Python
package is required.

## Wire it in

### Local self-hosted (Tempo on `localhost`)

Minimum Compose-style stack:

```yaml
# docker-compose.observability.yml
services:
  tempo:
    image: grafana/tempo:latest
    command: ["-config.file=/etc/tempo.yaml"]
    ports:
      - "4318:4318"   # OTLP HTTP
      - "3200:3200"   # Tempo UI
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    depends_on: [tempo]
```

Then point the framework at it:

```env
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=my-agent
```

`AjolopyFactory.create()` calls `setup_tracing_from_env()`, sees the
endpoint, installs the OTLP exporter, and every span starts flowing into
Tempo.

### Grafana Cloud

```env
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=https://tempo-prod-<region>.grafana.net/otlp
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64(instance_id:token)>
OTEL_SERVICE_NAME=my-agent
```

The `Authorization` header is `Basic <base64(<tempo_instance_id>:<token>)>`.
Generate it once:

```bash
printf '<tempo_instance_id>:<access_policy_token>' | base64
```

!!! tip "OTLP HTTP vs gRPC"
    The `otel` extra installs `opentelemetry-exporter-otlp-proto-http`,
    so leave the port on **4318** (HTTP). If your Tempo is configured for
    gRPC on **4317** only, either flip Tempo's config or install
    `opentelemetry-exporter-otlp-proto-grpc` and set the protocol via
    `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`.

### Power-user: custom provider

For a multi-exporter setup (Tempo for traces, OTLP/Loki for logs, custom
`Resource` for environment tagging), build your own `TracerProvider` and
install it **before** `AjolopyFactory.create()`. The framework's
`setup_tracing_from_env()` is a no-op when a real provider already exists.

```python
# bootstrap.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ajolopy import AjolopyFactory

from my_agent.app_module import AppModule


def _install_tempo_provider() -> None:
    resource = Resource.create(
        {
            "service.name": "my-agent",
            "service.namespace": "ai-team",
            "deployment.environment": "prod",
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint="http://tempo.svc:4318/v1/traces"))
    )
    trace.set_tracer_provider(provider)


async def bootstrap() -> None:
    _install_tempo_provider()
    await AjolopyFactory.create(AppModule)
```

## What you should see

- **Grafana → Explore → Tempo**: trace tree with the AJ-28 span shape; the
  `chat` span shows `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, `gen_ai.cost_usd`, and the model in / out.
- **TraceQL** queries scoped to AI traces:

  ```traceql
  { resource.service.name = "my-agent" && name =~ "agent.invoke .*" } | avg(span.gen_ai.cost_usd)
  ```

- **Tempo metrics generator** (or Prometheus recording rules on the
  attributes): a panel for cost-per-minute, tokens-per-minute, p95 latency
  per `gen_ai.request.model`.
- Tool-exception spans surface with the standard OTel error style
  (`Status = error`, exception event) so failed tool calls highlight in
  red in the trace view.

## Gotchas

- **Privacy.** `gen_ai.prompt` / `gen_ai.completion` are off by default.
  Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` to opt in;
  with self-hosted Grafana there is no third party in the loop, but
  prompt text still ends up in Tempo storage — set retention accordingly.
- **OTLP port mismatch.** The default Tempo image listens on **4317**
  (gRPC) and **4318** (HTTP). The `otel` extra ships the HTTP exporter;
  if you point at `4317`, all spans are dropped silently.
- **Sampling defaults.** Self-hosted Tempo will happily accept every span,
  which gets expensive on a busy agent. Configure a `TraceIdRatioBased`
  sampler at the SDK level (or use Tempo's tail-based sampling) once you
  cross ~10 RPS.
- **Cost attribute as a metric.** Tempo's metrics generator must be
  explicitly enabled and configured to derive metrics from
  `gen_ai.cost_usd` — without that, the attribute is searchable but not
  graphable. Same for Prometheus recording rules.
- **Cardinality on labels.** Do not promote `user_id` /
  `gen_ai.tool.call.id` to Prometheus labels. Keep high-cardinality
  fields in trace attributes (Tempo) and aggregate by model / agent in
  the metrics layer.

## See also

- [`@Agent` reference](../../reference/agent.md) — the primitive whose
  spans land in Tempo.
- [Recipes overview](index.md) — pick a different backend.
- [Install — `otel` extra](../../install.md#optional-extras).
- [Grafana Tempo docs · Configuration (OTLP receiver)](https://grafana.com/docs/tempo/latest/configuration/).
- [Grafana docs · TraceQL](https://grafana.com/docs/tempo/latest/traceql/).
