# AJ-3 — `@Stream` decorator (SSE on `@Agent` and `@Workflow`)

> Tracked in [`board.json`](../board.json) as `AJ-3`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §4 (Killer demo Paso 1) and
> `01 - Primitivas core - especificacion detallada` §`@Stream`. If this file
> ever conflicts with the Brief, the Brief wins.

## What

`@Stream` is a **method decorator** that turns an `async def` generator method
into an HTTP endpoint that responds with Server-Sent Events
(`text/event-stream`). The decorator:

1. Validates its configuration at decoration time (`path` shape, `method` value,
   `auth=True` not allowed until AJ-17).
2. Stamps the method with metadata (`path`, `method`, `auth`,
   `heartbeat_seconds`, the original handler) so the mount layer can register
   the route later.
3. Returns the method unchanged so calling `instance.respond(...)` from Python
   still returns the underlying async generator (composability with `@Eval`,
   tests, and internal callers).
4. At mount time, wraps the bound method in a Starlette handler that:
   - Parses request inputs through the same `ValidationPipe` machinery as
     AJ-15 (`Body()`, `Query()`, `Param()`, `Header()`).
   - Wraps each `yield`-ed value in a properly framed SSE `data:` event.
   - Emits SSE comment lines (`: keepalive\n\n`) every `heartbeat_seconds`.
   - Detects client disconnect via Starlette's `Request.is_disconnected()` and
     cancels the underlying generator (the framework calls `aclose()` on it).
   - Catches exceptions raised inside the generator and emits one final
     `data: {"error": "..."}\n\n` event before closing the stream. The
     original exception is logged at `ERROR` level via the framework's logger.

A separate helper, `mount_streams(app, classes_or_instances)`, walks the
provided classes/instances, finds every `@Stream`-marked method, and registers
the wrapping handlers on the given Starlette app. `create_app()` from
`ajolopy.http` (AJ-15) gains a thin `streams=[...]` kwarg that calls
`mount_streams` for the common case — keeping the demo at one line of wiring.

## Why

Brief v4.0 §4 names "Streaming SSE como endpoint HTTP" as one of the six
collapsing items in the killer demo Paso 1 — the table claims `@Stream` saves
"~30 líneas (Starlette + heartbeats + cancel on disconnect)" of glue per
project. The wedge user (AI Engineer at a Series A) re-implements heartbeats
and disconnect handling on every new chat surface; `@Stream` reduces that to a
single decorator and follows the framework-wide **"magical default + escape
hatch"** rule.

Splitting `@Stream` from `@Controller` (AJ-10) and from `AjolopyFactory`
(AJ-14) lets the killer demo Paso 1 ship before DI integration lands. The
mount helper is the same shape the factory will use later, so the migration
is mechanical when AJ-14 arrives.

## Public surface (v0.1)

```python
from typing import Annotated
from pydantic import BaseModel

from ajolopy import Agent, Stream
from ajolopy.http import Body, create_app


class ChatRequest(BaseModel):
    message: str


@Agent(
    model="claude-sonnet-4-7",
    system="You are Acme Support.",
)
class Support:
    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]):
        async for chunk in self.stream(body.message):
            yield chunk


app = create_app(streams=[Support])
```

### Signature

```python
def Stream(
    path: str,
    method: Literal["GET", "POST"] = "POST",
    *,
    auth: bool = False,
    heartbeat_seconds: float | None = 30.0,
) -> Callable[[F], F]: ...
```

- `path` — Starlette path pattern (`"/chat"`, `"/users/{user_id}/chat"`).
- `method` — `"GET"` or `"POST"`. Default `"POST"` matches the Brief; GET is
  legal for query-only handlers.
- `auth` — reserved for AJ-17 (`@UseGuards`). `auth=True` raises
  `StreamConfigError` at decoration time in this item; default `False` is a
  no-op.
- `heartbeat_seconds` — emit a `: keepalive\n\n` SSE comment every N seconds.
  `None` disables heartbeats. Default 30 s per the Brief.

### Decorated method shape

```python
@Stream("/chat")
async def respond(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[str | dict, None]:
    yield "token"
    yield {"event": "tool_call", "name": "lookup_order"}
```

