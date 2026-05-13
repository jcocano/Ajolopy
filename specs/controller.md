# AJ-10 — `@Controller` decorator (HTTP route binding with prefix)

> Tracked in [`board.json`](../board.json) as `AJ-10`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (framework primitives — the
> three foundational decorators `@Module` / `@Injectable` / `@Controller`)
> and `08 - Foundation - DI Módulos y HTTP` §`@Controller para endpoints
> no-streaming`. If this file conflicts with the Brief or doc 08, those win.

## What

`@Controller(prefix)` is the third foundational decorator, last in the
`@Module` / `@Injectable` / `@Controller` triad that Brief v4.0 locks
as the framework primitives. It is a class decorator that:

1. Stamps a path prefix (`__ajolopy_route_prefix__`) on the class.
2. Marks the class as an HTTP entry point so `mount_routes` (AJ-16)
   knows to concatenate the prefix with each method-level path before
   registering routes.

Method-level decorators (`@Get` / `@Post` / `@Put` / `@Patch` /
`@Delete` — shipped in AJ-16) already stamp their per-method
metadata. AJ-10 layers the class-level prefix on top so users can
write `@Controller("/users")` once instead of repeating `/users` in
every method.

This item ships:

- The `Controller(prefix)` decorator + prefix-shape validation.
- An updated `mount_routes(app, items)` so that when an item is a
  class decorated with `@Controller`, the prefix is concatenated
  with each method-level path.
- The `__ajolopy_route_prefix__` attribute contract.

This item does **not** ship:

- The route registration itself (AJ-15's `add_route` + AJ-16's
  `mount_routes` already do that).
- DI for controller construction (AJ-8's `compile_module` registers
  controllers as singletons in the container; AJ-11 resolves them).
- Streaming routes (AJ-3 ships `@Stream` and `mount_streams`; AJ-10
  is non-streaming only, matching doc 08).

## Why

Brief v4.0 §02 locks the three foundational decorators. With AJ-8
(`@Module`) and AJ-9 (`@Injectable`) shipped, AJ-10 closes the triad.

Doc 08's first HTTP snippet uses `@Controller("/users")` with method
decorators inside; users coming from NestJS expect this exact spelling.
The method decorators alone (AJ-16) already work, but every method
having to spell `/users/{user_id}` instead of `/{user_id}` is ergonomic
debt the Brief specifically calls out.

AJ-10 also unblocks **AJ-49** (reference docs for the 10 primitives) —
the documentation cannot ship without the third framework decorator's
final shape.

## Public surface (v0.1)

```python
from typing import Annotated
from pydantic import BaseModel

from ajolopy import Controller, Get, Post, compile_module
from ajolopy.http import Body, Param, create_app
from ajolopy.routes import mount_routes


class CreateUserDto(BaseModel):
    email: str
    name: str


@Controller("/users")
class UsersController:
    @Get("/")
    async def list_users(self) -> dict[str, list[object]]:
        return {"items": []}

    @Get("/{user_id}")
    async def get_user(self, user_id: Annotated[str, Param()]) -> dict[str, str]:
        return {"id": user_id}

    @Post("/")
    async def create_user(
        self, body: Annotated[CreateUserDto, Body()]
    ) -> dict[str, str]:
        return {"id": "u_1", "email": body.email}


app = create_app()
mount_routes(app, [UsersController])
# Registered routes:
#   GET  /users/
#   GET  /users/{user_id}
#   POST /users/
```

### Signature

```python
def Controller(prefix: str = "") -> Callable[[type], type]: ...
```

### Concrete invariants

- The decorator always takes one positional `prefix` argument (string).
  `@Controller` without `()` is **not** supported (unlike `@Injectable`).
  The reason: the prefix is core to the decorator's purpose; making it
  optional invites typo'd "decorator without parens" mistakes that
  silently bind methods to an empty prefix.
- An empty-string prefix is legal (`@Controller("")`); it produces the
  same route table as the bare method decorators from AJ-16. Useful for
  controllers that own root-level endpoints.
- The prefix is normalised at decoration time:
  - Leading slash is preserved if present.
  - Trailing slash is **stripped** so `@Controller("/users/")` and
    `@Controller("/users")` produce the same effective prefix.
  - Empty string stays empty (no implicit `/`).
- Stamps `__ajolopy_route_prefix__` (the normalised prefix string) on
  the class via `cls.__dict__`. Mirrors `@Module` and `@Injectable`'s
  no-inheritance rule.

### Errors

```python
class ControllerError(RuntimeError): ...
class ControllerConfigError(ControllerError): ...
```

Raised at decoration time for:
- Non-string `prefix` argument (`@Controller(42)` etc.).
- Re-decoration of an already-`@Controller` class.

### Updated `mount_routes` behaviour

When `mount_routes(app, items)` encounters a class with
`__ajolopy_route_prefix__`, it joins the prefix to every method-level
path before calling `add_route`. The join rule:

- `prefix=""` + `path="/users"` → `/users`.
- `prefix="/users"` + `path="/"` → `/users/` (preserved — Starlette
  treats `/users/` and `/users` differently).
- `prefix="/users"` + `path="/{id}"` → `/users/{id}`.
- `prefix="/users"` + `path=""` → `/users`.

Classes without `__ajolopy_route_prefix__` continue to work exactly
as AJ-16 shipped (no prefix). The change is backwards-compatible.

## Design rules

- **Magical default**: `@Controller("/users")` is one line that fixes
  the prefix for every method below. The 90% case.
