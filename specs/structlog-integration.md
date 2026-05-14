# AJ-29 — structlog setup (JSON in prod, human-readable in dev, trace_id correlation)

> Tracked in [`board.json`](../board.json) as `AJ-29`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §observability and
> `08 - Foundation - DI Módulos y HTTP` §`AjolopyFactory — bootstrap del
> app` (step 5, "Inicializa observabilidad (OTel, structlog)"). If this
> file conflicts with the Brief, the Brief wins.

## What

`configure_logging(env: str, log_level: str | None = None) -> None` installs a
single structlog pipeline that the framework, the user's application, and
every third-party library running in the same process emit through. The
pipeline:

1. Picks an **output renderer** based on `env`:
   - `development` / `test` → `structlog.dev.ConsoleRenderer` with colors,
     `key=value` style, pretty-printed exception tracebacks.
   - `production` → `structlog.processors.JSONRenderer()`, one compact JSON
     object per line (the shape log aggregators like Loki, Datadog, Sentry
     and OpenTelemetry collectors expect).
2. Adds shared **context fields** before the renderer runs: ISO-8601 UTC
   timestamp, log level name, logger name, plus any contextvars merged via
   `structlog.contextvars.merge_contextvars`.
3. Adds a **trace correlation processor** that pulls the current OTel span
   via `opentelemetry.trace.get_current_span()` and, when the span context
   is valid, injects `trace_id` (32-char hex) and `span_id` (16-char hex)
   into the event dict. When no span is active or OTel is not configured
   the keys are simply omitted — no empty strings.
4. Captures **stdlib `logging`** through a `ProcessorFormatter`, so every
   `logging.getLogger(...)` call (including third-party loggers like
   `anthropic._client`, `openai._client`, `httpx`, `starlette`, `uvicorn`,
   `google_genai`) flows through the same renderer + trace fields + JSON
   treatment as `structlog` calls.
5. Resolves the **threshold** in this order, applied to both `ajolopy.*`
   loggers and the stdlib root logger:
   - Explicit `log_level=…` argument (highest priority).
   - `LOG_LEVEL` env var (case-insensitive).
   - Env-derived default: `development` → `DEBUG`, `production` → `INFO`,
     `test` → `WARNING`.

A second public helper, `get_logger(name: str | None = None) ->
structlog.stdlib.BoundLogger`, is the framework's recommended way to get a
logger from app code. It returns a structlog logger bound to the given
name (`__name__` is the convention). Existing modules that already use
`logging.getLogger(__name__)` keep working because of the stdlib capture
above — they do not need to migrate.

`AjolopyFactory.create()` calls `configure_logging(...)` exactly once, after
the early-env validation pass and before lifecycle hooks fire. AJ-28's
`setup_tracing_from_env()` runs alongside this call in the same bootstrap
slot; see "Implementation notes" for the coordination plan.

## Why

The wedge user (AI Engineer at a Series A) ships a service that talks to
LLM providers, runs agents, streams SSE, and is observed end-to-end. Two
properties of their workflow drive AJ-29:

- **Local debugging vs. production aggregation are different problems.**
  In development they want a colored, human-readable line they can scan in
  a terminal; in production they want one JSON object per line that Loki /
  Datadog / Vector can parse without a regex. Forcing them to swap log
  config in two places (their own loggers + every third-party logger) is
  exactly the boilerplate Ajolopy promises to remove.
- **Trace pivoting is non-negotiable for LLM apps.** When an agent
  invocation fails, the user opens the Langfuse / Sentry / Honeycomb
  trace, then needs to pivot from a span to the logs that fired *inside*
  that span. Without `trace_id` injected into every log line that pivot
  is impossible. AJ-28 emits the spans; AJ-29 stamps the logs with the
  same IDs so the bridge works.

Deferring this to v0.2 is not an option: every primitive that lands in
v0.1 (`@Agent`, `@Tool`, `@Stream`, `@Workflow`) emits logs. Shipping them
without a coherent logging story would force every wedge user to write
their own structlog setup on day one — the opposite of the "default
mágico + escape hatch" rule.

## Design rule

| Magical default | Escape hatch |
|---|---|
| `configure_logging` runs automatically inside `AjolopyFactory.create()` with `env` taken from `ConfigService.APP_ENV`. Levels follow the env-based defaults. Format follows the env. | Set `LOG_LEVEL=…` to override the threshold; call `configure_logging(env=..., log_level=...)` directly from app code if not using `AjolopyFactory`; pass `add_processors=[...]` to extend the pipeline (e.g. inject a `request_id` from contextvars); for a fully bespoke setup, skip `configure_logging` entirely and call `structlog.configure(...)` yourself before `AjolopyFactory.create()` runs (it detects an already-configured logger and is a no-op on subsequent calls). |

