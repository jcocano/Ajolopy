# AJ-15 — HTTP layer over Starlette

> Tracked in [`board.json`](../board.json) as `AJ-15`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (framework primitives —
> HTTP / controllers / pipes / filters) and the cross-cutting **"magical
> default + escape hatch"** rule. If this file ever conflicts with the Brief,
> the Brief wins.

## What

The HTTP foundation the rest of the framework's web-facing primitives sit on.
This item ships **four cooperating pieces** plus a low-level functional API:

1. **`ValidationPipe`** — a Pydantic v2-backed input pipe that coerces and
   validates raw request data (body bytes, query string, path captures,
   headers) into typed values before the handler runs.
2. **Param-injection decorators** — `Body()`, `Query()`, `Param()`,
   `Header()` consumed via `typing.Annotated` on handler parameters. They
   describe *where* a value comes from; `ValidationPipe` decides *how* to
   coerce/validate it.
3. **`ExceptionFilter` ABC + `@Catch(...)`** — class-based exception
   filters in the NestJS style, registered globally on the app instance.
   The framework ships a default filter for `pydantic.ValidationError`
   (→ HTTP 422) and for `HttpException` (→ its own `status`).
4. **`HttpException` base** — a typed framework error carrying
   `status: int` and `message: str`, plus a small hierarchy of common
   subclasses (`BadRequestException`, `UnauthorizedException`,
   `NotFoundException`, `ConflictException`, `InternalServerErrorException`).
5. **Low-level functional API** — `create_app()` / `add_route()` exported
   from `ajolopy.http` so the layer is exercisable end-to-end without
   `@Controller` (AJ-10) or `@Get/@Post/...` (AJ-16). This unblocks AJ-3
   (`@Stream`) and is the surface the higher-level decorators reduce to.

Every piece is built around plain Starlette (`Route`, `Request`, `Response`,
`JSONResponse`); the framework does **not** wrap Starlette in a parallel
type hierarchy. Users who need the raw `Request` accept it as a normal
parameter.

### Default error envelope

