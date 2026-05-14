# AJ-28 — OpenTelemetry spans for `@Agent`/`@Tool`/`@Workflow`/`@MCP`/`@Stream` with `gen_ai.*` attrs

> Tracked in [`board.json`](../board.json) as `AJ-28`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §10 (Observabilidad) and the
> OpenTelemetry **GenAI semantic conventions** (the cross-vendor standard
> adopted by Langfuse, Logfire/Pydantic AI, OpenLLMetry, Honeycomb, Datadog).
> If this file ever conflicts with the Brief, the Brief wins — with one
> already-resolved exception below.

## What

Instrument the agent + tool + provider pipeline with OpenTelemetry spans that
follow the **GenAI semantic conventions**, so that any compliant OTel backend
(Langfuse, Honeycomb, Grafana Tempo, Datadog, Sentry, …) can render the trace
without vendor-specific glue.

The instrumentation surfaces:

1. A root **`agent.invoke {AgentName}`** span per `agent.run()` / `agent.stream()`
   call, carrying Ajolopy-level metadata (`ajolopy.agent.name`,
   `ajolopy.agent.operation`, `ajolopy.streaming`).
2. One **`chat {model}`** child span per LLM call inside the tool loop, with
   the full `gen_ai.*` attribute set (system, model in/out, temperature,
   max_tokens, finish reasons, input/output tokens). Fallback retries produce
   sibling `chat` spans under the same root.
3. One **`execute_tool {tool_name}`** grandchild span per tool dispatch, with
   `gen_ai.tool.name`, `gen_ai.tool.call.id`, and OTel `Status` reflecting
   success / exception.

The framework ships only `opentelemetry-api` in core. The heavy bits
(`opentelemetry-sdk`, OTLP HTTP exporter) ride a new `ajolopy[otel]` extra.
A `setup_tracing_from_env()` helper auto-installs a `TracerProvider` when the
SDK is importable and standard OTel env vars are present; otherwise spans
remain noop at the API layer (no overhead, no exports).

## Why

The wedge user — an AI Engineer at a Series A startup — needs three things from
production AI observability that today require a custom integration each:

1. **Token-level cost tracking.** Bill shock is dolor #2 in Brief §6. AJ-30
   builds a built-in pricing catalog that multiplies `gen_ai.usage.*` by model
   rates to emit `gen_ai.cost_usd` on every span. AJ-28 is the data source.
2. **Distributed tracing across model + tool calls.** A single user message
   can fan out into N LLM calls (tool loop, fallback retries) and M tool
   executions. Without a coherent span tree the trace is unreadable.
3. **Backend portability.** The user picks their backend (Langfuse for AI
   focus, Honeycomb for tracing depth, Datadog when corp pays the bill).
   Ajolopy must not bind. OTel semantic conventions are how that promise gets
   kept — the spans are the same shape regardless of exporter.

AJ-28 directly **unblocks AJ-30, AJ-31, AJ-51, AJ-54** (per `board.json` →
`blocks`).

## Design rule

Magical default + escape hatch:

| Scenario | Default | Escape hatch |
|---|---|---|
| User just wants traces in dev | `pip install ajolopy[otel]`; set `OTEL_EXPORTER_OTLP_ENDPOINT` in `.env`; everything else is automatic | `setup_tracing_from_env()` is callable directly; user can pass overrides |
| User has their own `TracerProvider` (custom resource, multi-exporter, batch tuning) | Set the provider before `AjolopyFactory.create()` runs; framework detects and skips its own setup | n/a — user is fully in control |
| User wants noop / no observability | `pip install ajolopy` (no extra) ⇒ SDK absent ⇒ all spans are no-op at the api layer | n/a |
| User wants to capture prompt / completion text | Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` (official OTel GenAI env var) | n/a — opt-in only, privacy default off |

## Decisions locked before implementation

1. **`trace=True` kwarg removed from `@Agent`.** Spans are always emitted via
   the OTel api; the SDK presence is the gate. This contradicts the Brief
   v4.0 killer demo literal (`@Agent(... trace=True, ...)`), reopened and
   accepted on 2026-05-13 because the per-primitive flag breaks composition
   with `@Workflow`/`@MCP`. The Brief and README copy get updated as part of
   this item. See engram memory `AJ-28 trace=True flag dropped, always-emit
   spans`.
2. **OTel SDK shipped as `ajolopy[otel]` extra.** Core stays on
   `opentelemetry-api` only. Heavy deps (`opentelemetry-sdk`,
   `opentelemetry-exporter-otlp-proto-http`) live in the extra. Framework
   uses `try/except ImportError` to detect SDK and is fully optional. See
   engram memory `AJ-28 OTel SDK shipped as ajolopy[otel] extra`.
3. **Streaming usage via `Chunk.usage: ChunkUsage | None`.** A single nullable
   field on the existing `Chunk` dataclass, populated only on the terminal
   chunk by each provider. No `StreamEnd` union, no estimation via
   `count_tokens()`. See engram memory `AJ-28 streaming usage via optional
   Chunk.usage field`.
4. **Provider-level spans live in the runtime, not the provider.** Providers
   stay pure SDK adapters; `AgentRuntime` wraps every `provider.complete()` /
   `provider.stream()` in a `chat {model}` span. This keeps a provider plugin
   author free of OTel imports.
5. **Privacy default: no content capture.** Prompt and completion text are
   **not** emitted as span attributes by default. Users opt in via the
   official OTel env var `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`.

## Span tree

```
agent.invoke {AgentName}                  ajolopy.agent.name,
                                          ajolopy.agent.operation (run|stream),
                                          ajolopy.streaming (bool)
 ├─ chat {model}                          gen_ai.system, gen_ai.operation.name=chat,
 │   ├─ execute_tool {tool}               gen_ai.request.model, gen_ai.response.model,
 │   ├─ execute_tool {tool}               gen_ai.request.temperature,
 │                                        gen_ai.request.max_tokens,
 │                                        gen_ai.response.finish_reasons,
 │                                        gen_ai.usage.input_tokens,
 │                                        gen_ai.usage.output_tokens
 ├─ chat {model}                          (second iteration after tool_results)
 └─ chat {model}                          (fallback retry on a different model)
```

### Span name conventions

| Span | Name |
|---|---|
| Agent root | `agent.invoke {AgentName}` |
| LLM call | `chat {request_model}` (lowercase verb, model string verbatim) |
| Tool dispatch | `execute_tool {tool_name}` |

### `gen_ai.system` values

Provider class → `gen_ai.system`:

| Provider | Value |
|---|---|
| `AnthropicProvider` | `anthropic` |
| `OpenAIProvider` | `openai` |
| `GeminiProvider` | `gcp.gemini` |
| `UniversalOpenAIProvider` | `openai_compatible.<flavor>` where flavor comes from the model route (e.g. `ollama`, `together`, `groq`, `mistral`, `deepseek`, `openrouter`, `bedrock`, `azure`). When the flavor cannot be resolved the value is `openai_compatible`. |

The mapping is owned by the provider class via a new class attribute
`gen_ai_system: str` (or a classmethod for the universal one which has to
inspect the route). The runtime reads it; the provider does not import OTel.

## Module layout

```
src/ajolopy/observability/
  __init__.py
  conventions.py     # gen_ai.* constants + helpers
  tracing.py         # setup_tracing_from_env, get_tracer, span helpers
```

`conventions.py` holds string constants only:

```python
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"

AJOLOPY_AGENT_NAME = "ajolopy.agent.name"
AJOLOPY_AGENT_OPERATION = "ajolopy.agent.operation"
AJOLOPY_STREAMING = "ajolopy.streaming"