The escape hatch keeps the framework opt-in: a user who already runs
their own logging pipeline (e.g. inherited from a corp template) can
ignore Ajolopy's setup without fighting it.

## Decisions locked before implementation

- **Env-derived default level.** `APP_ENV=development → DEBUG`,
  `production → INFO`, `test → WARNING`. Explicit `LOG_LEVEL=…` always
  overrides. Mirrors the Spring Boot / NestJS pattern so the wedge user
  recognises it immediately.
- **Renderer follows env.** `development` and `test` → `ConsoleRenderer`
  with colors + pretty tracebacks. `production` → `JSONRenderer`, one
  compact line per event. No "mixed mode" — picking based on TTY is too
  magical and breaks reproducibility between dev laptops and CI.
- **Trace correlation via OTel API only.** The processor calls
  `opentelemetry.trace.get_current_span()` from `opentelemetry-api`
  (already a core dep for AJ-28). It never imports
  `opentelemetry.sdk` so the import cost stays zero when the SDK is not
  installed. If the span is invalid (the "no-op" span when OTel is not
  configured), `trace_id` / `span_id` keys are **omitted**, never
  emitted as empty strings — log aggregators key off presence, not
  emptiness.
- **Stdlib capture is on by default.** `configure_logging` installs a
  `logging.StreamHandler` on the root stdlib logger whose formatter is
  `structlog.stdlib.ProcessorFormatter`. Third-party libraries that use
  `logging.getLogger(...)` (anthropic, openai, google-genai, httpx,
  starlette, uvicorn) inherit the renderer + trace fields + threshold
  for free. Users who do not want this can call `configure_logging`
  with `capture_stdlib=False`.
- **Public API.** `from ajolopy import get_logger` is the recommended
  shape: `_LOGGER = get_logger(__name__)`. Existing modules using
  `logging.getLogger(__name__)` keep working — they go through the
  stdlib capture and produce identical output. Migration is optional.
- **Module location: `src/ajolopy/observability/logging.py`.** Shares
  the package with AJ-28's `tracing.py`. The package becomes the home
  for every cross-cutting observability concern in v0.1.
- **`structlog>=24.1.0` is a core dependency**, not an extra. Logging
  is universal: no Ajolopy app runs without logs. (Contrast with the
  OpenTelemetry SDK, which AJ-28 keeps as an opt-in extra because not
  every deployment runs an OTel collector.)
- **Idempotent.** Multiple calls to `configure_logging` after the first
  no-op out — the second call must not double-install the stdlib
  handler or replace the renderer. The check is a private module-level
  flag so tests can reset it via `_reset_for_tests()`.
- **Factory invocation order matters.** `configure_logging` runs after
  `_validate_env_early` so users see their env validation error in the
  *configured* format, not in raw stdlib output. It runs before
  `compile_module` so the lifecycle hooks fire under the configured
  logger.

## Module layout

```
src/ajolopy/observability/
  __init__.py         # re-exports configure_logging, get_logger; AJ-28 adds setup_tracing_from_env, conventions
  logging.py          # configure_logging, get_logger, _reset_for_tests, trace processor, env→level resolver
  tracing.py          # AJ-28 — not touched by AJ-29
  conventions.py      # AJ-28 — not touched by AJ-29

src/ajolopy/__init__.py
  + re-exports `get_logger` at the package root for `from ajolopy import get_logger`.

tests/observability/
  test_logging_levels.py        # env→level resolver, LOG_LEVEL override, log_level kwarg priority
  test_logging_renderer.py      # ConsoleRenderer in dev/test, JSONRenderer in prod, timestamp + level + logger
  test_logging_trace.py         # trace_id/span_id injected when OTel span is active; omitted otherwise
  test_logging_stdlib_capture.py# logging.getLogger(...) goes through the same renderer + trace fields
  test_logging_idempotent.py    # second configure_logging call is a no-op
  test_logging_factory.py       # AjolopyFactory.create() invokes configure_logging exactly once
```

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. Tests use `pytest`'s `caplog` for stdlib capture
assertions and `capsys` for renderer-output assertions.

### Dependency + packaging

- [ ] `structlog>=24.1.0` is added to `[project] dependencies` in
      `pyproject.toml`. `uv sync` succeeds; `uv.lock` is updated and
      committed.