Every uncaught exception leaves the app through the framework's default
filter pipeline and is serialised as the same JSON shape (chosen to match
NestJS's `HttpException` body for cross-stack familiarity):

```json
{
  "statusCode": 422,
  "error": "Unprocessable Entity",
  "message": "Validation failed",
  "details": [/* optional, present for validation errors */]
}
```

`statusCode` matches the response status. `error` is the canonical HTTP
reason phrase. `message` is the exception's `message`. `details` is
omitted unless explicitly set (validation errors set it to
`ValidationError.errors()`).

## Why

Brief v4.0 requires the framework's HTTP entry point to be production-grade
on day one: typed inputs, predictable error responses, automatic 422 for
bad payloads, and no `os.environ`-style ad hoc plumbing. The wedge user
(AI Engineer at a Series A) expects FastAPI-grade ergonomics with the
NestJS-style class/decorator discoverability the rest of Ajolopy enforces.

Splitting this layer from the route decorators (AJ-16) and from
`@Controller` (AJ-10) keeps each PR focused and lets `@Stream` (AJ-3) — a
killer-demo Paso 1 dependency — start as soon as this item lands instead
of waiting for full DI integration.

## Public surface (v0.1)

### Functional low-level API

```python
from typing import Annotated
from pydantic import BaseModel
from starlette.requests import Request

from ajolopy.http import (
    Body,
    Header,
    Param,
    Query,
    add_route,
    create_app,
)


class CreateUserDto(BaseModel):
    email: str
    name: str


class ListUsersDto(BaseModel):
    page: int = 1
    limit: int = 20


async def create_user(body: Annotated[CreateUserDto, Body()]) -> dict[str, str]:
    return {"id": "u_1", "email": body.email, "name": body.name}


async def list_users(query: Annotated[ListUsersDto, Query()]) -> dict[str, object]:
    return {"page": query.page, "limit": query.limit, "items": []}


async def get_user(
    user_id: Annotated[str, Param()],
    auth: Annotated[str, Header("authorization")],
) -> dict[str, str]:
    return {"id": user_id, "token": auth}


async def whoami(request: Request) -> dict[str, str]:
    return {"path": request.url.path}


app = create_app()
add_route(app, "POST", "/users", create_user)
add_route(app, "GET", "/users", list_users)
add_route(app, "GET", "/users/{user_id}", get_user)
add_route(app, "GET", "/whoami", whoami)
```

### Param markers

```python
def Body() -> ParamMarker: ...
def Query(name: str | None = None) -> ParamMarker: ...
def Param(name: str | None = None) -> ParamMarker: ...
def Header(name: str | None = None) -> ParamMarker: ...
```

The kind of parsing `Body()` performs is driven by the **Python type** on the
parameter, not by a `media_type=` kwarg:

| Annotated type | Body parsing |
|---|---|
| `BaseModel` subclass | `await request.json()` + `Model.model_validate(...)` |
| `dict[str, Any]` | `await request.json()` |
| `bytes` | `await request.body()` |
| `str` | `(await request.body()).decode("utf-8")` |
| any other | `HttpHandlerConfigError` at `add_route` time |

`name=` on `Query`, `Param`, and `Header` overrides the parameter name when
the URL placeholder, query key, or header differs from the Python identifier
(`Header("authorization")`, etc.). All four markers return sentinels consumed
by the pipe; they are inert outside an `Annotated[...]` slot.

### Exception filters

```python
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ajolopy.http import (
    Catch,
    ExceptionFilter,
    HttpException,
    NotFoundException,
    create_app,
)


@Catch(NotFoundException)
class NotFoundFilter(ExceptionFilter[NotFoundException]):
    async def catch(self, exc: NotFoundException, request: Request) -> Response:
        return JSONResponse({"error": "not_found", "message": exc.message}, status_code=404)


app = create_app(exception_filters=[NotFoundFilter])
```

`ExceptionFilter` is declared with PEP 695 generics
(`class ExceptionFilter[E: Exception]`) — the type parameter is informational
(lets pyright narrow `exc` inside `catch`) and not used for dispatch.
Dispatch is driven entirely by the class(es) passed to `@Catch(...)`. If
CodeQL ever flags the PEP 695 form inside this file (as it does in
`agent/tool.py`), fall back to a module-level `TypeVar("E", bound=Exception)`
— behaviour is identical.

`create_app(exception_filters=[...])` accepts either filter classes (which
are instantiated once with no constructor args at app construction time) or
pre-built instances. Mixing both is allowed.

### Built-in exception hierarchy

```python
class HttpException(Exception):
    status: int
    message: str

class BadRequestException(HttpException):     status = 400
class UnauthorizedException(HttpException):   status = 401
class ForbiddenException(HttpException):      status = 403
class NotFoundException(HttpException):       status = 404
class ConflictException(HttpException):       status = 409
class UnprocessableEntityException(HttpException): status = 422
class InternalServerErrorException(HttpException): status = 500
```

Every subclass accepts `message: str` and an optional `details: object`
forwarded into the response body.

## Design rules

- **Magical default**: a handler annotated with `Annotated[Dto, Body()]`
  parses, validates, and injects the model with zero extra wiring. A bare
  `request: Request` parameter receives the raw Starlette request. Returning
  a `dict` produces a `JSONResponse`; returning a Pydantic model serialises
  via `model_dump()`; returning a Starlette `Response` is forwarded verbatim.
- **Escape hatches**:
  - Accept `request: Request` (and/or `response: Response`) and ignore the
    pipe entirely.
  - Override `ValidationPipe` (subclass + `app = create_app(pipe=MyPipe())`)
    when the default Pydantic-only coercion is not enough.
  - Register custom `ExceptionFilter`s — order is "most specific class wins,
    last-registered breaks ties".
  - Pass `routes=[...]` or `lifespan=...` to `create_app(...)` to drop
    straight into Starlette's native APIs.
- **No DI here.** Handlers in this item are plain callables. AJ-10 / AJ-14
  add the DI wrapper that resolves constructor params for `@Controller`
  classes.
- **One pipe, one filter pipeline.** The pipe runs **once per request**
  before the handler; filters run **once per uncaught exception**. No
  per-route middleware stack in this item — guards (AJ-17) and DI lifetimes
  (AJ-14) extend the model in later items.
- **Sync and async handlers both work.** Async handlers are awaited
  directly; sync handlers are dispatched via `asyncio.to_thread` so they
  cannot block the event loop. This mirrors `@Tool`'s sync/async support
  and matches NestJS's transport-agnostic stance.
- **Filter dispatch.** The framework walks the raised exception's MRO
  outward (most specific class first). At each class, it picks the
  **last-registered** filter that `@Catch`-ed that class. This means: more
  specific filters win, and within a single class the later registration
  overrides the earlier (predictable override at app composition time).

## Out of scope for this item

- `@Get`, `@Post`, `@Put`, `@Patch`, `@Delete` method decorators → `AJ-16`.
- `@Controller` class decorator + class-level routing → `AJ-10`.
- `@UseGuards` middleware → `AJ-17`.
- `@Stream` SSE response helper → `AJ-3` (this item ships the plumbing so
  that handlers returning Starlette streaming responses are forwarded
  unchanged).
- DI integration (`AjolopyFactory`, container) → `AJ-14`.
- OpenAPI / Swagger generation. Brief defers to v0.2.
- WebSockets and `lifespan` background tasks beyond the trivial forwarding
  of Starlette's own `lifespan` parameter.
- Multipart / file uploads. v0.1 ships JSON bodies only; multipart lands
  with a dedicated post-v0.1 item.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All HTTP tests use `starlette.testclient.TestClient`
(synchronous wrapper around the ASGI app — no real network).

### `create_app()` / `add_route()`

- [ ] `create_app()` returns a Starlette `Starlette` instance with the
      framework's default exception filters already registered (one for
      `HttpException`, one for `pydantic.ValidationError`, one catch-all
      for `Exception`).
