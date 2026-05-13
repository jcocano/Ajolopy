# AJ-11 — DI Container core

> Tracked in [`board.json`](../board.json) as `AJ-11`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (framework primitives — the
> three foundational decorators `@Module` / `@Injectable` / `@Controller`)
> and `08 - Foundation - DI Modulos y HTTP` §`DI Container`. If this file
> ever conflicts with the Brief or doc 08, those win.

## What

`Container` is the runtime engine behind the framework's DI story. This
item ships **only** the container — registration, scope-aware resolution,
type-hint-driven dependency wiring, and circular-dependency detection.
The declarative API (`@Injectable` provider marker, `@Module` composition,
lifecycle hooks, `AjolopyFactory.create` bootstrap) lands in the items
this one unblocks (`AJ-9`, `AJ-8`, `AJ-13`, `AJ-14` respectively).

The container is a small, single-process object. Tests and
`AjolopyFactory` build one at startup; primitives that need
constructor wiring (`@Controller`, `@Agent` when AJ-14 lands) ask the
container to resolve a class instance for them.

## Why

Doc 08 calls out the foundation layer — DI, modules, HTTP — as "lo que
diferencia a Ajolopy de una librería". The Brief's wedge user (AI
Engineer at a Series A) compares the framework against NestJS, where
DI is the unspoken assumption that holds five-thousand-line services
together. Shipping the container before `@Module` keeps the surface
explicit: this PR exercises only the engine, with a synthetic test
harness that registers classes by hand, so the resolution semantics
land coherent before the declarative wrappers freeze them.

## Public surface (v0.1)

### Programmatic API

```python
from ajolopy.di import Container, Scope

container = Container()

container.register(DatabaseService, scope="singleton")
container.register(OrderRepository)            # scope defaults to "singleton"
container.register(IdGenerator, scope="transient")
container.register(RequestContext, scope="request")

# Resolve top-down: TicketService needs OrderRepository + DatabaseService.
service = container.resolve(TicketService)
assert isinstance(service, TicketService)

# Same singleton across resolves.
assert container.resolve(DatabaseService) is container.resolve(DatabaseService)

# Transient yields a fresh instance every time.
assert container.resolve(IdGenerator) is not container.resolve(IdGenerator)

# Request scope is a per-context cache.
with container.request_scope():
    a = container.resolve(RequestContext)
    b = container.resolve(RequestContext)
    assert a is b
# Outside the scope, request-scoped resolves raise.
```

### Concrete types

```python
type Scope = Literal["singleton", "request", "transient"]


class Container:
    def register(
        self,
        provider: type[T],
        *,
        scope: Scope = "singleton",
        instance: T | None = None,
        factory: Callable[[Container], T] | None = None,
    ) -> None: ...

    def resolve[T](self, token: type[T]) -> T: ...

    def request_scope(self) -> AbstractContextManager[None]: ...
    def async_request_scope(self) -> AbstractAsyncContextManager[None]: ...

    def is_registered(self, token: type) -> bool: ...
    def __contains__(self, token: type) -> bool: ...  # alias for is_registered
```

`register` accepts one of three forms — they are mutually exclusive
and the runtime check raises `ContainerConfigError` if more than one
is set:

- **class only** — the container builds the class itself by resolving
  its `__init__` dependencies recursively.
- `instance=` — a pre-built object the container uses verbatim (no
  `__init__` introspection). Always scope-singleton; passing
  `scope="transient"` with `instance=` raises.
- `factory=` — a callable `(container) -> T`; the container will
  invoke it lazily on first resolve (singleton) or every resolve
  (transient), or once per request scope (request).

### Errors

```python
class ContainerError(RuntimeError): ...
class ContainerConfigError(ContainerError): ...      # registration-time misuse
class ProviderNotRegisteredError(ContainerError): ...# resolve() of unknown token
class CircularDependencyError(ContainerError): ...   # cycle detected mid-resolve
class MissingAnnotationError(ContainerError): ...    # __init__ param has no type hint
class OutOfScopeError(ContainerError): ...           # request resolve outside scope
```

Every error message names the offending token and (for
`CircularDependencyError`) prints the full resolution stack so the
fix is obvious.

## Design rules

- **Type hints are the only injection signal.** Constructors that
  declare a parameter without a type annotation raise
  `MissingAnnotationError`. `__init__(self, *, db)` is not supported;
  match doc 08 exactly.