OPERATION_CHAT = "chat"
```

`tracing.py` exposes:

```python
def get_tracer(name: str = "ajolopy") -> Tracer: ...
def setup_tracing_from_env() -> bool: ...   # True if it installed a provider
def is_content_capture_enabled() -> bool: ...
```

## SDK auto-setup contract

`setup_tracing_from_env()`:

1. If `opentelemetry.sdk.trace.TracerProvider` cannot be imported → return
   `False` (the extra is not installed; spans stay noop).
2. If `opentelemetry.trace.get_tracer_provider()` already returns a real
   `TracerProvider` (not the api's `ProxyTracerProvider`) → return `False`.
   The user installed one explicitly; we do not overwrite.
3. Otherwise install a `TracerProvider` with:
   - `Resource` populated from `OTEL_SERVICE_NAME` (default `"ajolopy"`),
     `OTEL_RESOURCE_ATTRIBUTES`.
   - `BatchSpanProcessor(OTLPSpanExporter())` reading
     `OTEL_EXPORTER_OTLP_ENDPOINT` /
     `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / headers / protocol envs.
4. Return `True`.

`AjolopyFactory.create()` calls it once after `ConfigService` is built.
Idempotent — second call returns `False` and does nothing.

## Acceptance criteria

Implementation lands behind these gates. Tick each as the corresponding test
passes.

- [ ] `pyproject.toml` defines
      `[project.optional-dependencies] otel = ["opentelemetry-sdk>=1.41.1", "opentelemetry-exporter-otlp-proto-http>=1.41.1"]`.
- [ ] New package `src/ajolopy/observability/` with `__init__.py`,
      `conventions.py`, `tracing.py`. Module exports `get_tracer`,
      `setup_tracing_from_env`, `is_content_capture_enabled`, and every
      attribute-name constant used by the runtime.
- [ ] `setup_tracing_from_env()` returns `False` when the SDK extra is not
      installed (test runs with the SDK stubbed away via `sys.modules`).
- [ ] `setup_tracing_from_env()` returns `False` when a real
      `TracerProvider` is already installed.
- [ ] `setup_tracing_from_env()` installs a `TracerProvider` +
      `BatchSpanProcessor` + `OTLPSpanExporter` when the SDK is importable
      and no provider is set. Resource attrs include
      `service.name=$OTEL_SERVICE_NAME` (default `ajolopy`).
- [ ] `AjolopyFactory.create()` invokes `setup_tracing_from_env()` exactly
      once and does not raise if it returns `False`.
- [ ] `providers/types.py` adds `ChunkUsage(input_tokens: int,
      output_tokens: int)` dataclass and `Chunk.usage: ChunkUsage | None =
      None`.
- [ ] `AnthropicProvider.stream()` sets `chunk.usage = ChunkUsage(...)` on
      the terminal chunk using the `message_delta` event payload.
- [ ] `OpenAIProvider.stream()` requests usage via
      `stream_options={"include_usage": True}` and sets `chunk.usage` on the
      terminal chunk.
- [ ] `GeminiProvider.stream()` sets `chunk.usage` from `usage_metadata` on
      the terminal chunk.
- [ ] `UniversalOpenAIProvider.stream()` mirrors the OpenAI path (with the
      same `stream_options` flag) — and when the upstream server does not
      include usage, `chunk.usage` stays `None` without erroring.
- [ ] `@Agent` decorator removes the `trace` kwarg from its signature.
- [ ] `AgentRuntime` removes `_trace_enabled`, the `_NullSpan` class, the
      `_NULL_SPAN` sentinel, and the gating branches in `_span` / `_tool_span`.
- [ ] `AgentRuntime.run` opens an `agent.invoke {AgentName}` root span with
      `ajolopy.agent.name`, `ajolopy.agent.operation="run"`,
      `ajolopy.streaming=false`.
- [ ] `AgentRuntime.stream` opens an `agent.invoke {AgentName}` root span
      with `ajolopy.agent.operation="stream"`, `ajolopy.streaming=true`.
- [ ] Every `provider.complete()` call is wrapped in a `chat {model}` span
      with all `gen_ai.*` attributes (system, operation.name=chat,
      request.model, response.model when known, request.temperature when
      set, request.max_tokens when set, response.finish_reasons,
      usage.input_tokens, usage.output_tokens).
