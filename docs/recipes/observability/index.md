# Observability recipes

Plug Ajolopy into your observability backend in **under 10 minutes**. Every
recipe on this page assumes you have a working agent from the
[Quickstart](../../quickstart.md). Pick a backend, follow the page, watch
traces land.

## The shared model

Ajolopy ships **only** `opentelemetry-api` in the core install. The SDK and
the OTLP HTTP exporter live in the [`otel`](../../install.md#optional-extras)
extra:

```bash
uv pip install "ajolopy[otel]"
```

When the extra is installed **and** `OTEL_EXPORTER_OTLP_ENDPOINT` (or
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) is set,
[`AjolopyFactory.create()`](../../reference/module.md) calls
`setup_tracing_from_env()` once during bootstrap. That installs a real
`TracerProvider` with a `BatchSpanProcessor` and an `OTLPSpanExporter` reading
the standard OTel environment variables. Every primitive — `@Agent`,
`@Tool`, `@Stream`, `@Workflow`, `@MCP` — emits spans through that pipeline
automatically. No per-primitive flag, no per-call instrumentation.

The wire format is the **OpenTelemetry GenAI semantic conventions**: every
LLM call lands as a `chat {model}` span carrying `gen_ai.system`,
`gen_ai.request.model`, `gen_ai.usage.input_tokens` /
`gen_ai.usage.output_tokens`, and — when the model resolves against the
embedded pricing snapshot — `gen_ai.cost_usd`. The root
`agent.invoke {AgentName}` span rolls up the total cost as
`ajolopy.cost_usd.total`. Every modern backend understands this shape; the
recipes below differ only in where to point the exporter.

!!! tip "One pipeline, any backend"
    Switching from Langfuse to Honeycomb (or to a local Tempo) is one env-var
    change. The framework does not bind to a vendor; the recipes are
    cookbooks, not lock-ins.

## Which one should I pick?

| Backend                          | Best for                                                                                  | Hosted | Self-host | AI-native | Notes                                                            |
| -------------------------------- | ----------------------------------------------------------------------------------------- | :----: | :-------: | :-------: | ---------------------------------------------------------------- |
| [Langfuse](langfuse.md)          | LLM-first dashboards out of the box, prompt + completion review, cost-by-user.            |   x    |     x     |     x     | Pure OTLP, no SDK swap. Sweetest defaults for `gen_ai.*` attrs.  |
| [Sentry](sentry.md)              | You already pay for Sentry on the JS side. Errors + traces under one project.             |   x    |           |           | AI Monitoring product reads OTLP. Errors + AI traces in one UI.  |
| [Grafana stack](grafana.md)      | On-prem, cost-controlled, "we already run Grafana." Tempo + Loki + Prometheus + Grafana.  |   x    |     x     |           | Self-hosted by default; Grafana Cloud accepts the same OTLP.     |
| [Honeycomb](honeycomb.md)        | High-cardinality traces, BubbleUp on outliers, tail-latency debugging.                    |   x    |           |           | Best UX for "why is this one request slow / expensive".          |
| [Datadog](datadog.md)            | Enterprise default; corp pays the bill; one pane of glass with infra + APM + logs.        |   x    |           |           | OTLP endpoint behind the regular DD API key.                     |

If you have not picked one yet:

- Optimising for **AI-specific dashboards** with a generous free tier:
  start with [Langfuse](langfuse.md).
- Optimising for **errors and AI traces in the same view**: pick
  [Sentry](sentry.md).
- Optimising for **on-prem / data-residency / no third-party cost**:
  pick the [Grafana stack](grafana.md).
- Optimising for **deep trace analytics** and outlier hunts: pick
  [Honeycomb](honeycomb.md).
- Optimising for **fitting into an existing Datadog estate**: pick
  [Datadog](datadog.md).

## The recipe template

Every page in this section follows the same six-section shape:

1. **What you get** — the dashboard / data promise in one paragraph.
2. **Prerequisites** — account / API key / endpoint URL.
3. **Install** — the optional-extras line (always
   [`ajolopy[otel]`](../../install.md#optional-extras), plus a
   backend-specific one when applicable).
4. **Wire it in** — the minimum `.env` block and (optionally) the minimum
   code snippet. Honours the same `setup_tracing_from_env()` surface for
   every backend.
5. **What you should see** — prose description of the traces, the cost
   roll-up, the error spans, the per-model latency.
6. **Gotchas** — cardinality limits, sampling defaults, cost gotchas,
   content-capture opt-in, the one or two things that will bite you.

## Privacy default

The framework does **not** export prompt or completion text by default. LLM
inputs and outputs routinely carry PII, secrets, and customer data, and
exporting them to a third party without consent is a footgun.

Opt in only when you understand the trade-off:

```bash
# .env
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
```

The official OTel GenAI env var. When set, `chat` spans gain `gen_ai.prompt`
and `gen_ai.completion` string attributes. Every recipe page below repeats
this knob under its Gotchas section so the trade-off is impossible to miss.

## See also

- [Install — optional extras](../../install.md#optional-extras)
- [`@Agent` reference](../../reference/agent.md) — the primitive every
  recipe traces.
- [Next steps](../../next-steps.md) — where to go after observability is
  wired in.
