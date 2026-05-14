# AJ-17 — `@UseGuards` basic auth middleware

> Tracked in [`board.json`](../board.json) as `AJ-17`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §"Production primitives — los 7
> dolores ancla" (gating endpoints), `08 - Foundation - DI Modulos y HTTP`
> ("Guards (auth) — middleware básico | v0.1"), and the existing
> `auth: bool = False` reservation in `specs/stream.md` (AJ-3). If this file
> ever conflicts with the Brief, the Brief wins.

## What

`@UseGuards` is a **class- or method-level decorator** that gates HTTP
routes (`@Controller` route methods and `@Stream` handlers) behind one
or more `Guard` objects. The decorator:

1. Validates at decoration time that every argument is either a `Guard`
   subclass or an already-constructed `Guard` instance (callables are
   wrapped into a `Guard` adapter).
2. Stamps `_ajolopy_guards` metadata on the decorated target — a tuple of
   normalised `Guard` instances. Zero-arg classes are instantiated with
   `Cls()`; pre-built instances are stored verbatim.
3. Is **inert at decoration time** beyond metadata stamping. No request
   processing happens until the gated route handler runs.
4. At route mount time, the framework reads `_ajolopy_guards` from BOTH
   the host class AND the handler method, concatenates them in that
   order (class guards first, method guards second), and wraps the
   handler so each guard's `can_activate(request)` runs sequentially
   before the handler body executes.
5. A guard rejection short-circuits the request: 401 by default (or
   401/403 if the guard raised a typed exception). The handler body
   never runs.

Two built-in guards ship in v0.1:
- `BearerTokenGuard` — `Authorization: Bearer <token>` checked against
  an env-derived value.
- `IPAllowlistGuard` — remote client IP matched against a CIDR list
  with optional `X-Forwarded-For` honouring.

## Why

Brief v4.0 calls out the "deploy at 2am breaks because the endpoint was
open to the internet" dolor implicitly through dolor #1 (env vars / config
validation) and explicitly via the "Foundation" doc listing
"Guards (auth) — middleware básico" as v0.1 scope. The wedge user
(AI Engineer at a Series A startup) reaches for `@UseGuards` the moment
they ship the first `@Controller`/`@Stream` to staging: they need at
least token-based gating for internal endpoints and IP-allowlisting for
admin/debug surfaces. Today they hand-roll a `def require_token(req): ...`
Starlette middleware per project; `@UseGuards` collapses that into a
declarative class- or method-level decorator with a stable contract.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: pass an instance of `BearerTokenGuard(token_env=...)`
  or `IPAllowlistGuard(allowed=[...])` and the framework handles env
  reading, CIDR matching, and 401/403 responses.
- **Escape hatch**: subclass `Guard` and implement `can_activate()`. Any
  request-derived check is one method override away.

## Public surface (v0.1)

```python
from ajolopy import Controller, Get, Post, Stream, UseGuards
from ajolopy.guards import BearerTokenGuard, IPAllowlistGuard, Guard
from starlette.requests import Request


# Class-level: every method on the controller is gated.
@UseGuards(BearerTokenGuard(token_env="API_TOKEN"))
@Controller("/admin")
class AdminController:
    @Get("/users")
    async def list_users(self) -> list[dict]: ...

    @UseGuards(IPAllowlistGuard(allowed=["10.0.0.0/8"]))
    @Post("/users/wipe")
    async def wipe(self) -> dict:
        ...
        # Effective guards: [BearerTokenGuard, IPAllowlistGuard]


# Method-level only.
@Controller("/health")
class HealthController:
    @UseGuards(BearerTokenGuard(token_env="ADMIN_TOKEN"))
    @Get("/internals")
    async def internals(self) -> dict: ...

    @Get("/")
    async def ping(self) -> dict: ...   # no guard
```

For `@Stream`, the existing `auth=True` kwarg flips from a reservation
into a runtime requirement — the mount layer asserts that the stream
method (or its host class) carries `@UseGuards` metadata:

```python
@UseGuards(BearerTokenGuard(token_env="API_TOKEN"))
class ChatAgent:
    @Stream("/chat", auth=True)
    async def respond(self, body): ...
```

### Signatures

