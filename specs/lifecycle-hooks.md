# AJ-13 — Lifecycle hooks (`on_module_init`, `on_app_bootstrap`, `on_app_shutdown`)

> Tracked in [`board.json`](../board.json) as `AJ-13`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (foundation primitives) and
> `08 - Foundation - DI Modulos y HTTP` §`Lifecycle hooks`. If this file
> conflicts with the Brief or doc 08, those win.

## What

`LifecycleManager` walks the `Container`'s cached singletons at two
well-defined moments and calls the lifecycle hooks each instance
declares:

- **`bootstrap()`** — runs after the container has resolved every
  singleton. Phase 1 invokes `on_module_init` on each singleton in
  *first-resolution order*; phase 2 invokes `on_app_bootstrap` on
  each, same order. The split lets a service finish its own setup
  before any cross-service "everything is wired" hook fires.
- **`shutdown()`** — runs `on_app_shutdown` on each singleton in
  *reverse* of first-resolution order, so dependencies stay alive
  while their dependents close.

The manager is a thin orchestrator over `Container.iter_singletons()`
(added in AJ-11). It owns no state of its own; multiple containers
each need their own manager instance.

`AjolopyFactory.create` (AJ-14) is what eventually wires this into
the app's ASGI lifespan; AJ-13 ships the manager + its tests so AJ-14
just composes the manager and the Starlette lifespan callback.

## Why

Doc 08 lists `on_module_init` / `on_app_bootstrap` /
`on_app_shutdown` as the three hooks every production app needs the
moment it grows past one service: open the DB pool before the first
request, register cross-service metrics once everything else is up,
flush queues on `SIGTERM`. Without them, framework users hand-roll
`async with database.pool():` inside every entry point. Shipping the
manager early — before AJ-14 wires it into the bootstrap — keeps the
hook-firing semantics testable and pins the ordering decisions
(forward init, reverse shutdown) in code rather than docs.

## Public surface (v0.1)

```python
from ajolopy.di import Container
from ajolopy.lifecycle import LifecycleManager


class DatabaseConnection:
    async def on_module_init(self) -> None:
        await self.pool.connect()

    async def on_app_bootstrap(self) -> None:
        await self.register_metrics()

    async def on_app_shutdown(self) -> None:
        await self.pool.close()


class CacheService:
    def on_module_init(self) -> None:    # sync is allowed
        self._ttl_table = {}


container = Container()
container.register(DatabaseConnection)
container.register(CacheService)
container.resolve(DatabaseConnection)
container.resolve(CacheService)

manager = LifecycleManager(container)
await manager.bootstrap()   # on_module_init then on_app_bootstrap
# ... app serves requests ...
await manager.shutdown()    # on_app_shutdown in reverse order
```

### Class

```python
class LifecycleManager:
    def __init__(self, container: Container) -> None: ...

    async def bootstrap(self) -> None: ...
    async def shutdown(self) -> None: ...
```

### Hook protocols (duck-typed)

The manager looks up three method names on each cached singleton:

| Method                | Phase                     | Signature                          |
|-----------------------|---------------------------|------------------------------------|
| `on_module_init`      | bootstrap phase 1         | `(self) -> None` or `async (self)` |
| `on_app_bootstrap`    | bootstrap phase 2         | `(self) -> None` or `async (self)` |
| `on_app_shutdown`     | shutdown                  | `(self) -> None` or `async (self)` |

A singleton may implement any subset. Sync methods run via
`asyncio.to_thread` so they cannot block the event loop, matching
`@Tool`'s precedent. Async methods are awaited directly.

`on_module_destroy` from doc 08 is **deferred** to v0.2 — modules are
not removable at runtime in v0.1, so the hook would never fire.

## Design rules

- **Order is from the container.** The manager calls
  `container.iter_singletons()` once at the start of each phase.
  Init/bootstrap follow that order; shutdown is its reverse. The
  manager does not re-sort by dependency depth — that would require
  re-introspecting `__init__` and would diverge from the container's
  own resolution order.
- **Sync hooks dispatched via `asyncio.to_thread`.** Lets a user
  write a quick `def on_module_init(self): self.cache = {}` without
  knowing about `async`. Matches how AJ-2 (`@Tool`) handles the same
  axis.