- **Singletons are container-scoped, not process-scoped.** Two
  containers built in the same test produce two independent
  singletons. The framework will reuse one container per running
  `AjolopyFactory` (AJ-14); nothing here cares.
- **Request scope is `contextvars`-backed.** `request_scope()` pushes
  a fresh per-context `dict[type, Any]` and pops it on exit. Async
  request handlers under `asyncio` share `contextvars` state with
  their parents inside the same task — that's the intended
  propagation. Each concurrent `asyncio.Task` gets its own scope, so
  parallel requests do not see each other's request-scoped instances.
- **`async_request_scope()` exists for symmetry with the HTTP layer.**
  It does exactly the same push/pop but yields from an async context
  manager so handlers can write
  `async with container.async_request_scope(): ...`. No background
  threads, no `asyncio.to_thread` round-trip.
- **Resolutions are not thread-safe.** Singletons are protected by a
  per-container `threading.Lock` on first creation so two threads
  resolving the same singleton race to build it once. Request scopes
  are per-context (and contextvars are not shared across threads
  unless the caller explicitly copies them), so no extra lock is
  needed there.
- **Cycle detection is per-resolution.** Each `resolve()` push the
  token onto a stack stored in a `ContextVar`; if `resolve()`
  re-encounters the same token already on the stack, raise
  `CircularDependencyError` listing the cycle (`A → B → C → A`).
- **No automatic registration.** Resolving a class that was never
  registered raises `ProviderNotRegisteredError`. The container
  refuses to silently create transient instances of "anything with
  type hints" — that would mask typos and shadow real dependencies.

## Open design decisions (please confirm before implementation)

1. **`@Injectable` lives in AJ-9, not here.** This item ships `Container`
   only; `register()` is the programmatic equivalent. The
   `@Injectable(scope="...")` decorator is a thin wrapper that
   stashes the chosen scope on the class as
   `__ajolopy_scope__`; AJ-9 reads it and calls
   `Container.register(cls, scope=cls.__ajolopy_scope__)`. Agreed?

2. **`forwardRef` belongs in AJ-8 (`@Module`), not here.** Inside a
   single `__init__`, circular dependencies between two injectables
   are a design bug — the container raises
   `CircularDependencyError`. The `forwardRef` from doc 08 is for
   *modules* importing each other, which is AJ-8's surface. Agreed?

3. **`request` scope semantics are `contextvars`-only.** No
   middleware-injected scope, no thread-local fallback. If the user
   resolves a request-scoped token outside any `request_scope()` /
   `async_request_scope()` block, the container raises
   `OutOfScopeError`. Agreed? (Alternative: silently fall back to
   transient. I think that hides bugs.)

4. **`register(factory=...)` does not get the resolution kwargs.**
   The factory receives only the container itself. If a user needs
   "build a service per request with a value computed at request
   time", they should use a request-scoped class whose `__init__`
   pulls that value from another request-scoped service. Avoids the
   trap of "what does my factory see when it runs at registration
   time vs. resolve time". Agreed?

## Out of scope for this item

- `@Injectable` decorator → `AJ-9`.
- `@Module` composition → `AJ-8`.
- Lifecycle hooks (`on_module_init` / `on_app_bootstrap` / `on_app_shutdown`)
  → `AJ-13`. The container exposes a `for instance in container.iter_singletons()`
  helper so AJ-13 can walk the cached instances to fire hooks; the
  iteration order is the order of first resolution.
- `AjolopyFactory.create` bootstrap → `AJ-14`.
- `forwardRef` for circular module imports → `AJ-8`.
- Plugin-friendly auto-discovery (scan a package for `@Injectable`
  classes) → post-v0.1.
- Generic providers (`Container.register(Generic[T])`) → post-v0.1.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### Registration

- [ ] `Container().register(MyService)` defaults scope to `"singleton"`.
- [ ] `register(MyService, scope="transient")` and `scope="request"`
      both succeed; later `resolve()` honours the scope.
- [ ] `register(MyService, scope="invalid")` raises
      `ContainerConfigError` listing the three legal scopes.
- [ ] `register(MyService, instance=obj)` stores `obj` and bypasses
      `__init__` introspection.
- [ ] `register(MyService, instance=obj, scope="transient")` raises
      `ContainerConfigError` (instance providers are inherently
      singletons).