```python
# Decorator
GuardLike = Guard | type[Guard] | Callable[[Request], Awaitable[bool] | bool]

def UseGuards(*guards: GuardLike) -> Callable[[T], T]: ...

# ABC
class Guard(abc.ABC):
    """Base class for request-level gates."""

    @abc.abstractmethod
    async def can_activate(self, request: Request) -> bool: ...

# Built-ins
class BearerTokenGuard(Guard):
    def __init__(
        self,
        *,
        token_env: str = "API_TOKEN",
        token: str | None = None,
    ) -> None: ...
    # If `token=` is provided, the literal string is compared directly.
    # Otherwise the env var named by `token_env` is read at request time
    # (NOT at construction) so test fixtures and rotated tokens work
    # without re-instantiating the guard.

class IPAllowlistGuard(Guard):
    def __init__(
        self,
        *,
        allowed: list[str],
        trust_forwarded_for: bool = False,
    ) -> None: ...
    # `allowed` accepts host addresses ("127.0.0.1") or CIDR ranges
    # ("10.0.0.0/8", "::1/128"). Parsed once via stdlib `ipaddress` at
    # construction. `trust_forwarded_for` honours the LEFTMOST
    # `X-Forwarded-For` value when set (use only behind a known proxy).
```

### Errors

```python
class GuardError(Exception):
    """Base error raised by guards or the guard machinery."""

class GuardUnauthorizedError(GuardError):
    """Maps to HTTP 401."""

class GuardForbiddenError(GuardError):
    """Maps to HTTP 403."""

class UseGuardsConfigError(GuardError):
    """Raised at decoration / mount time when @UseGuards is misconfigured."""
```

### Guard normalisation

`@UseGuards(g)` accepts three forms; the framework normalises every one
into a `Guard` instance at decoration time:

| Form                                  | Normalisation                                            |
|---------------------------------------|----------------------------------------------------------|
| `Guard` instance (built-in or custom) | Stored verbatim.                                         |
| `type[Guard]` (zero-arg class)        | Instantiated with `Cls()`. Non-zero-arg `__init__` → `UseGuardsConfigError` pointing at "pass an instance". |
| `Callable[[Request], Awaitable[bool] | bool]` | Wrapped in `_CallableGuard(fn)` that delegates `can_activate` to the callable. Sync callables run in the event loop directly (no `to_thread`); they must NOT do I/O. |

Anything else (str, int, lambdas with wrong arity, classes that aren't
`Guard` subclasses) → `UseGuardsConfigError` at decoration time.

### Execution flow

For each gated request (method or controller-level guard present):

1. Build the effective guard list at mount time:
   `host_class_guards + method_guards`. Order is preserved.
2. Per incoming request, iterate guards sequentially:
   - `passed = await guard.can_activate(request)` (sync `can_activate`
     overrides also tolerated; framework awaits via `asyncio.iscoroutine`
     check).
   - `True` → next guard.
   - `False` (no exception) → raise `GuardUnauthorizedError("Guard
     <ClassName> denied the request")` internally; the response is 401.
   - Raised `GuardUnauthorizedError` → 401, body `{"detail": str(exc),
     "status": 401}`.
   - Raised `GuardForbiddenError` → 403, body `{"detail": str(exc),
     "status": 403}`.
   - Any other exception bubbles to the existing ExceptionFilter (AJ-15)
     and produces 500 unless the user installed a custom filter.
3. If all guards pass, the wrapped handler runs as if the guard chain
   were absent.

The response shape `{"detail": str, "status": int}` matches the existing
`HTTPException` envelope produced by AJ-15's filter pipeline; the
mapping is implemented in `ajolopy/guards/runtime.py` so the filter
catches a plain `HTTPException(status_code=401/403, detail=str)` and
serializes it.

### Hierarchical concatenation

```python
@UseGuards(AuthGuard)
@Controller("/orders")
class OrdersController:
    @Get("/")
    async def list_orders(self): ...   # effective: [AuthGuard]

    @UseGuards(AdminGuard)
    @Post("/")
    async def create(self): ...        # effective: [AuthGuard, AdminGuard]
```

Class guards run first. Method guards run second. Any failure
short-circuits and the rest of the chain (including the handler body)
does not run. A method-level `@UseGuards()` does NOT replace the class
list; it ALWAYS appends.