- [ ] Importing `from ajolopy import get_logger` succeeds and returns a
      `structlog.stdlib.BoundLogger`.

### `configure_logging` — level resolution

- [ ] `configure_logging("development")` with no `LOG_LEVEL` env var and
      no `log_level` argument sets the effective threshold to `DEBUG`
      for both `ajolopy.test_module` and the stdlib root logger.
- [ ] `configure_logging("production")` defaults to `INFO`.
- [ ] `configure_logging("test")` defaults to `WARNING`.
- [ ] Setting `LOG_LEVEL=ERROR` in `os.environ` causes
      `configure_logging("development")` to use `ERROR`, not `DEBUG`.
- [ ] `LOG_LEVEL` parsing is case-insensitive (`debug`, `Debug`,
      `DEBUG` all accepted).
- [ ] An invalid `LOG_LEVEL` value (e.g. `"chatty"`) raises `ValueError`
      with the offending value in the message, before any handler is
      installed.
- [ ] Passing `log_level="ERROR"` explicitly overrides both the env
      default and `LOG_LEVEL` env var.

### `configure_logging` — renderer

- [ ] In `development` mode, a log call produces a line containing
      ANSI color codes and `key=value` formatting (asserted by checking
      the output against `structlog.dev.ConsoleRenderer`'s known shape,
      not byte-exact match).
- [ ] In `test` mode the renderer is also `ConsoleRenderer` — the only
      difference from `development` is the default level.
- [ ] In `production` mode each log call produces a single line of valid
      JSON. The JSON has at least these keys: `timestamp`, `level`,
      `logger`, `event`. `timestamp` parses as ISO-8601 UTC.
- [ ] An exception logged via `logger.exception("boom")` in `production`
      emits the traceback under a JSON `exception` key (string).
- [ ] The same exception in `development` emits a pretty-printed
      traceback after the event line (default `ConsoleRenderer`
      behaviour).

### Trace correlation

- [ ] When called inside an active OpenTelemetry span (created via
      `opentelemetry.sdk.trace.TracerProvider` in the test fixture),
      a log event in `production` includes `trace_id` (32-char hex)
      and `span_id` (16-char hex) fields whose values equal the span
      context's `trace_id` / `span_id` formatted via OTel's hex helpers.
- [ ] When no span is active, the log event has neither `trace_id` nor
      `span_id` keys (verified by asserting the keys are absent from
      the JSON, not by asserting empty values).
- [ ] When the current span is the invalid "no-op" span (i.e. OTel
      SDK never configured), the processor takes the same branch as
      "no span" — keys are omitted.
- [ ] In `development` mode, `trace_id=… span_id=…` appears in the
      `ConsoleRenderer` output when a span is active (proves the
      processor runs before the renderer in both branches).

### Stdlib `logging` capture

- [ ] `logging.getLogger("ajolopy.test_module").info("hello", extra={"k":"v"})`
      produces output through the same renderer as a direct
      `structlog.get_logger().info(...)` call (asserted by parsing the
      JSON line in `production` mode).
- [ ] A log from a fake third-party logger (`logging.getLogger("acme")`)
      goes through the same renderer + trace fields. Proves the root
      handler installation actually reaches non-`ajolopy.*` names.
- [ ] `configure_logging(env="development", capture_stdlib=False)`
      leaves the stdlib root logger untouched (no new handler attached).

### Public API

- [ ] `from ajolopy import get_logger` is exported. `get_logger("x.y")`
      returns a `structlog.stdlib.BoundLogger` whose name is `"x.y"`.
- [ ] `get_logger()` with no argument returns a logger bound to the
      caller's `__name__` (via `inspect`-free convention: the helper
      simply requires the caller to pass `__name__`; the no-arg path
      returns the root `ajolopy` logger so it remains useful in REPL).
- [ ] Existing code that uses `logging.getLogger(__name__)` from
      `ajolopy.agent.runtime`, `ajolopy.stream.runtime`,
      `ajolopy.providers.*` continues to produce output (no behavioural
      change after capture is enabled).

### Idempotency

- [ ] Calling `configure_logging("production")` twice in a row results
      in exactly one stdlib root handler installed. The second call is
      a no-op (verified by patching `logging.basicConfig` and asserting
      it ran once).
- [ ] `_reset_for_tests()` exists, undoes the install, and is used by
      the test fixtures so each test starts from a clean state.

### Factory invocation