- [ ] `register(MyService, factory=lambda c: MyService(...))`
      registers the factory; the factory is not called until
      `resolve()`.
- [ ] `register(MyService, factory=..., instance=...)` raises
      `ContainerConfigError` (mutually exclusive).
- [ ] Re-registering the same token raises `ContainerConfigError`
      unless `overwrite=True` is passed. (The kwarg lives on
      `register`; default is `False`.)
- [ ] `is_registered(MyService)` and `MyService in container` both
      return the right boolean.

### Resolution — singleton

- [ ] `resolve(DatabaseService)` returns an instance.
- [ ] Two `resolve()` calls return the same instance.
- [ ] `resolve(TicketService)` whose `__init__` takes
      `(orders: OrderRepository, cache: CacheService)` builds the
      dependencies recursively and passes them positionally.
- [ ] Re-resolving the same singleton from two different request
      scopes still returns the same instance.

### Resolution — transient

- [ ] Two `resolve()` calls return two distinct instances.
- [ ] A transient dependency injected into a singleton is **frozen**
      at the singleton's first resolution (the singleton holds one
      copy of the transient). The test makes this explicit so future
      readers don't expect "transient cascades into singletons".

### Resolution — request

- [ ] `resolve(RequestContext)` outside any `request_scope()` raises
      `OutOfScopeError` referencing the scope name.
- [ ] Inside a `with container.request_scope():` block, two
      `resolve()` calls return the same instance.
- [ ] Two **sequential** `request_scope()` blocks produce two
      distinct request-scoped instances (the scope is freshly
      pushed each time).
- [ ] Two **concurrent** `asyncio.Task`s under
      `async_request_scope()` see independent request-scoped
      instances (verified via `asyncio.gather` + assert IDs differ).
- [ ] A request-scoped service injected into a singleton service
      resolved *outside* a request scope raises `OutOfScopeError`
      with a message naming both services. (Singletons can only
      depend on singletons.)

### Resolution — errors

- [ ] `resolve(UnregisteredClass)` raises
      `ProviderNotRegisteredError` naming the class.
- [ ] A circular dependency `A → B → A` raises
      `CircularDependencyError`; the message includes the full path.
- [ ] A class whose `__init__` declares a parameter without a type
      hint raises `MissingAnnotationError` at resolution time naming
      the parameter and the class.
- [ ] A class whose `__init__` declares a parameter whose annotation
      resolves to a class the container can't introspect (e.g.
      `Annotated[str, ...]` without a marker) raises
      `MissingAnnotationError` with a hint about using a marker.
- [ ] An unresolvable forward-reference annotation
      (`__init__(self, dep: "DefinedLater")` where `DefinedLater`
      is never reachable from the class's module) raises
      `MissingAnnotationError`.

### Resolution — singleton thread safety

- [ ] Two threads racing to resolve the same singleton end up with
      the same instance, and `__init__` runs exactly once. Verified
      with a class whose `__init__` increments a class-level counter
      under a brief `time.sleep` to widen the race window.

### Lifecycle support hooks for AJ-13

- [ ] `container.iter_singletons()` yields each cached singleton
      instance in the order it was first resolved. (AJ-13 will use
      this to fire `on_module_init` and `on_app_shutdown`.)
- [ ] `container.iter_singletons()` is safe to call when no
      singletons have been resolved yet (yields zero items).

### Programmatic surface — sanity

- [ ] `Container()` constructs without args.
- [ ] `Container()` constructed in two different tests does not
      share state (no module-level globals leak between containers).

## Implementation pointers

- Source: `src/ajolopy/di/` (new package).
  - `__init__.py` — public re-exports (`Container`, `Scope`, every
    error class).
  - `container.py` — the `Container` class.
  - `errors.py` — error hierarchy listed above.
  - `_introspect.py` — small helper that reads `__init__` type hints
    via `typing.get_type_hints` and surfaces the right error class
    on each failure mode.
- Tests: `tests/di/` mirroring source layout, one test file per
  concern (`test_register.py`, `test_singleton.py`,
  `test_transient.py`, `test_request.py`, `test_errors.py`,
  `test_concurrency.py`).
- Runtime deps: none new. Stdlib `contextvars` + `threading` only.
- Naming: prefer `token` over `key` and `provider` consistently with
  doc 08. Avoid `dependency` (overloaded).

## Implementation notes

_Populated as the item is implemented._