There is no per-route way to "skip" class-level guards in v0.1. (If a
controller needs that mix, the user should split the controller or apply
guards only at the method level.)

### `@Stream` integration

AJ-3's `@Stream` decorator reserves `auth: bool = False` with a current
`StreamConfigError` raise. AJ-17 flips that reservation:

- `@Stream(..., auth=True)` no longer raises at decoration time.
- At MOUNT time (`mount_streams`), the framework asserts that the
  decorated method OR its host class carries `_ajolopy_guards`
  metadata. If neither does, `StreamConfigError` is raised with a
  message naming the method and instructing the user to apply
  `@UseGuards(...)`.
- When guards are present, the mount layer wraps the SSE handler the
  same way it wraps controller routes: guard chain runs before the
  async-generator body. A rejection causes the framework to short-circuit
  BEFORE any `text/event-stream` headers are sent — the response is a
  normal JSON 401/403 (no SSE), matching how AJ-3 already handles
  pre-yield exceptions (see `specs/stream.md` "Error handling").

### `@Controller` and route-method integration

`@Controller` (AJ-10) wraps a class with a base path. Its route methods
(`@Get`, `@Post`, `@Put`, `@Patch`, `@Delete` from AJ-16) are mounted
via the route mounter in `ajolopy.routes.mount`. AJ-17 adds a guard
resolution step inside the mounter:

- At decoration time, `_ajolopy_guards` may be stamped on:
  - the bound method object (from method-level `@UseGuards`).
  - the class (from class-level `@UseGuards`).
- At mount time, the mounter reads both, concatenates, and wraps the
  Starlette `endpoint` callable to run the guard chain before invoking
  the original endpoint.

The wrapping is transparent to existing AJ-15 pipeline (ValidationPipe,
ExceptionFilter, param resolution): guards run AFTER request reception
but BEFORE the pipeline runs. The order is: receive → guards → pipe →
handler → filter.

### `auth=True` future-compat for `@MCPServer`

AJ-60 (`@MCPServer`) is blocked by this item. Once AJ-17 ships, AJ-60
will accept `@UseGuards(...)` on HTTP/SSE transport servers via the
same mount-time wiring. AJ-17 makes no `@MCPServer`-specific changes;
the integration lives in AJ-60.

## Design rules

- **Magical default**: drop `@UseGuards(BearerTokenGuard(token_env=...))`
  on a controller and the route is gated.
- **Escape hatch**: subclass `Guard` and override `can_activate`.
  Callables are accepted for quick custom logic.
- **No new primitive**: `@UseGuards` is a foundation feature, NOT one of
  the 11 locked primitives. (Brief lists `@Guard` as a v0.2 idea; this
  item ships only the bare `@UseGuards` + the `Guard` ABC, NOT a full
  Pipes/Interceptors/Filters middleware stack.)
- **Lifecycle inertness**: decorating does nothing at runtime; mounting
  is where the wiring lives. This keeps the import graph clean.

## Out of scope for this item

- **`@Pipe` / `@Interceptor` / `@Filter`** → Brief v0.2.
- **DI-resolved guards** (a guard whose `__init__` takes `@Injectable`
  services) → v0.2. v0.1 instantiates zero-arg classes only; instances
  with custom config must be passed pre-built.
- **OAuth / JWT validation** → v0.2 (likely an external lib).
- **Per-route "skip-class-guards" knob** → not in v0.1. Users split the
  controller if they need it.
- **Role-based decorators (`@Roles(...)`)** → v0.2.
- **Guards on `@MCPServer`** → AJ-60.
- **Guards on Workflow / Agent** (gating LLM invocations themselves) →
  not in v0.1. The HTTP-level guard is the public-facing one; protecting
  the agent itself is a separate concern.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All HTTP tests use `starlette.testclient.TestClient`;
no real network traffic in CI. The IP allowlist tests use the
`TestClient`'s `client` kwarg to control `request.client.host`.

### Decoration-time validation

- [ ] `@UseGuards(GuardSubclass)` on a class stamps `_ajolopy_guards`
      with a tuple containing one instantiated `GuardSubclass()`.
- [ ] `@UseGuards(guard_instance)` stores the instance verbatim.
- [ ] `@UseGuards(callable_fn)` wraps the callable in a `_CallableGuard`
      adapter; calling `can_activate(request)` delegates to the
      callable. Sync callables are tolerated (the adapter does NOT
      `to_thread`; sync guards must be fast).