- [ ] `add_route(app, method, path, handler)` registers the handler under
      the given method/path; a `TestClient(app)` call to that route returns
      the handler's response.
- [ ] `add_route` accepts `method` in any case (`"post"`, `"POST"`) and
      rejects unknown verbs with `HttpHandlerConfigError`.
- [ ] An `async def` handler is awaited directly; a sync `def` handler is
      dispatched via `asyncio.to_thread` (verified by patching
      `asyncio.to_thread` and asserting it was called once per request).
- [ ] `create_app(routes=[Route("/raw", raw_handler)])` forwards extra
      routes to Starlette unchanged (escape hatch).

### Param decorators — body

- [ ] `Annotated[Dto, Body()]` where `Dto` is a Pydantic `BaseModel`
      causes the request body to be parsed as JSON and validated; the
      handler receives the model instance.
- [ ] A request whose JSON body fails Pydantic validation produces a
      `422` response whose JSON body matches the structure
      `{"statusCode": 422, "error": "Unprocessable Entity",
      "message": "Validation failed", "details": [...]}` where `details`
      is `ValidationError.errors()`.
- [ ] A request whose body is **not** valid JSON when a Pydantic model
      body is expected produces a `400` response with
      `error == "Bad Request"` and the same envelope (no `details`).
- [ ] `Annotated[bytes, Body()]` receives the raw bytes without JSON
      parsing.
- [ ] `Annotated[str, Body()]` receives the body decoded as UTF-8.
- [ ] `Annotated[dict[str, Any], Body()]` receives the parsed JSON object
      without Pydantic validation.
- [ ] An `Annotated[<unsupported-type>, Body()]` (e.g. an arbitrary
      non-BaseModel class) raises `HttpHandlerConfigError` at `add_route`
      time naming the parameter and supported types.
- [ ] Two `Body()`-annotated parameters on the same handler raise
      `HttpHandlerConfigError` at `add_route` time (at most one body per
      handler).

### Param decorators — query

- [ ] `Annotated[Dto, Query()]` where `Dto` is a Pydantic `BaseModel`
      validates the query string against the model. Missing required
      fields produce a `422` with the same error envelope as Body.
- [ ] `Annotated[int, Query()]` reads `?page=…` and coerces to `int`;
      a non-numeric value produces a `422`.
- [ ] `Annotated[int, Query("p")]` reads from `?p=…` instead of the
      parameter name.
- [ ] `Annotated[int | None, Query()]` is optional and resolves to
      `None` when absent.
- [ ] `Annotated[list[str], Query()]` collects repeated keys
      (`?tag=a&tag=b`) into the list.

### Param decorators — path

- [ ] `Annotated[str, Param()]` reads the placeholder of the same name
      from the route path (`/users/{user_id}` + parameter `user_id`).
- [ ] `Annotated[int, Param()]` coerces the captured string; a
      non-numeric capture produces a `422`.
- [ ] `Annotated[str, Param("uid")]` reads `{uid}` from the path
      regardless of the Python parameter name.
- [ ] A handler whose `Param()` name has no matching placeholder in the
      registered path raises `HttpHandlerConfigError` at `add_route` time.

### Param decorators — header

- [ ] `Annotated[str, Header("authorization")]` reads the
      `Authorization` request header (case-insensitive match).
- [ ] `Annotated[str | None, Header()]` is optional and resolves to
      `None` when absent.
- [ ] A required `Header()` value missing from the request produces a
      `400` with `error == "Bad Request"`.

### Mixed parameters & raw access

- [ ] A handler with `Annotated[Dto, Body()]`,
      `Annotated[int, Param()]`, and `request: Request` (no marker)
      receives all three correctly.
- [ ] A handler with **only** `request: Request` runs the pipe as a
      no-op and forwards the raw request.

### Response handling

