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

- [x] `@Controller("/users")` returns the class unchanged.
- [x] The decorated class exposes `__ajolopy_route_prefix__ = "/users"`.
- [x] `@Controller("/users/")` (with trailing slash) normalises to
      `__ajolopy_route_prefix__ = "/users"`.
- [x] `@Controller("")` is legal and stamps the empty string.
- [x] `@Controller(42)` raises `ControllerConfigError` at decoration
      time, naming the offending argument and its type.
- [x] `@Controller(None)` raises `ControllerConfigError`.

### Re-decoration & inheritance

- [x] Re-decorating an already-`@Controller` class raises
      `ControllerConfigError`.
- [x] Subclassing a controller does NOT inherit
      `__ajolopy_route_prefix__` (verified via
      `assert "__ajolopy_route_prefix__" not in Child.__dict__`).

### `mount_routes` integration — prefix concatenation

- [x] `@Controller("/users")` + `@Get("/")` mounts as `GET /users/`.
- [x] `@Controller("/users")` + `@Get("/{user_id}")` mounts as
      `GET /users/{user_id}`.
- [x] `@Controller("/users")` + `@Get("")` mounts as `GET /users`.
- [x] `@Controller("")` + `@Get("/foo")` mounts as `GET /foo`.
- [x] A class **without** `@Controller` (bare class with method
      decorators) continues to work as AJ-16 shipped — no prefix,
      method paths used verbatim.

### Integration with `@Module` (AJ-8) and DI

- [x] A controller listed in `@Module(controllers=[UsersController])`
      is registered in the container, mounted via `mount_routes`
      walking `CompiledModule.controllers`, and its prefix applies.
- [x] A controller whose `__init__` takes a DI dependency
      (`def __init__(self, db: Db): ...`) is built with the dep
      injected when the route handler resolves it. (Verified by
      hitting the route via Starlette's test client.)

### Public surface

- [x] `from ajolopy import Controller` resolves.
- [x] `from ajolopy.routes import Controller` (the more specific
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

`@Controller(prefix)` ships as a single-attribute stamp
(`__ajolopy_route_prefix__`) on the decorated class. The decorator
returns the class unchanged — no wrapping, no subclassing, no
instrumentation. `mount_routes` reads the attribute via
`get_controller_prefix(cls)` (a thin `cls.__dict__.get(...)` helper)
and joins the prefix to each method-level path before forwarding to
AJ-15's `add_route`.

### Confirmed design decisions (all six)

1. `Controller` requires a positional `prefix` argument. Bare
   `@Controller` is rejected (TypeError at call time, mirroring the
   signature). The decorator's whole purpose is the prefix; supporting
   a bare form would invite typo'd "decorator without parens" mistakes.
2. Trailing slashes are stripped at decoration time
   (`prefix.rstrip("/")`). `@Controller("/users/")` and
   `@Controller("/users")` produce the same effective prefix. A bare
   `"/"` collapses to `""` to avoid the `//` foot-gun when concatenated
   with a method-level path.
3. Re-decoration is rejected with `ControllerConfigError`, naming the
   class and its existing prefix. Detection uses `cls.__dict__`, not
   `getattr`, so a legitimate `class Child(Parent): ...` is not
   misclassified as a re-decoration of `Parent`.
4. `__ajolopy_route_prefix__` is not inherited. Subclasses must be
   re-decorated to count as controllers. Mirrors `@Module` /
   `@Injectable`.
5. `mount_routes` uses simple string concatenation
   (`prefix + method_path`) — no slash deduplication beyond the
   trailing-slash strip the decorator already applied to the prefix.
   Double slashes inside the method path itself are the user's bug.
6. `@Controller("")` is valid and produces unprefixed routes —
   useful for root-level controllers.

### Public surface

- `src/ajolopy/routes/controller.py` — the `Controller` decorator plus
  `get_controller_prefix(cls)` and the `CONTROLLER_PREFIX_ATTR`
  constant.
- `src/ajolopy/routes/errors.py` — `ControllerError` (base, extends
  `RuntimeError`) and `ControllerConfigError` (decoration-time misuse).
- `src/ajolopy/routes/mount.py` — extended to read the prefix and
  join via the new private `_join_prefix(prefix, path)` helper.
- Re-exports from `ajolopy.routes` and the top-level `ajolopy`
  package: `Controller`, `ControllerError`, `ControllerConfigError`.

### Scope decision taken at implementation time

The AJ-10 spec's join rule `prefix="/users"` + `path=""` → `"/users"`
requires the method decorators to accept an empty path. AJ-16's
`_validate_path` originally rejected the empty string at decoration
time, so the rule was unreachable as written. The fix:

- Relax `_validate_path` in `src/ajolopy/routes/decorator.py` to
  accept `path == ""`. Non-empty paths that do not start with `"/"`
  are still rejected (so Express-style relative paths still fail
  early); non-string paths now raise with a clearer
  `"must be a str"` message.
- Update AJ-16's `tests/routes/test_decorator.py::TestPathValidation`
  to mirror the new contract:
  `test_empty_path_is_accepted_for_controller_composition` replaces
  `test_empty_path_raises`, and `test_non_string_path_raises` covers
  the type-check branch.

The relaxation aligns with NestJS' `@Get()` semantics, where a
method without a path inherits the controller's prefix verbatim.
Standalone (controller-less) classes that declare `@Get("")` register
a route at the empty path — Starlette handles that as `"/"`-equivalent
at request time, so the misuse surfaces in the running app rather than
at decoration time. No other AJ-16 test changed; the rest of the
contract (relative paths, Express-style `:id`, stacking,
`@Stream` conflict) is intact.

### Tests + coverage

- `tests/routes/test_controller.py` — 35 unit tests covering metadata
  stamping, prefix normalisation, validation errors, re-decoration,
  inheritance, public surface, and API shape.
- `tests/routes/test_controller_integration.py` — 15 integration
  tests covering the four documented join rules, backwards
  compatibility (bare classes with method decorators), forwarding
  to `add_route`, duplicate detection on full paths, end-to-end via
  Starlette's `TestClient`, and `@Module` / `compile_module` /
  container DI.
- `src/ajolopy/routes/controller.py` — **100 %** statement + branch
  coverage.
- `src/ajolopy/routes/mount.py` — pre-existing AJ-16 lines (the
  `_normalise` failure paths) remain uncovered; every AJ-10 line is
  covered.
- Full suite: **830 passed**, no regressions. Repo coverage 89 %.

### Edge cases worth noting

- `Controller("/")` rstrips to `""` so a bare-slash controller does
  not silently match every prefix-less route. Documented in
  `test_leading_slash_is_preserved`.
- `Controller` uses a bound `TypeVar("_C", bound=type)` so the
  decorated class keeps its identity for static type checkers
  (`class Child(MyController): ...` no longer triggers
  `reportUntypedBaseClass`).
- `get_controller_prefix(non_class)` returns `None` instead of
  raising — keeps the helper safe to call on arbitrary objects from
  introspection / tooling code.
- The duplicate-detection key in `mount_routes` is the *full* path
  (`prefix + method_path`), so two controllers can declare the same
  method-level path under different prefixes without colliding
  (covered by
  `test_same_method_path_resolves_to_distinct_full_paths`).
- No new dependencies — stdlib only.
