# `@UseGuards`

!!! note "Spec"
    Full specification: [`specs/guards.md`](https://github.com/jcocano/ajolopy/blob/main/specs/guards.md)
    · Item: `AJ-17`

## Purpose

`@UseGuards` is a class- or method-level decorator that gates HTTP
routes ([`@Controller`](controller.md) methods and [`@Stream`](stream.md)
handlers) behind one or more `Guard` objects. At decoration time it
normalises every argument into a `Guard` instance and stamps
`_ajolopy_guards` metadata on the target. At route mount time the
framework wraps the handler so each guard's `can_activate(request)`
runs sequentially — class guards first, method guards second — before
the handler body executes.

Two built-in guards ship in v0.1: `BearerTokenGuard` and
`IPAllowlistGuard`. Anything else is one `Guard` subclass away.

## Signature

```python
GuardLike = Guard | type[Guard] | Callable[[Request], Awaitable[bool] | bool]

def UseGuards(*guards: GuardLike) -> Callable[[T], T]: ...
```

## Quick example

```python
from ajolopy import Controller, Get, Post, UseGuards
from ajolopy.guards import BearerTokenGuard, IPAllowlistGuard


# Class-level: every method is gated by the bearer-token guard.
@UseGuards(BearerTokenGuard(token_env="API_TOKEN"))
@Controller("/admin")
class AdminController:
    @Get("/users")
    async def list_users(self) -> list[dict[str, str]]:
        return []

    @UseGuards(IPAllowlistGuard(allowed=["10.0.0.0/8"]))
    @Post("/users/wipe")
    async def wipe(self) -> dict[str, str]:
        # Effective guards: [BearerTokenGuard, IPAllowlistGuard].
        return {"status": "wiped"}
```

## Arguments

`@UseGuards` takes a positional, variadic list of `GuardLike` items.
There are no kwargs. Each item is normalised at decoration time:

| Form                                                | Normalisation                                                                                       |
|-----------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `Guard` instance                                    | Stored verbatim.                                                                                    |
| `type[Guard]` (zero-arg class)                      | Instantiated with `Cls()`. Required-arg `__init__` → `UseGuardsConfigError`.                        |
| `Callable[[Request], Awaitable[bool] \| bool]`      | Wrapped in `_CallableGuard(fn)`; sync callables run on the event loop (no `to_thread`, no I/O).      |

Anything else (str, int, lambdas with wrong arity, classes that aren't
`Guard` subclasses) raises `UseGuardsConfigError` at decoration time.

## Escape hatches

- **Subclass `Guard`.** Implement `async def can_activate(self,
  request: Request) -> bool` for any request-level check. Return
  `True` to pass, `False` (or raise `GuardForbiddenError`) to reject.
- **Stack guards.** Class-level + method-level decorators compose;
  guards run in declaration order. Wrap a controller with
  authentication once, layer per-method authorisation on top.
- **Callable guards.** Quick demos can pass a plain function:
  `@UseGuards(lambda req: bool(req.headers.get("x-trace")))`.
- **Compose with [`@MCPServer`](mcp-server.md).** HTTP / SSE servers
  pick up the same guard chain. `transport="stdio"` rejects
  `@UseGuards` (no Request to gate).

## Common gotchas

- `GuardUnauthorizedError` maps to HTTP `401`; `GuardForbiddenError`
  maps to HTTP `403`. Returning `False` (without an exception)
  short-circuits as `401`. Pick the exception when the distinction
  matters.
- `BearerTokenGuard` reads `token_env` at **request time**, not at
  construction. Rotated tokens take effect on the next request — no
  process restart needed.
- `IPAllowlistGuard(trust_forwarded_for=True)` honours the leftmost
  `X-Forwarded-For` value. Only enable this behind a known proxy;
  otherwise clients can spoof.
- Sync callables passed via `@UseGuards(fn)` must not perform I/O.
  They run directly on the event loop; use a subclass with
  `async def can_activate` for any awaitable work.
- `@Stream(..., auth=True)` requires `@UseGuards` on the method or
  host class. Mount-time fails with a config error if the guard is
  missing.

## See also

- [`@Controller`](controller.md) / [`@Stream`](stream.md) — the
  primitives whose handlers `@UseGuards` gates.
- [`@MCPServer`](mcp-server.md) — composes with `@UseGuards` for HTTP /
  SSE transports.
- Spec: [`specs/guards.md`](https://github.com/jcocano/ajolopy/blob/main/specs/guards.md).