- **`on_module_init` errors abort `bootstrap()`.** A service that
  cannot initialise is fatal. The manager re-raises the original
  exception so the caller (`AjolopyFactory.create` in AJ-14) decides
  what to do (likely terminate the process). No partial start.
- **`on_app_bootstrap` errors also abort `bootstrap()`** for the
  same reason — if a cross-service wiring step fails, the app is
  not ready to serve.
- **`on_app_shutdown` errors are logged and skipped.** Shutdown must
  always finish; failing to close one pool should not block the
  rest. The framework's logger emits at `ERROR` with the exception
  and the offending class name. After shutdown ends, callers can
  inspect `LifecycleManager.shutdown_errors` (a list of
  `(instance_qualname, exception)` tuples) to decide whether to
  exit non-zero.
- **No concurrency between singletons in one phase.** The hooks
  fire one after the other in their respective order. Parallel
  firing would obscure ordering bugs and isn't worth the
  complexity in v0.1.

## Out of scope for this item

- `on_module_destroy` → v0.2 (no runtime module removal in v0.1).
- ASGI lifespan integration → `AJ-14` (`AjolopyFactory.create`).
- Health-check endpoints that report "ready" only after bootstrap
  → post-v0.1.
- Per-request hooks (`on_request_start`, `on_request_end`) →
  post-v0.1; the wedge user can use middleware via `@UseGuards`
  (AJ-17) for that pattern.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### Bootstrap ordering

- [ ] A container with two singletons resolved in order A → B causes
      `bootstrap()` to call `A.on_module_init`, `B.on_module_init`,
      `A.on_app_bootstrap`, `B.on_app_bootstrap` in that exact
      sequence (verified by recording call order on a fake class).
- [ ] A singleton that lacks `on_module_init` but defines
      `on_app_bootstrap` is skipped in phase 1 and called in phase 2.
- [ ] A singleton that lacks both hooks is skipped entirely.

### Sync vs async

- [ ] An `async def on_module_init` is awaited directly.
- [ ] A sync `def on_module_init` is dispatched via
      `asyncio.to_thread` (verified by patching `asyncio.to_thread`
      and asserting it was called once).
- [ ] A coroutine that returns a non-`None` value is accepted (the
      return value is discarded; we only need side effects).

### Bootstrap failure

- [ ] An exception raised inside `on_module_init` propagates from
      `bootstrap()`. Singletons after the failing one do not have
      their hooks fired.
- [ ] An exception raised inside `on_app_bootstrap` propagates from
      `bootstrap()` after phase 1 finished for every instance.

### Shutdown ordering and resilience

- [ ] `shutdown()` calls `on_app_shutdown` on each singleton in
      reverse first-resolution order.
- [ ] A singleton that raises inside `on_app_shutdown` does **not**
      stop the others. Subsequent shutdowns still run and the
      exception is logged at `ERROR` via
      `logging.getLogger("ajolopy.lifecycle")` (verified with
      `caplog`).
- [ ] After a partial-failure shutdown,
      `LifecycleManager.shutdown_errors` contains one
      `(qualname, exception)` per failed instance.
- [ ] `shutdown()` is safe to call when `bootstrap()` was never
      called (no singletons cached → no hooks → noop, returns
      normally).

### Composition with `Container`

- [ ] Singletons resolved after `bootstrap()` has already returned
      **are not** retroactively wired. Their hooks never fire (no
      "second bootstrap" semantics). The test pins this so future
      code does not silently add it.
- [ ] `LifecycleManager` does not call hooks on request-scoped or
      transient instances. Only `container.iter_singletons()` is
      consulted.
- [ ] Building two `LifecycleManager` over the same container and
      calling `bootstrap()` on both fires the hooks **twice**, in
      order, on the same instances. This is unusual but documented;
      AJ-14 will call `bootstrap()` exactly once.

## Implementation pointers

- Source: `src/ajolopy/lifecycle/` (new package).
  - `__init__.py` — public re-exports (`LifecycleManager`).
  - `manager.py` — the manager class.
  - (errors, if any, live as plain `RuntimeError` subclasses
    inside `manager.py` for now — separate `errors.py` only if the
    surface grows past one or two types).
- Tests: `tests/lifecycle/` mirroring source layout
  (`test_bootstrap.py`, `test_shutdown.py`, `test_composition.py`).
- Runtime deps: none new.

## Implementation notes

_Populated as the item is implemented._