The method **must** be an `async def` function whose body uses `yield`
(i.e. an async generator). Each yielded value is serialised:

| Yielded type | SSE wire format |
|---|---|
| `str` | `data: <text>\n\n` (newlines in `<text>` are split into multiple `data:` lines per the SSE spec) |
| `dict` / `BaseModel` | `data: <json>\n\n` (UTF-8 JSON, single line) |
| any other | `StreamConfigError` at decoration time |

### Mount API

```python
from ajolopy.stream import mount_streams
from ajolopy.http import create_app

# One-line magical default:
app = create_app(streams=[Support, Chat])

# Two-line escape hatch (control over app construction):
app = create_app()
mount_streams(app, [Support, Chat])

# Pass pre-built instances when constructor args matter:
support = Support(db=db)
app = create_app(streams=[support])
```

`mount_streams` accepts a list of:

- **classes** — instantiated as `Cls()` (zero-arg constructor) and bound; this
  works because `@Agent`-decorated classes default to a zero-arg `__init__`.
- **instances** — bound directly, no re-instantiation. Required when the user
  needs to pass constructor arguments (e.g. `Support(db=...)`).

For each item, `mount_streams` walks the class MRO looking for attributes
marked with `_ajolopy_stream` metadata and calls `add_route` (from AJ-15) per
method.

### Error envelope

```text
data: {"error": "lookup_order failed: db unreachable"}\n\n
```

The error event is the **last** event emitted on the stream; the connection
closes immediately after. The original exception is logged at `ERROR` level
via the framework's logger (verified with `caplog` in tests).

## Design rules

- **Magical default**: a method that already `yield`s strings becomes an SSE
  endpoint with heartbeats and disconnect handling by adding one decorator.
  The mount step is one extra kwarg on `create_app`.
- **Escape hatches**:
  - Yield `dict` (or a Pydantic `BaseModel`) to emit structured JSON events
    instead of plain tokens.
  - `heartbeat_seconds=None` disables heartbeats for handlers that produce
    their own keepalive.
  - Bypass `mount_streams` entirely and call `add_route(app, method, path,
    handler)` with a hand-written SSE handler — `@Stream` is opt-in.
  - Use `mount_streams(app, [instance])` to control instantiation.
- **No DI here.** `mount_streams` calls `Cls()` for classes; constructor
  arguments must come via pre-built instances. AJ-14 (`AjolopyFactory`)
  replaces the zero-arg path with full DI resolution; the signature of
  `streams=[...]` does not change.