- [ ] `@UseGuards()` with zero arguments raises `UseGuardsConfigError`
      at decoration time.
- [ ] `@UseGuards("not-a-guard")` raises `UseGuardsConfigError` listing
      accepted forms.
- [ ] `@UseGuards(GuardSubclassWithRequiredInit)` (zero-arg
      instantiation impossible) raises `UseGuardsConfigError` with a
      hint to "pass a pre-built instance".
- [ ] Decorator is composable with `@Controller`: `@UseGuards(g)` BELOW
      or ABOVE `@Controller("/x")` on the same class both work; both
      stamping orders preserve metadata.
- [ ] Decorator is composable with route method decorators (`@Get` /
      `@Post` / `@Put` / `@Patch` / `@Delete`) and with `@Stream`.

### `BearerTokenGuard`

- [ ] `BearerTokenGuard(token_env="API_TOKEN")` reads `os.environ["API_TOKEN"]`
      at request time (NOT at construction), so a test fixture that sets
      the env var AFTER the guard is built still works.
- [ ] Request with `Authorization: Bearer <correct>` → guard returns
      `True`, handler runs, 200 response.
- [ ] Request with `Authorization: Bearer <wrong>` → guard raises
      `GuardForbiddenError`, response is 403.
- [ ] Request with NO `Authorization` header → `GuardUnauthorizedError`,
      response is 401.
- [ ] Request with `Authorization: Basic ...` (wrong scheme) → 401.
- [ ] `BearerTokenGuard(token="literal")` compares against the literal,
      ignoring env vars. (Useful for tests.)
- [ ] `BearerTokenGuard(token_env="UNSET")` at request time → 401 with
      a generic message; the framework does NOT leak that the env var
      is missing.

### `IPAllowlistGuard`

- [ ] `IPAllowlistGuard(allowed=["127.0.0.1"])` accepts requests from
      `127.0.0.1`, rejects requests from `192.168.0.1` (403).
- [ ] `IPAllowlistGuard(allowed=["10.0.0.0/8"])` matches CIDR ranges.
- [ ] IPv6 host `"::1/128"` matches `::1`.
- [ ] Invalid CIDR like `"not-an-ip"` at construction raises
      `UseGuardsConfigError`.
- [ ] `trust_forwarded_for=False` (default) ignores `X-Forwarded-For`
      and checks `request.client.host`.
- [ ] `trust_forwarded_for=True` uses the LEFTMOST value of
      `X-Forwarded-For` when present (else falls back to
      `request.client.host`).
- [ ] Missing `request.client` (rare edge case in some ASGI testers)
      → 403 (treated as not-allowed).

### Hierarchical concatenation

- [ ] A class decorated with `@UseGuards(A)` whose method is also
      decorated with `@UseGuards(B)` runs `[A, B]` in order. Both must
      pass.
- [ ] Either guard can short-circuit; if `A` fails the request is
      rejected and `B.can_activate` is never called.
- [ ] A class with `@UseGuards(A)` and a method with no `@UseGuards`
      runs just `[A]`.
- [ ] A class with no `@UseGuards` and a method with `@UseGuards(B)`
      runs just `[B]`.
- [ ] Multiple guards in one decorator (`@UseGuards(A, B, C)`) run in
      argument order.

### Response shape

- [ ] 401 response body matches `{"detail": "<message>", "status": 401}`
      with `Content-Type: application/json`.
- [ ] 403 response body matches `{"detail": "<message>", "status": 403}`.
- [ ] A guard that raises an unrelated exception (e.g. `ValueError`)
      bubbles to the existing ExceptionFilter and produces a 500 by
      default (with the AJ-15 envelope).

### `@Stream(auth=True)` flip

- [ ] `@Stream("/chat", auth=True)` on a method whose host class is
      decorated with `@UseGuards(...)` mounts successfully and the
      stream is gated.
- [ ] `@Stream("/chat", auth=True)` on a method directly decorated
      with `@UseGuards(...)` (not the host) mounts successfully.
- [ ] `@Stream("/chat", auth=True)` with NO `@UseGuards` anywhere raises
      `StreamConfigError` at mount time with a message naming the
      method.
