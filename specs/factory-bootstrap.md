# AJ-14 — `AjolopyFactory.create()` bootstrap (DI + config + lifecycle + HTTP)

> Tracked in [`board.json`](../board.json) as `AJ-14`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (framework primitives) and
> `08 - Foundation - DI Módulos y HTTP` §`AjolopyFactory — bootstrap del
> app`. If this file conflicts with the Brief or doc 08, those win.

## What

`AjolopyFactory.create(root_module)` is the **single entry point** that
takes a `@Module`-decorated root class and produces a ready-to-serve
`AjolopyApp`. It is the seam that glues every foundation piece together:

- `compile_module` from AJ-8 (DI container population).
- `LifecycleManager` from AJ-13 (on_module_init / on_app_bootstrap /
  on_app_shutdown).
- `ConfigService` from AJ-12 (env validation at startup).
- `create_app` + `mount_routes` from AJ-15 / AJ-16 (Starlette + routes).
- `mount_streams` from AJ-3 (SSE).
- Future hookpoints reserved for AJ-28 (OpenTelemetry) and AJ-29
  (structlog).

`AjolopyApp` is the artifact users call `await app.listen(port)` on.
It exposes the compiled module + container + http app for introspection
and tests; users call `await app.aclose()` (or use the async-context-
manager form) for graceful shutdown.

This item is **bootstrap glue**, not new behaviour. Every leaf component
already ships its own surface; AJ-14 wires them in the documented
order, enforces "fail fast" at startup, and gives the caller one
import line for the killer-demo Paso 1.

This item ships:

1. `AjolopyFactory.create(root: type) -> AjolopyApp` — async classmethod.
2. The `AjolopyApp` class with `listen`, `aclose`, `__aenter__` /
   `__aexit__`, and read-only properties for `compiled_module`,
   `container`, and `http` (the underlying Starlette).
3. The bootstrap pipeline that runs in a fixed order with typed
   failure modes.
4. A small CLI-friendly helper (`run(root_module, port=3000)`) so
   the `main.py` snippet from doc 08 stays at twelve lines.

This item does **not** ship:

- OpenTelemetry instrumentation → AJ-28.
- `structlog` setup → AJ-29.
- Dev-reload server (`ajolopy dev`) → AJ-33.
- The `ValidationPipe` / `HttpExceptionFilter` themselves (AJ-15
  already ships them); AJ-14 only exposes the
  `app.use_global_pipes(...)` and `app.use_global_filters(...)`
  pass-throughs that already exist in AJ-15.

## Why

Doc 08 §`AjolopyFactory` lists the seven bootstrap steps explicitly:

```
1. Lee AppModule y todos sus imports recursivamente.
2. Resuelve el DI container (todas las dependencias, en orden).
3. Inicializa providers (corre OnModuleInit hooks).
4. Registra rutas de @Controller y @Stream.
5. Inicializa observabilidad (OTel, structlog).
6. Valida el .env.
7. Llama await app.listen(port).
```

Each step lands in its own already-shipped item (AJ-8, AJ-11, AJ-13,
AJ-15 / AJ-16 / AJ-3, future AJ-28 / AJ-29, AJ-12). AJ-14 stitches
them together so the user-facing surface from the killer-demo Paso 1
becomes a single import.

Splitting bootstrap into its own item keeps every leaf testable in
isolation (which is how AJ-8 / AJ-11 / AJ-13 / AJ-15 already prove
themselves). When something breaks at startup, the failure trail is
explicit: which step failed, with what message.

## Public surface (v0.1)

### The factory

```python
from ajolopy import AjolopyFactory


async def bootstrap() -> None:
    app = await AjolopyFactory.create(AppModule)

    # Global cross-cutting concerns (pass-throughs to AJ-15).
    app.use_global_pipes(ValidationPipe())
    app.use_global_filters(HttpExceptionFilter())

    await app.listen(3000)


if __name__ == "__main__":
    import asyncio

    asyncio.run(bootstrap())
```

### The convenience helper