- [ ] `AjolopyFactory.create(RootModule)` calls `configure_logging`
      exactly once. Order: after `_validate_env_early`, before
      `compile_module`. Verified by patching the helper and asserting
      the call count + position relative to other patched helpers.
- [ ] The `env` passed to `configure_logging` is read from
      `os.environ.get("APP_ENV", "development")` (or from a
      `ConfigService` instance if one is already available in the
      bootstrap path; see "Implementation notes" for the chosen seam).
- [ ] When `AjolopyFactory.create` raises a `FactoryStartupError` from
      a later step, the configured renderer is already in effect — the
      framework's own error log line is rendered in the correct format
      (JSON in production).

### Lint / type / format gates

- [ ] `uv run ruff check` is clean for `src/ajolopy/observability/` and
      `tests/observability/`.
- [ ] `uv run ruff format --check` is clean for the same paths.
- [ ] `uv run pyright` is clean in strict mode for the new module and
      tests (structlog ships type stubs; no `# pyright: ignore`
      escapes without an inline justification).
- [ ] `uv run pytest` is green for the full suite (new tests +
      existing 360+ tests stay passing).

## Implementation pointers

- New module: `src/ajolopy/observability/logging.py`.
  - `configure_logging(env, log_level=None, *, capture_stdlib=True,
    add_processors=None) -> None`.
  - `get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger`.
  - `_reset_for_tests() -> None` — private; the test fixtures import
    it. Not part of the public API.
  - Private helpers: `_resolve_level(env, log_level)`,
    `_trace_correlation_processor(logger, name, event_dict)`,
    `_install_stdlib_handler(level, processors, renderer)`.
- New module: `src/ajolopy/observability/__init__.py`.
  - Re-exports `configure_logging`, `get_logger`. AJ-28 will add
    `setup_tracing_from_env` and the OTel `conventions` namespace.
  - **Merge conflict expected** with AJ-28's branch on this file —
    see "Implementation notes".
- Change to `src/ajolopy/__init__.py`:
  - Add `from .observability import get_logger`.
  - Append `"get_logger"` to `__all__`.
- Change to `src/ajolopy/factory/factory.py`:
  - Insert `configure_logging(env=...)` call between
    `_validate_env_early(root_module)` and `compile_module(...)`.
  - Wrap the call in a `try`/`except` that surfaces failures as
    `FactoryStartupError(step="configure_logging", ...)` — the same
    pattern the existing steps use.
- Tests: `tests/observability/` (new directory). One file per concern
  per the "Module layout" section above. Async tests use
  `pytest-asyncio` (already a dev dep).
- Runtime deps: `structlog>=24.1.0` is added to
  `pyproject.toml [project] dependencies`. No other deps change —
  `opentelemetry-api` is already core for AJ-28.
- Dev deps: none new. The OTel SDK fixtures use
  `opentelemetry-sdk` which is an opt-in extra in v0.1; for AJ-29 the
  tracing tests install it as a dev-only dep marker (already present
  via AJ-28's branch). If AJ-28 has not landed yet, the trace tests
  add `opentelemetry-sdk` to the dev group as part of this item.

## Out of scope

- **Log sampling / rate limiting.** Production deployments with very
  high log volume need a sampler in front of the renderer; this is a
  v0.2 concern once we have real usage data.
- **Async logging / non-blocking handlers.** Structlog's synchronous
  rendering is fast enough for v0.1; switching to
  `logging.handlers.QueueHandler` is a v0.2 optimisation.
- **Request-ID middleware.** Threading a per-request ID into log
  events belongs to the HTTP layer (AJ-15/AJ-16) and will land as a
  separate item that adds a context-vars-aware middleware. AJ-29 only
  ships the contextvars *machinery* (`merge_contextvars` in the
  pipeline) so the middleware item is purely additive.
- **Log shipping integrations.** Vendor-specific shipping (Datadog
  agent, Sentry breadcrumbs, OTel Logs exporter) lives in the
  observability recipes section of the docs, not in the framework
  surface. Recipes are tracked separately.
- **Per-logger overrides.** A future `LOG_LEVEL_OVERRIDES` env var
  (e.g. `httpx=WARNING,anthropic=DEBUG`) is a v0.2 item. v0.1 has one
  global threshold.
- **`@Stream` per-event log envelopes.** The decision to log each SSE
  event lives with `@Stream` (AJ-3) and `@Agent` (AJ-1), not with the
  logging setup.

## Implementation notes

(empty — fill in during the implementation PR)