- [ ] A guard rejection on a stream endpoint returns a normal JSON
      401/403 with `Content-Type: application/json` — NO
      `text/event-stream` headers are sent.

### `@Controller` integration

- [ ] A controller-only guard rejection short-circuits BEFORE the
      route's ValidationPipe runs (verified by giving the handler a
      malformed body and confirming the response is 401, not 422).
- [ ] A method-only guard rejection short-circuits BEFORE the
      handler runs.
- [ ] Per-method guards do NOT bleed across methods on the same
      controller.

### Public re-exports

- [ ] `from ajolopy import UseGuards` works.
- [ ] `from ajolopy.guards import (Guard, BearerTokenGuard,
      IPAllowlistGuard, GuardError, GuardUnauthorizedError,
      GuardForbiddenError, UseGuardsConfigError)` works.
- [ ] `UseGuards` is added to `src/ajolopy/__init__.py`'s `__all__`
      alongside the primitive decorators.

### Negative cases

- [ ] Decorating something that's not a class OR a function with
      `@UseGuards(...)` raises `UseGuardsConfigError` at decoration
      time (e.g. trying to decorate a module-level variable).
- [ ] Two `@UseGuards(...)` decorators on the same target concatenate
      their lists in declaration order (top decorator runs LAST in
      Python decorator semantics, but the framework normalises into
      a single sequence stamped on the target).
- [ ] A `Guard` subclass whose `can_activate` is NOT async raises
      `UseGuardsConfigError` at decoration time (we don't want a
      synchronous I/O guard blocking the event loop).

## Implementation pointers

- Source: `src/ajolopy/guards/` (new package).
  - `__init__.py` — public re-exports: `Guard`, `UseGuards`,
    `BearerTokenGuard`, `IPAllowlistGuard`, errors.
  - `base.py` — `Guard` ABC, `_CallableGuard` adapter, `GuardLike`
    type alias.
  - `decorator.py` — `UseGuards(...)` factory, metadata stamping,
    normalisation helpers.
  - `builtins.py` — `BearerTokenGuard`, `IPAllowlistGuard`.
  - `errors.py` — `GuardError`, `GuardUnauthorizedError`,
    `GuardForbiddenError`, `UseGuardsConfigError`.
  - `runtime.py` — `apply_guard_chain(handler, guards)` wrapper used
    by the route and stream mount layers; maps guard exceptions to
    Starlette `HTTPException` for the AJ-15 filter pipeline.
- Cross-cut to `src/ajolopy/routes/mount.py`:
  - At mount time, read `_ajolopy_guards` from the host class AND the
    bound method; concatenate; if non-empty, wrap the endpoint with
    `apply_guard_chain`.
- Cross-cut to `src/ajolopy/stream/decorator.py`:
  - Remove the `_validate_auth` raise that pointed at AJ-17. Replace
    with a no-op (`auth=True` is allowed at decoration time).
- Cross-cut to `src/ajolopy/stream/mount.py`:
  - For each mounted stream method, if `auth=True` and the method+host
    carry NO `_ajolopy_guards` metadata, raise `StreamConfigError`.
  - If `_ajolopy_guards` are present (regardless of `auth=`), wrap the
    stream handler with `apply_guard_chain`. Guards still run for
    `auth=False` streams as long as `@UseGuards` was applied — i.e.,
    `@UseGuards` is the load-bearing primitive; `auth=True` is just
    a "did the user remember to gate this?" assertion.
- Cross-cut to `src/ajolopy/http/exceptions.py` or `filters.py`:
  - Ensure `HTTPException(status_code=401, detail=...)` and 403 pass
    through the existing filter with the JSON envelope. No new filter
    needed — Starlette / AJ-15 should already produce
    `{"detail": "...", "status": 401}` for HTTPException.
- Tests: `tests/guards/` (new).
  - `test_decorator_validation.py`
  - `test_bearer_token_guard.py`
  - `test_ip_allowlist_guard.py`
  - `test_hierarchy.py`
  - `test_response_shape.py`
  - `test_stream_integration.py`
  - `test_controller_integration.py`
  - `test_public_api.py`
  - `test_negative.py`
- Runtime deps: none new. `ipaddress` is stdlib.

## Implementation notes

(Empty — populated by the implementation PR.)