- [ ] Every `provider.stream()` call is wrapped in a `chat {model}` span
      with the same `gen_ai.*` set; `usage.*` is populated from
      `chunk.usage` on the terminal chunk and remains absent when the
      provider could not report it.
- [ ] When fallback fires (e.g. primary raises `LLMProviderError`), the
      retry call gets its own sibling `chat {fallback_model}` span under
      the same `agent.invoke` root. The failed span records the exception
      via `span.record_exception` + `Status(StatusCode.ERROR)`.
- [ ] Each tool dispatch opens an `execute_tool {tool_name}` span with
      `gen_ai.tool.name`, `gen_ai.tool.call.id`. On exception the span sets
      `Status(StatusCode.ERROR)` and records the exception; on success it
      stays unset (OTel default).
- [ ] When `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`, the
      `chat` spans gain `gen_ai.prompt` (input messages, serialised) and
      `gen_ai.completion` (assistant text). Default off.
- [ ] `tests/observability/test_tracing.py` exists and uses an in-memory
      `InMemorySpanExporter` (from `opentelemetry-sdk.trace.export`) to
      assert: (a) span tree shape, (b) gen_ai.* attrs, (c) fallback sibling
      shape, (d) tool error path, (e) noop behaviour when SDK absent.
- [ ] All pre-existing tests pass after `trace=True/False` is removed from
      `@Agent` constructions.
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`
      all clean.
- [ ] README `## Quickstart` no longer shows `trace=True`. It mentions
      `pip install ajolopy[otel]` + `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Implementation pointers

- New: `src/ajolopy/observability/__init__.py`
- New: `src/ajolopy/observability/conventions.py`
- New: `src/ajolopy/observability/tracing.py`
- Edit: `src/ajolopy/agent/decorator.py` (drop `trace` kwarg)
- Edit: `src/ajolopy/agent/runtime.py` (rewrite span helpers around the new
  conventions; drop the `_NullSpan` gate)
- Edit: `src/ajolopy/providers/types.py` (`ChunkUsage` + `Chunk.usage`)
- Edit: `src/ajolopy/providers/base.py` (new class attr `gen_ai_system: str`
  abstract, or a `classmethod gen_ai_system_for(model: str) -> str` for the
  universal provider)
- Edit: `src/ajolopy/providers/anthropic/provider.py` (emit usage on stream
  terminal chunk; set `gen_ai_system = "anthropic"`)
- Edit: `src/ajolopy/providers/openai/provider.py` (add
  `stream_options.include_usage=True`; emit usage; set
  `gen_ai_system = "openai"`)
- Edit: `src/ajolopy/providers/gemini/provider.py` (emit usage from
  `usage_metadata`; set `gen_ai_system = "gcp.gemini"`)
- Edit: `src/ajolopy/providers/universal_openai/provider.py` (mirror OpenAI
  path; implement `gen_ai_system_for(model)` based on the route flavor)
- Edit: `src/ajolopy/factory/factory.py` (call `setup_tracing_from_env()`
  after `ConfigService` build, before lifecycle hooks)
- Edit: `pyproject.toml` (extras)
- Edit: `README.md` (Quickstart)
- New: `tests/observability/__init__.py`
- New: `tests/observability/test_tracing.py`
- Edit: any test under `tests/agent/` or `tests/stream/` that passes
  `trace=True/False` — remove that kwarg.

## Out of scope (lives in other items)

- Pricing catalog and `gen_ai.cost_usd` attr: **AJ-30**.
- Custom metric API on top of OTel meter: **AJ-31**.
- Backend-specific recipes (Langfuse, Sentry, Grafana, Honeycomb, Datadog):
  **AJ-51**.
- `@Workflow` / `@MCP` instrumentation: lands in **AJ-6** / **AJ-7**
  respectively, but they will reuse `get_tracer` + `conventions` from this
  item.
- `@Eval` span shape: **AJ-4**.

## Implementation notes

Empty for now. Append entries during the work in chronological order with a
`YYYY-MM-DD` prefix.