- **Escape hatch**: `@Controller("")` for root-level controllers; bare
  method decorators (no class wrapper) still work for ad-hoc routes
  on plain classes.
- **`@Controller` is `Controller`, capital-C.** Brief locks the
  spelling.
- **Prefix is just a string; no template substitution.** Path
  parameters (`{user_id}`) live on the method-level path, never the
  class-level prefix. This keeps the prefix concept simple and the
  introspection (AJ-15's `Param`/`Body`/`Query` markers) per-method.

## Open design decisions (please confirm before implementation)

1. **`Controller` requires a positional `prefix` argument; no bare
   `@Controller` form.** Unlike `@Injectable`, the prefix is the
   decorator's whole purpose; supporting a bare form invites
   confusing typos. **Agreed?**

2. **Trailing slash is stripped from `prefix`.** Two reasons: matches
   NestJS behaviour (the wedge user expects this) and prevents the
   `/users/` vs `/users` route-table foot-gun. The method-level path
   retains its own trailing-slash semantics. **Agreed?**

3. **No multiple-`@Controller` stacking.** Re-decoration raises
   `ControllerConfigError`. A class has exactly one prefix.
   **Agreed?**

4. **`__ajolopy_route_prefix__` is NOT inherited by subclasses.**
   Mirrors `@Module` and `@Injectable`. Subclassing an
   `@Controller`-decorated class does not inherit the prefix; the
   subclass must be re-decorated to count as a controller.
   **Agreed?**

5. **`mount_routes` joins prefix + method-path with simple string
   concatenation, no slash deduplication beyond the prefix's own
   trailing-slash strip.** The four join rules listed above cover
   every case the test suite exercises. We do not try to be clever
   about double-slashes inside the method path (`/users//{id}`) —
   that's the user's bug. **Agreed?**

6. **`@Controller("")` is valid and produces unprefixed routes.**
   Useful for the root controller of an app or for ad-hoc edge
   cases. We do NOT reject empty prefixes. **Agreed?**

## Out of scope for this item

- Streaming routes — AJ-3's `@Stream` + `mount_streams` already
  handle SSE endpoints separately. `@Controller` is non-streaming
  only.
- `@UseGuards` middleware — AJ-17 (separate item).
- Nested controllers / sub-routers — post-v0.1.
- WebSocket handlers — post-v0.3 per the Brief roadmap.
- Auto-discovery of controllers in a package — modules already
  declare their controllers explicitly via `@Module(controllers=[])`.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### Decorator — metadata stamping

- [ ] `@Controller("/users")` returns the class unchanged.
- [ ] The decorated class exposes `__ajolopy_route_prefix__ = "/users"`.
- [ ] `@Controller("/users/")` (with trailing slash) normalises to
      `__ajolopy_route_prefix__ = "/users"`.
- [ ] `@Controller("")` is legal and stamps the empty string.
- [ ] `@Controller(42)` raises `ControllerConfigError` at decoration
      time, naming the offending argument and its type.
- [ ] `@Controller(None)` raises `ControllerConfigError`.

### Re-decoration & inheritance

- [ ] Re-decorating an already-`@Controller` class raises
      `ControllerConfigError`.
- [ ] Subclassing a controller does NOT inherit
      `__ajolopy_route_prefix__` (verified via
      `assert "__ajolopy_route_prefix__" not in Child.__dict__`).

### `mount_routes` integration — prefix concatenation

- [ ] `@Controller("/users")` + `@Get("/")` mounts as `GET /users/`.
- [ ] `@Controller("/users")` + `@Get("/{user_id}")` mounts as
      `GET /users/{user_id}`.
- [ ] `@Controller("/users")` + `@Get("")` mounts as `GET /users`.
- [ ] `@Controller("")` + `@Get("/foo")` mounts as `GET /foo`.
- [ ] A class **without** `@Controller` (bare class with method
      decorators) continues to work as AJ-16 shipped — no prefix,
      method paths used verbatim.

### Integration with `@Module` (AJ-8) and DI

- [ ] A controller listed in `@Module(controllers=[UsersController])`
      is registered in the container, mounted via `mount_routes`
      walking `CompiledModule.controllers`, and its prefix applies.
- [ ] A controller whose `__init__` takes a DI dependency
      (`def __init__(self, db: Db): ...`) is built with the dep
      injected when the route handler resolves it. (Verified by
      hitting the route via Starlette's test client.)

### Public surface

- [ ] `from ajolopy import Controller` resolves.
- [ ] `from ajolopy.routes import Controller` (the more specific
      path) also resolves, since the decorator lives next to the
      method decorators.

## Implementation pointers

- Source: extend `src/ajolopy/routes/` (no new package — `Controller`
  belongs next to `Get` / `Post` / `Put` / `Patch` / `Delete` and
  `mount_routes`).
  - `controller.py` — the `Controller` decorator.
  - Extend `errors.py` with `ControllerError` + `ControllerConfigError`.
  - Extend `mount.py` to read `__ajolopy_route_prefix__` and join.
- Top-level `src/ajolopy/__init__.py` — re-export `Controller`.
- Tests: extend `tests/routes/` with `test_controller.py` covering
  every acceptance item. Integration tests live in
  `tests/routes/test_controller_integration.py` (Starlette test
  client + `@Module` compile).
- Runtime deps: none new. Stdlib only.
- Naming: `Controller` is the spelling, not `RestController` or
  `HTTPController`. Brief locks `@Controller`.

## Implementation notes

<!-- Filled during implementation. Capture scope decisions taken at
write time, edge-case findings, coverage numbers, and any test-only
quirks. -->
