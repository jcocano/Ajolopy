# AJ-16 — Method route decorators (`@Get` / `@Post` / `@Put` / `@Patch` / `@Delete`)

> Tracked in [`board.json`](../board.json) as `AJ-16`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (HTTP layer primitives) and
> `08 - Foundation - DI Modulos y HTTP` §`HTTP Layer`. If this file conflicts
> with the Brief or doc 08, those win.

## What

Five method decorators — `@Get`, `@Post`, `@Put`, `@Patch`, `@Delete`
— that mark an `async def` (or `def`) method on any class as a
non-streaming HTTP handler. Each decorator stamps a small
metadata record on the method (`_ajolopy_route`) and returns the
method unchanged. A `mount_routes(app, items)` helper walks marked
methods and registers them via `add_route` from AJ-15 — same shape
as the `mount_streams` helper AJ-3 ships.

The decorators are host-agnostic: they work on a bare class today;
AJ-10 (`@Controller`) will later wrap the same pattern with a class
decorator that adds DI integration + a `prefix=`. AJ-16 ships the
method-level surface so the HTTP layer can be exercised end to end
without waiting for the rest of the foundation chain.

## Why

Doc 08 lists `@Get` / `@Post` / `@Put` / `@Patch` / `@Delete` as the
HTTP method primitives the framework's controllers compile to.
AJ-15 already ships the underlying `add_route(app, method, path, handler)`
function; AJ-16 turns the method-on-class pattern into a one-line
decorator and gives reviewers / docs a concrete callable surface.
Splitting this from `@Controller` (AJ-10) keeps each PR focused and
makes the route-binding logic land before the DI-flavoured wrappers
need it.

## Public surface (v0.1)

```python
from typing import Annotated
from pydantic import BaseModel

from ajolopy.http import Body, Query, Param, create_app
from ajolopy.routes import Get, Post, mount_routes


class CreateUserDto(BaseModel):
    email: str
    name: str


class Users:
    @Get("/users")
    async def list_users(
        self, page: Annotated[int, Query()] = 1
    ) -> dict[str, object]:
        return {"page": page, "items": []}

    @Get("/users/{user_id}")
    async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
        return {"id": user_id}

    @Post("/users")
    async def create_user(
        self, body: Annotated[CreateUserDto, Body()]
    ) -> dict[str, str]:
        return {"id": "u_1", "email": body.email}


app = create_app()
mount_routes(app, [Users])
```

### Signatures

```python
def Get(path: str) -> Callable[[F], F]: ...
def Post(path: str) -> Callable[[F], F]: ...
def Put(path: str) -> Callable[[F], F]: ...
def Patch(path: str) -> Callable[[F], F]: ...
def Delete(path: str) -> Callable[[F], F]: ...


def mount_routes(
    app: Starlette,
    items: Iterable[type | object],
) -> None: ...
```

All five decorators take a single `path` argument. The path uses
**Starlette syntax** — `/users/{user_id}` (curly braces), not
Express-style `:user_id`. Doc 08's Express-style snippet predates
AJ-15's commitment to Starlette's pipeline; this item resolves the
ambiguity in favour of the Starlette form, which is what AJ-15's
`add_route` already consumes.

### Stamped metadata

```python
@dataclass(frozen=True, slots=True)
class RouteMetadata:
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    handler: Callable[..., Any]
```

The metadata lives at `function._ajolopy_route`. Python-level callers
(tests, `@Eval` runners, plain `await instance.list_users()`) see
the original method — the decorator is a no-op at call time.

### Mount semantics

`mount_routes(app, items)`:

1. Accepts a list of classes or pre-built instances. Classes are
   instantiated with zero args (matching `mount_streams`); required
   constructor parameters raise `RouteConfigError` pointing at
   AJ-14 for DI-driven instantiation. Pre-built instances bypass
   the check.
2. Walks each instance's MRO and pulls every method whose
   `_ajolopy_route` is set. Calls `add_route(app, metadata.method, metadata.path, bound_method)`
   per match.