- **Reuses AJ-15.** Parameter resolution (`Body()`, `Query()`, `Param()`,
  `Header()`) and exception filtering go through the existing pipeline — no
  duplicate body parser inside `@Stream`. A `StreamingResponse` returned by
  the wrapping handler is forwarded verbatim by AJ-15 (already verified in
  AJ-15's acceptance criteria).
- **Composable with `@Agent` and `@Workflow`.** The decorator never inspects
  the host class — it only requires the method to be an async generator.
  Methods on plain classes work too; methods on `@Workflow`-decorated classes
  will compose automatically when AJ-6 lands.

## Out of scope for this item

- `@UseGuards` integration → `AJ-17`. `auth=True` is rejected at decoration
  time until then.
- DI-driven instantiation → `AJ-14`. Classes are constructed via `Cls()`;
  instances are bound verbatim.
- `@Workflow` tests → `AJ-6`. The decorator is workflow-agnostic; once `AJ-6`
  lands its tests will exercise this path. No stub `@Workflow` is created
  here.
- OpenTelemetry spans for `@Stream` → `AJ-28` (the spec there explicitly
  covers `@Stream` once the surface stabilises).
- WebSocket upgrade — SSE only in v0.1. Brief defers WS to v0.3.
- Server-side reconnection support (`Last-Event-ID` header processing) —
  client-side reconnect works automatically since EventSource handles it;
  resuming server state is a v0.2 concern.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All HTTP tests use `starlette.testclient.TestClient`
in streaming mode (`with client.stream("POST", ...) as r:`); no real network
traffic happens in CI.

### Decorator validation

- [ ] `@Stream("/chat")` on an async generator method stamps
      `_ajolopy_stream` metadata (`path`, `method`, `auth`,
      `heartbeat_seconds`, original function) on the method object and
      returns the method unchanged (calling it directly still produces the
      original async generator).
- [ ] `@Stream` on a non-async-generator (regular `async def`, sync function,
      sync generator) raises `StreamConfigError` at decoration time with a
      message naming the offending function.
- [ ] `@Stream("")` or a path that does not start with `/` raises
      `StreamConfigError` at decoration time.
- [ ] `@Stream("/chat", method="DELETE")` raises `StreamConfigError`; only
      `"GET"` and `"POST"` (case-insensitive) are accepted in v0.1.
- [ ] `@Stream("/chat", auth=True)` raises `StreamConfigError` referencing
      AJ-17 (`@UseGuards`).
- [ ] `@Stream("/chat", heartbeat_seconds=0)` and any negative value raise
      `StreamConfigError`; `None` is accepted (disables heartbeats).

### `mount_streams` / `create_app(streams=...)`

- [ ] `mount_streams(app, [Cls])` instantiates `Cls()` (zero-arg
      constructor) and registers every `@Stream`-marked method on `app` using
      `add_route` from AJ-15 (verified by patching `add_route`).
- [ ] `mount_streams(app, [instance])` does **not** call the class
      constructor; the supplied instance is bound directly.
- [ ] `mount_streams` raises `StreamConfigError` when handed a class whose
      `__init__` requires arguments and no instance is supplied, with a
      message pointing to "pass a pre-built instance or wait for AJ-14".
- [ ] `mount_streams` raises `StreamConfigError` when a class has no
      `@Stream`-marked methods (catches typos like decorating the wrong
      method).
- [ ] `create_app(streams=[Cls])` is equivalent to `app = create_app(); mount_streams(app, [Cls])`.
- [ ] `create_app(streams=None)` (default) leaves the app unchanged — no
      stream wiring runs. The `streams` kwarg is opt-in.

### SSE wire format

- [ ] A handler that yields three string tokens produces a response with
      `content-type: text/event-stream`, `cache-control: no-cache`,
      `connection: keep-alive`, and a body of
      `data: token1\n\ndata: token2\n\ndata: token3\n\n`.
- [ ] A yielded string containing `\n` is split across multiple `data:`
      lines per the SSE spec
      (`yield "line1\nline2"` → `data: line1\ndata: line2\n\n`).
- [ ] A yielded `dict` is serialised as compact UTF-8 JSON:
      `yield {"event": "x"}` → `data: {"event":"x"}\n\n`.
- [ ] A yielded Pydantic `BaseModel` is serialised via
      `model.model_dump(mode="json")` and emitted as `data: <json>\n\n`.
- [ ] Yielding any other type (e.g. `bytes`, `int`) raises a runtime
      `StreamRuntimeError`, which is caught and surfaced via the error
      envelope (see "Error handling" below).

### Heartbeats

- [ ] With `heartbeat_seconds=0.05`, a handler that takes 0.2 s between
      yields produces at least three `: keepalive\n\n` comment lines
      interleaved with the `data:` events (verified with `freezegun` or a
      monotonic clock fake).
- [ ] `heartbeat_seconds=None` produces zero comment lines for the same
      handler.
- [ ] Heartbeats stop firing once the handler's generator finishes (no
      keepalive after the final `data:` event).

### Disconnect handling

- [ ] When the test client closes the connection mid-stream, the framework
      cancels the underlying async generator (verified by checking that the
      generator's `finally:` block ran and the in-flight `asyncio.Task` for
      the heartbeat coroutine is cancelled).
- [ ] After disconnect, no further work is done on the generator — verified
      by yielding from a counter and asserting the counter stopped advancing
      after the client closed.

### Error handling

- [ ] A handler that raises mid-stream sends one final
      `data: {"error": "<exception message>"}\n\n` event before closing the
      stream. The bytes after that event are zero.