- [ ] Returning a `dict` produces a `JSONResponse` with the dict body.
- [ ] Returning a Pydantic `BaseModel` produces a `JSONResponse` whose
      body equals `model.model_dump(mode="json")`.
- [ ] Returning a Starlette `Response` is forwarded verbatim (no
      re-serialisation, status preserved).
- [ ] Returning a Starlette `StreamingResponse` is forwarded verbatim and
      the framework consumes the body as a stream (no buffering — verified
      with a generator that yields chunks observable in TestClient's
      streamed read). This is the hook AJ-3 (`@Stream`) builds on.
- [ ] Returning `None` produces a `204 No Content` response.

### Exception filters

- [ ] An uncaught `HttpException` subclass with `status=404` produces a
      `404` response with the default envelope
      `{"statusCode": 404, "error": "Not Found", "message": "<exc.message>"}`.
- [ ] An `HttpException` raised with a `details=` object surfaces that
      object under the envelope's `"details"` key.
- [ ] A `@Catch(NotFoundException)` filter registered on the app
      overrides the default for that exception class only; sibling
      exception classes still go through the default handler.
- [ ] Filter dispatch picks the most specific class first
      (`@Catch(NotFoundException)` wins over `@Catch(HttpException)` for
      a `NotFoundException` instance) by walking the exception's MRO.
- [ ] `@Catch` accepts multiple classes:
      `@Catch(NotFoundException, ConflictException)` registers the filter
      for both.
- [ ] When two filters declare `@Catch` on the same class, the one
      registered later in `exception_filters=[...]` wins.
- [ ] An uncaught non-`HttpException` exception is logged via the
      framework's logger at `ERROR` level (verified with `caplog`) and
      produces a `500` with the envelope
      `{"statusCode": 500, "error": "Internal Server Error",
      "message": "Internal Server Error"}` (the original exception
      message is **not** leaked to the response body).
- [ ] `@Catch()` with no argument raises `ExceptionFilterConfigError`
      at decoration time.
- [ ] A class decorated with `@Catch(...)` that does not subclass
      `ExceptionFilter` raises `ExceptionFilterConfigError` at
      decoration time.

### ValidationPipe escape hatch

- [ ] `create_app(pipe=MyPipe())` swaps in a subclass of
      `ValidationPipe` for the default; a custom pipe that returns a
      hardcoded model is observed by the handler.
- [ ] The `Pipe` ABC exposes a single async method
      `transform(value: Any, *, param: ResolvedParam) -> Any`; the default
      `ValidationPipe` is the only implementation shipped in this item.

### Negative cases

- [ ] An `Annotated[...]` parameter with two markers
      (`Annotated[str, Query(), Header()]`) raises
      `HttpHandlerConfigError` at `add_route` time.
- [ ] An untyped parameter with a marker
      (`def handler(x = Body())`) raises `HttpHandlerConfigError`.
- [ ] A handler with a parameter whose type pyright cannot serialise
      (e.g. an unresolvable forward reference) raises
      `HttpHandlerConfigError` at `add_route` time.

## Implementation pointers

- Source: `src/ajolopy/http/` (new package).
  - `__init__.py` — public re-exports.
  - `app.py` — `create_app()`, `add_route()`, default filter wiring.
  - `params.py` — `Body`, `Query`, `Param`, `Header` marker constructors
    plus the `ParamMarker` ABC.
  - `pipes.py` — `Pipe` ABC + `ValidationPipe` default implementation.
  - `filters.py` — `ExceptionFilter` ABC, `@Catch(...)`, filter registry.
  - `exceptions.py` — `HttpException` + canonical subclasses.
  - `introspect.py` — handler signature scanner that maps parameters to
    resolvers (Body / Query / Param / Header / Request / Response).
  - `errors.py` — framework-side errors (`HttpHandlerConfigError`,
    `ExceptionFilterConfigError`).
- Tests: `tests/http/` with one file per concern
  (`test_app.py`, `test_body.py`, `test_query.py`, `test_param.py`,
  `test_header.py`, `test_filters.py`, `test_pipe.py`, `test_response.py`,
  `test_negative.py`).
- Runtime deps to add via `uv add`: **`starlette`** (>=0.41, MIT). The
  PR description must justify the addition and confirm no known CVEs
  against the pinned version.
- Dev deps to add via `uv add --dev`: **`httpx`** (already transitive via
  `anthropic`, but Starlette's `TestClient` imports it as a direct
  requirement — pin it explicitly so the test suite does not depend on
  a transitive). MIT-compatible.

## Implementation notes

- _(populated during implementation — record scope decisions, deviations,
  coverage numbers per existing spec convention)._