```python
from ajolopy import run

if __name__ == "__main__":
    run(AppModule, port=3000)
```

`run()` is the twelve-line-killer-demo helper: a `def run(root, *, port,
host)` that wraps `AjolopyFactory.create + listen` and adds SIGINT /
SIGTERM handling. Users who need finer control go through
`AjolopyFactory.create` directly.

### Concrete types

```python
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager

from starlette.applications import Starlette

from ajolopy.di import Container
from ajolopy.modules import CompiledModule


class AjolopyApp:
    @property
    def compiled_module(self) -> CompiledModule: ...

    @property
    def container(self) -> Container: ...

    @property
    def http(self) -> Starlette: ...

    # AJ-15 pass-throughs.
    def use_global_pipes(self, *pipes: object) -> None: ...
    def use_global_filters(self, *filters: object) -> None: ...

    # Lifecycle.
    async def listen(self, port: int, *, host: str = "0.0.0.0") -> None: ...
    async def aclose(self) -> None: ...

    # Async context manager.
    async def __aenter__(self) -> "AjolopyApp": ...
    async def __aexit__(self, *_: object) -> None: ...


class AjolopyFactory:
    @classmethod
    async def create(cls, root_module: type) -> AjolopyApp: ...


def run(
    root_module: type,
    *,
    port: int = 3000,
    host: str = "0.0.0.0",
) -> None: ...
```

### Errors

```python
class FactoryError(RuntimeError): ...
class FactoryConfigError(FactoryError): ...      # AppModule invalid / not @Module
class FactoryStartupError(FactoryError): ...     # any bootstrap step raised
```

`FactoryStartupError` always includes the **step name** in the message
(`"validate_env"`, `"compile_module"`, `"fire_on_app_bootstrap"`,
`"mount_routes"`, etc.) so a deploy log shows exactly which phase
exploded.

## Design rules

- **Magical default**: `AjolopyFactory.create(AppModule)` is enough.
  Twelve lines from `main.py` to a running production server, matching
  the killer-demo Paso 1.