- [ ] The original exception is logged at `ERROR` level via
      `logging.getLogger("ajolopy.stream")` (verified with `caplog`); the
      response stays 200 OK because headers were already sent.
- [ ] An exception raised **before the first `yield`** (e.g. validation
      error from the pipe) goes through AJ-15's exception filter pipeline
      and produces the normal 422/500 JSON envelope, not the SSE error
      envelope (no `text/event-stream` headers are emitted).

### Parameter resolution (delegates to AJ-15)

- [ ] `Annotated[Dto, Body()]` where `Dto` is a Pydantic `BaseModel`
      parses/validates the request body via the same `ValidationPipe`
      AJ-15 uses; a malformed payload produces a 422 response (no SSE).
- [ ] `Annotated[str, Query()]` on a `@Stream("/chat", method="GET")`
      handler reads from the query string.
- [ ] `Annotated[str, Param()]` reads path placeholders
      (`@Stream("/chat/{room}")` + `room: Annotated[str, Param()]`).
- [ ] A handler whose first non-`self` parameter is `request: Request`
      receives the raw Starlette request (AJ-15 escape hatch path).

### Composability

- [ ] Calling `instance.respond(body)` directly (without going through HTTP)
      returns the original `AsyncGenerator[str | dict, None]`. Iterating it
      yields the raw values, **not** SSE-framed bytes. (Lets `@Eval` and
      tests consume the generator natively.)
- [ ] A class with two `@Stream` methods (`@Stream("/chat")` and
      `@Stream("/admin/chat")`) registers both routes when mounted.
- [ ] `@Stream` on a method of a plain class (no `@Agent` decorator) still
      mounts and serves correctly. The decorator is host-agnostic.

### Negative cases

- [ ] Two `@Stream` decorators on the same method raise `StreamConfigError`
      at decoration time.
- [ ] Two `@Stream` methods declaring the same `(method, path)` pair across
      classes in the same `mount_streams` call raise `StreamConfigError`
      with both source method names in the message.
- [ ] A `@Stream` method whose signature requires a parameter that AJ-15's
      introspector cannot resolve (e.g. an untyped marker) raises
      `HttpHandlerConfigError` at mount time (propagated unchanged from
      AJ-15).

## Implementation pointers

- Source: `src/ajolopy/stream/` (new package).
  - `__init__.py` — public re-exports: `Stream`, `mount_streams`,
    `StreamConfigError`, `StreamRuntimeError`.
  - `decorator.py` — the `Stream(...)` decorator factory plus
    `_ajolopy_stream` metadata helpers (`get_stream_metadata`, `iter_stream_methods`).
  - `mount.py` — `mount_streams(app, items)`; the bridge to AJ-15's
    `add_route`.
  - `sse.py` — SSE wire helpers (`format_data_event`, `format_keepalive`,
    `format_error_event`, value-to-text serialiser).
  - `runtime.py` — `make_sse_handler(bound_method, metadata)`; the
    Starlette-facing handler that orchestrates pipe → generator →
    heartbeats → disconnect → errors.
  - `errors.py` — `StreamConfigError` (decoration / mount errors),
    `StreamRuntimeError` (mid-stream errors caught and surfaced as the
    error envelope).
- Changes to AJ-15 surface: `src/ajolopy/http/app.py` gains an optional
  `streams: list[type | object] | None = None` kwarg on `create_app(...)`.
  Implementation imports `mount_streams` lazily inside the function body to
  avoid a hard dep cycle between `ajolopy.http` and `ajolopy.stream`. The
  AJ-15 acceptance criteria stay green.
- Tests: `tests/stream/` with one file per concern
  (`test_decorator.py`, `test_mount.py`, `test_sse_format.py`,
  `test_heartbeats.py`, `test_disconnect.py`, `test_errors.py`,
  `test_params.py`, `test_composability.py`, `test_negative.py`).
- Runtime deps: none new. `starlette` (AJ-15) provides
  `StreamingResponse` and `Request.is_disconnected()`; `anyio` (transitive
  via Starlette) handles the heartbeat scheduling.
- Dev deps: none new. The streaming `TestClient` is already in use by AJ-15.

## Implementation notes

_Populated as the item is implemented._