3. Raises `RouteConfigError` for duplicate `(method, path)` pairs
   across the call so collisions surface at boot.

## Design rules

- **Magical default**: declare `@Get("/users")` on a method, then
  `mount_routes(app, [Users])` and the route is live. Two lines on
  top of AJ-15's `create_app`.
- **Escape hatches**:
  - Keep the bound method invocable from Python — `await users.list_users()`
    skips the HTTP framing entirely.
  - Use `add_route(app, "GET", "/users", handler)` directly to
    bypass the decorator (matches AJ-15's escape hatch).
  - Pass pre-built instances to `mount_routes(app, [users])` when
    the class needs constructor arguments.
- **No DI here.** Classes are instantiated with `Cls()`; AJ-14
  replaces the zero-arg path with full DI resolution. Constructor
  arguments raise at mount time so the bug surfaces at boot.
- **Reuses AJ-15.** All parameter resolution
  (`Body()` / `Query()` / `Param()` / `Header()`) goes through the
  existing `ValidationPipe`. The decorator stores only the
  `(method, path, function)` triple; it never reaches into the
  pipe or filter pipeline.
- **One decorator per method.** Stacking `@Get("/a") @Post("/a")`
  raises `RouteConfigError` at decoration time. Users wanting
  two methods on the same path declare two functions.
- **`@Stream` and `@Get` are mutually exclusive on one method.**
  Attempting to apply both raises `RouteConfigError` at decoration
  time with a pointer to the right primitive for streaming.

## Out of scope for this item

- `@Controller` decorator + class-level `prefix=` → `AJ-10`.
- DI-driven instantiation → `AJ-14`.
- `@UseGuards` middleware → `AJ-17`.
- OpenAPI/Swagger generation — Brief defers to v0.2.
- `create_app(controllers=[...])` kwarg — AJ-10 owns that surface.
  AJ-16 ships the explicit `mount_routes` helper only.

## Acceptance criteria

Each item must have at least one passing test before the board
item can transition to `done`. All HTTP tests use
`starlette.testclient.TestClient`.

### Decorator validation

- [x] `@Get("/users")` on a method stamps `_ajolopy_route` with
      `method="GET"`, `path="/users"`, `handler=fn` and returns the
      method unchanged.
- [x] `@Post`, `@Put`, `@Patch`, `@Delete` produce the same
      metadata shape with the right HTTP verb.
- [x] `@Get("")` and a path that does not start with `/` raise
      `RouteConfigError` at decoration time.
- [x] Two route decorators stacked on one method raise
      `RouteConfigError` at decoration time.
- [x] Applying `@Get` to a method already decorated with `@Stream`
      (or vice versa) raises `RouteConfigError` referencing the
      conflicting primitive.

### `mount_routes`

- [x] `mount_routes(app, [Users])` instantiates `Users()` and
      registers every `@Get`/`@Post`/etc-marked method via
      `add_route` (verified by patching `add_route`).
- [x] `mount_routes(app, [users])` accepts a pre-built instance
      without calling the constructor.
- [x] A class whose `__init__` needs arguments raises
      `RouteConfigError` naming the parameter and pointing at AJ-14.
- [x] A class without any route-marked method raises
      `RouteConfigError` so typos surface at boot.
- [x] Two methods across all items declaring the same
      `(method, path)` pair raise `RouteConfigError` listing both
      source qualnames.

### End-to-end via TestClient

- [x] `Get("/users")` → `client.get("/users")` returns the
      handler's response (JSON body from `dict` return).
- [x] `Get("/users/{user_id}")` → path parameter is forwarded into
      the handler via `Annotated[str, Param()]`.
- [x] `Post("/users")` → `client.post("/users", json={...})` parses
      the body through `ValidationPipe` (`Annotated[Dto, Body()]`)
      and returns the handler's response.
- [x] `Patch("/users/{user_id}")` with a Pydantic body works the
      same way; `Put` and `Delete` likewise (parametrised test).
- [x] A body whose JSON fails Pydantic validation produces the
      standard 422 envelope from AJ-15 (no custom AJ-16 path).
- [x] A handler returning a Pydantic `BaseModel` is serialised via
      `model_dump(mode="json")` (delegated to AJ-15's response
      serialiser).

### Composability with `@Stream` and `mount_streams`

- [x] A class mixing `@Stream("/chat")` (AJ-3) and `@Get("/health")`
      (AJ-16) registers both routes when called as
      `mount_streams(app, [SameClass]); mount_routes(app, [SameClass])`.
      `mount_streams` only walks `_ajolopy_stream`-marked methods;
      `mount_routes` only walks `_ajolopy_route`. They do not
      interfere.

### Negative cases

- [x] A method registered via `mount_routes` whose signature AJ-15's
      introspector cannot bind (e.g. missing annotation on a
      param-marked argument) raises `HttpHandlerConfigError` —
      propagated unchanged from AJ-15.

## Implementation pointers

- Source: `src/ajolopy/routes/` (new package).
  - `__init__.py` — public re-exports
    (`Get`, `Post`, `Put`, `Patch`, `Delete`, `mount_routes`,
    `RouteMetadata`, `RouteConfigError`).
  - `decorator.py` — the five decorators + the
    `_ajolopy_route` metadata helpers.
  - `mount.py` — `mount_routes(app, items)`.
  - `errors.py` — `RouteConfigError`.
- Tests: `tests/routes/` mirroring source layout
  (`test_decorator.py`, `test_mount.py`, `test_e2e.py`,
  `test_composability.py`, `test_negative.py`).
- Runtime deps: none new. Reuses `starlette` + AJ-15's
  `add_route` + AJ-15's `introspect_handler`.

## Implementation notes

- The five decorators (`Get` / `Post` / `Put` / `Patch` / `Delete`)
  share a single closure builder `_make_decorator(method, path)` in
  `src/ajolopy/routes/decorator.py`. Each public function only fixes
  the HTTP verb; all validation logic (path checks, stacking
  rejection, `@Stream` conflict detection) lives in one place.
- `_validate_path` rejects empty strings, paths missing the leading
  `/`, and Express-style `:param` segments. The Express check uses
  the regex `(^|/):[A-Za-z_][A-Za-z0-9_]*` so it catches `:id` at the
  start of any segment but accepts Starlette's `{id}` form
  untouched. Doc 08's `:user_id` example predates AJ-15's commitment
  to Starlette syntax; the spec resolves the ambiguity in favour of
  `{user_id}`.
- The `@Stream` conflict is detected by reading
  `STREAM_META_ATTR` from `ajolopy.stream.decorator` rather than
  duplicating the string literal — so renaming the attribute in
  either layer surfaces as a static error rather than a silent
  divergence. The symmetric direction (`@Stream` applied to a
  route-decorated coroutine) is rejected by AJ-3's own
  async-generator guard, since a `@Get`-decorated `async def` is a
  plain coroutine and `@Stream` already requires
  `inspect.isasyncgenfunction(fn)`. The test suite documents this
  asymmetry explicitly.
- `mount_routes(app, items)` forwards every marked method to AJ-15's
  `add_route`, so parameter resolution (`Body` / `Query` / `Param` /
  `Header`), pipe execution, and response serialisation are reused
  verbatim. The mount layer never reaches into `ValidationPipe` or
  the filter pipeline; it owns only discovery + dispatch.
- Duplicate `(method, path)` detection happens before the
  `add_route` call so both decorating classes' qualnames appear in
  the error message. The error format mirrors `mount_streams`.
- Per the spec, `create_app` is **not** extended with a
  `controllers=` / `routes=` kwarg. AJ-10 owns that surface; AJ-16
  ships the explicit two-line wiring (`create_app()` +
  `mount_routes(app, [...])`).
- The decorator is a no-op at call time — `await
  instance.list_users()` invokes the original coroutine with no HTTP
  framing. Verified by `tests/routes/test_composability.py::test_route_decorated_method_callable_directly`.