- **Escape hatches**:
  - Pre-built `Container` injection — `AjolopyFactory.create(root,
    container=...)` for tests that pre-seed mocks (the signature
    extends `compile_module`'s existing kwarg).
  - Pre-built `Starlette` injection — `AjolopyFactory.create(root,
    http=...)` for tests that exercise the app without starting a
    real listener.
  - `AjolopyApp.http` exposes the underlying Starlette so escape-
    hatch middleware can be added directly.
- **Fail fast at startup, no half-bootstrapped state.** If any step
  fails, the factory raises `FactoryStartupError`, no listener
  starts, no resources stay allocated. `aclose()` runs on whatever
  was already initialised to release them in reverse order.
- **Lifecycle hooks fire in a deterministic order.** AJ-13 walks
  `Container.iter_singletons()` (first-resolution order); the factory
  walks `CompiledModule.module_order` in parallel so AJ-14 documents
  both contracts and uses each for what it owns.

## Open design decisions (please confirm before implementation)

1. **Bootstrap step order.** The proposed order, tighter than doc 08:

   1. `compile_module(root_module, container=...)` — build container
      with every provider registered. Failure mode:
      `CircularModuleImportError` / `DuplicateProviderError` /
      `ModuleVisibilityError` / `NotAModuleError`.
   2. **Env validation** — if `ConfigService` (AJ-12) is registered in
      the graph, resolve it once now to force its Pydantic-based
      validation. Missing required env vars fail here, before any
      hook runs.
   3. `fire_on_app_bootstrap(container)` — AJ-13's lifecycle manager
      walks `Container.iter_singletons()` and calls
      `on_app_bootstrap()` on every instance that defines it.
   4. `build_http_app()` — create the Starlette app (`create_app()`
      from AJ-15).
   5. `mount_routes(http_app, compiled.controllers)` — AJ-16, with
      AJ-10's class-level prefix applied.
   6. `mount_streams(http_app, compiled.<streams>)` — AJ-3.
   7. (Future, no-op in v0.1) Observability hookpoint reserved for
      AJ-28 + AJ-29.

   Notice the difference from doc 08: env validation happens **after**
   `compile_module` because `ConfigService` only validates when
   instantiated, and instantiation is done by the container.
   **Agreed?** (Alternative: validate env first, then compile, then
   re-resolve ConfigService — but that requires two passes through
   the container.)

2. **`AjolopyApp` lifecycle: `listen()` is async and blocks until the
   server stops.** Internally it runs `uvicorn.Server(...).serve()`.
   Cancellation propagates: `KeyboardInterrupt` / `SIGINT` /
   `SIGTERM` cancel the serve task, which triggers `aclose()` via a
   `finally:` block. **Agreed?**

3. **`aclose()` fires `on_app_shutdown` in reverse module order**,
   then disposes the HTTP app, then any provider-level `aclose()`
   methods (Gemini's `_aio_caches` cleanup from AJ-58 in particular).
   The reverse order matters: providers initialised by
   `on_app_bootstrap` must see a still-functional container when they
   shut down. **Agreed?**

4. **`run()` is the convenience helper, not the primary API.** Users
   who need DI testing, custom signal handling, or extra middleware
   go through `AjolopyFactory.create` + `app.listen` directly. `run`
   is a 4-line wrapper that uses `asyncio.run` and installs SIGINT /
   SIGTERM handlers. **Agreed?**

5. **Pre-built container/http kwargs on `AjolopyFactory.create`.**
   For tests:

   ```python
   app = await AjolopyFactory.create(AppModule, container=mock_container)
   app = await AjolopyFactory.create(AppModule, http=test_starlette)
   ```

   The container kwarg flows through to `compile_module`. The http
   kwarg replaces `create_app()` so tests do not have to start a real
   Starlette. **Agreed?**

6. **Failure mode produces typed `FactoryStartupError` with the step
   name**, original exception chained via `raise … from exc`. The
   `step` is exposed as `FactoryStartupError.step: str` so callers
   can branch on it (rare, but useful for diagnostics in
   `ajolopy doctor` later). **Agreed?**

7. **Signal handling lives in `run()`, NOT in
   `AjolopyApp.listen()`.** `listen()` is a building block that
   blocks until the server stops; the way you stop it is up to the
   caller. `run()` is the opinionated convenience that installs
   SIGINT / SIGTERM handlers + calls `aclose()` on exit. Keeps
   `listen()` testable without process-level globals. **Agreed?**

8. **Bootstrap is sync-on-the-outside, async-internally.** `create()`
   is `async` so `on_app_bootstrap` (which can be async) can await
   things during init. `run()` wraps it with `asyncio.run()` so the
   CLI snippet stays 12 lines. **Agreed?**

## Out of scope for this item

- OpenTelemetry instrumentation → AJ-28 (separate item; AJ-14 leaves a
  documented hookpoint).
- `structlog` setup → AJ-29.
- `ajolopy dev` hot-reload — AJ-33.
- Dynamic modules / module factories — post-v0.1 (the same boundary
  as AJ-8).
- Multi-app composition (two `AjolopyApp` instances in one process)
  — post-v0.1.
- Worker / multi-process mode — post-v0.1; v0.1 starts a single uvicorn
  worker.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### Happy path

- [x] `AjolopyFactory.create(AppModule)` returns an `AjolopyApp`
      with `compiled_module`, `container`, and `http` populated.
- [x] The returned app's `container` resolves every provider
      declared in `AppModule`'s graph (same invariant as
      `compile_module`'s output).
- [x] Routes from every `@Controller` in the graph are mounted with
      the AJ-10 prefix applied.
- [x] Streams from every `@Stream` in the graph are mounted via
      `mount_streams`.

### Step ordering

- [x] `compile_module` runs before env validation. (Test: `AppModule`
      missing `@Module` decorator raises `NotAModuleError` and
      `ConfigService` is never instantiated.)
- [x] Env validation runs before `on_app_bootstrap`. (Test:
      missing required env var raises `FactoryStartupError(step="validate_env")`
      and no `on_app_bootstrap` is called.)
- [x] `on_app_bootstrap` runs before HTTP mounting. (Test: a
      provider with `on_app_bootstrap` that raises prevents any
      route from being registered.)
- [x] HTTP mounting runs in the deterministic order produced by
      `CompiledModule.module_order` + `controllers` list — verified
      by inspecting registered routes after a fixed module graph.

### Failure modes

- [x] Passing a non-module root raises `FactoryConfigError` before
      any other step runs. Message names the offending class.
- [x] `compile_module` errors (`DuplicateProviderError`,
      `ModuleVisibilityError`, etc.) bubble up as
      `FactoryStartupError(step="compile_module")` with the original
      chained.
- [x] Env validation failures bubble up as
      `FactoryStartupError(step="validate_env")` with
      `pydantic.ValidationError` chained.
- [x] `on_app_bootstrap` raising bubbles up as
      `FactoryStartupError(step="fire_on_app_bootstrap")` with the
      original chained.
- [x] Route mounting failure (rare — typically a malformed
      `__ajolopy_route_path__`) bubbles up as
      `FactoryStartupError(step="mount_routes")`.

### `AjolopyApp` lifecycle

- [x] `app.listen(port=0)` (random ephemeral port) starts the
      server, can be cancelled via `task.cancel()`, and `aclose()`
      is reached via the `finally:` block.
- [x] `await app.aclose()` fires every singleton's
      `on_app_shutdown` in reverse module order, then closes the
      HTTP app, then awaits each provider's optional `aclose()`
      method (e.g. Gemini's cache registry cleanup).
- [x] Calling `aclose()` twice is idempotent (second call is a
      no-op).
- [x] `async with await AjolopyFactory.create(AppModule) as app:`
      enters the context manager, runs body, exits with `aclose()`
      fired (no `listen` involved).

### `use_global_pipes` / `use_global_filters` pass-throughs

- [x] `app.use_global_pipes(SomePipe())` reaches the underlying
      Starlette app via AJ-15's mechanism. Existing AJ-15 tests
      continue to pass when exercised through `AjolopyApp`.
- [x] `app.use_global_filters(SomeFilter())` likewise.

### Escape-hatch kwargs

- [x] `AjolopyFactory.create(AppModule, container=custom_container)`
      uses the supplied container (verified by pre-seeding a
      provider and asserting it resolves identically).
- [x] `AjolopyFactory.create(AppModule, http=custom_starlette)`
      uses the supplied HTTP app — routes mount onto it; the
      property `app.http is custom_starlette` is true.

### `run()` convenience

- [x] `run(AppModule, port=0)` starts the server, handles
      `KeyboardInterrupt` by cancelling cleanly, and exits with
      code 0 after `aclose()` runs.
- [x] `run(AppModule, port=0)` with a faulty AppModule (e.g.
      duplicate provider) exits with a non-zero status and prints
      the `FactoryStartupError` to stderr — the test runs `run` in
      a subprocess and asserts the exit code + stderr content.

### Public surface

- [x] `from ajolopy import AjolopyFactory, AjolopyApp, run` all
      resolve.
- [x] `from ajolopy.factory import AjolopyFactory` (the dedicated
      path) also resolves.

## Implementation pointers

- Source: new package `src/ajolopy/factory/` (mirrors `src/ajolopy/di/` and `src/ajolopy/modules/`).
  - `__init__.py` — public re-exports.
  - `factory.py` — `AjolopyFactory` classmethod + the bootstrap
    pipeline (one function per step so each is independently
    testable).
  - `app.py` — `AjolopyApp` class.
  - `run.py` — `run()` helper.
  - `errors.py` — `FactoryError`, `FactoryConfigError`,
    `FactoryStartupError(step: str)`.
- Top-level `src/ajolopy/__init__.py` — re-export `AjolopyFactory`,
  `AjolopyApp`, `run`.
- Tests: `tests/factory/` mirroring source layout. Use the
  pre-built `container=` and `http=` kwargs so tests do not start a
  real uvicorn unless explicitly testing `listen`. For `listen`
  tests, use port 0 + `httpx.AsyncClient` (already a dev dep).
- Runtime deps: `uvicorn` (new — Apache-2.0). PR description must
  justify the addition. Pin a recent stable; v0.30+.
- Naming: `AjolopyFactory` matches doc 08 verbatim. `AjolopyApp` is
  shorter than `INestApplication` but clearly an *Ajolopy* artifact.
  `run` is intentionally lowercase + short for the killer-demo
  snippet.

## Implementation notes

- `2026-05-13` — Shipped `src/ajolopy/factory/{factory,app,run,errors,__init__}.py`
  + `tests/factory/`. All 8 open design decisions confirmed by the
  author before coding. Decision **#1** (double validation — early
  `.env` instantiation + container re-instantiation) and **#7**
  (signal handling only in `run()`) were the two flagged for explicit
  user confirmation; the remaining six were adopted as proposed.

- **AJ-11 bug surfaced during smoke testing — fixed in this PR.**
  Pydantic-settings's `BaseSettings.__init__` uses `__pydantic_self__`
  in place of `self` (so users can declare a field named "self") and
  carries several `_`-prefixed configuration kwargs. AJ-11's
  `introspect_dependencies` did not skip either convention, so
  `Container.resolve(<BaseConfig subclass>)` failed with
  `MissingAnnotationError: parameter '__pydantic_self__'`. Fix: skip
  `__pydantic_self__` alongside `self`, plus skip every `_`-prefixed
  parameter (matches pydantic-settings's convention). Tests live in
  `tests/di/test_introspect_pydantic.py` (4 cases).

- **Eager-resolve singletons before lifecycle.** AJ-13's
  `LifecycleManager.bootstrap()` walks `Container.iter_singletons()`,
  which only yields already-cached instances. Without an explicit
  pre-resolve pass, `on_app_bootstrap` would silently fail to fire on
  providers that nothing else had resolved yet (the normal case at
  the moment ``create()`` runs). The factory's
  ``_eager_resolve_singletons`` walks ``compiled.module_order``,
  collects every owned token, and resolves each singleton once.
  Request-scoped and transient providers are skipped.

- **Stream mounting filters controllers.** `mount_streams` refuses
  classes with no `@Stream`-marked methods (would shadow a real bug).
  But `CompiledModule.controllers` includes pure-HTTP controllers
  alongside any future stream-bearing controllers. The factory filters
  via ``iter_stream_methods(cls)`` to forward only classes that carry
  at least one stream; everything else stays as a regular controller.

- **`use_global_pipes` accepts at most one pipe.** v0.1 supports
  exactly one global `Pipe`. Passing zero is a no-op (NestJS allows
  it); passing more than one raises `TypeError` immediately.

- **`set_global_pipe` is a new public seam in `ajolopy.http`.** AJ-14
  needed to swap the pipe on a running app; the previous AJ-15 API
  only let you pass a pipe at `create_app` construction. Added a
  public helper so AJ-14 does not reach into Starlette's
  `app.state.ajolopy_pipe` private attribute. AJ-15 keeps the private
  attr internal; ``set_global_pipe`` is the supported way to swap.

- **`run()` keeps signal handlers process-global.** SIGINT / SIGTERM
  are installed inside `run()` only, never inside `listen()`. Two
  reasons: (a) `listen()` stays testable without rolling back signal
  handlers between tests, and (b) advanced users who want their own
  signal handling call `AjolopyFactory.create + listen` directly. On
  Windows event loops where `add_signal_handler` is
  `NotImplementedError`, uvicorn ships its own SIGINT handler that
  still works.

- **`uvicorn` is the new runtime dependency** (Apache-2.0, version
  0.46.0). Justified by Brief v4.0's killer-demo Paso 1 contract
  (`await app.listen(port)`). No known CVEs against 0.46.0.

- **Total suite: 802 tests passing**, 89% global coverage. pyright
  strict clean, ruff (check + format) clean, `tools/board.py validate`
  clean.
