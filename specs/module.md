# AJ-8 — `@Module` decorator (DI container root)

> Tracked in [`board.json`](../board.json) as `AJ-8`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (the three framework
> primitives) and `08 - Foundation - DI Módulos y HTTP` §`@Module` and
> §`AjolopyFactory`. If this file ever conflicts with the Brief or doc 08,
> those win.

## What

`@Module(...)` is the class decorator that groups a set of providers,
imports other modules, and decides which providers leak to importers via
`exports`. It is the **root** of the DI graph: the `AjolopyFactory.create`
bootstrap (AJ-14) walks a single root `@Module` class, compiles the
recursive graph, and produces a populated `Container` (AJ-11).

AJ-8 ships:

1. The `@Module(...)` decorator (metadata stamp on a class).
2. A `forwardRef(lambda: OtherModule)` helper for circular module imports.
3. A `compile_module(root) -> CompiledModule` function that walks the
   import graph, validates visibility, and populates a `Container`. This is
   the surface `AjolopyFactory.create` (AJ-14) will consume.
4. The error hierarchy that surrounds module composition mistakes.

AJ-8 does **not** ship `@Injectable` (AJ-9), `@Controller` (AJ-10),
lifecycle wiring (AJ-13 owns hook firing — AJ-8 just exposes the cached
singletons via `Container.iter_singletons()`, which AJ-11 already provides),
or the bootstrap glue / HTTP mount / env validation that turns a compiled
module into a running app (AJ-14).

## Why

The Brief locks in `@Module` / `@Injectable` / `@Controller` as the three
framework primitives that mirror NestJS for the wedge user. Doc 08 spells
out the surface: modules compose by `imports`, expose via `exports`, and a
single root `AppModule` is the boot artifact. AJ-11 already ships the
runtime engine (`Container`); AJ-8 puts the declarative layer on top so
applications grow as a tree of `@Module` classes instead of a script that
calls `Container.register(...)` by hand.

Splitting `@Module` from `AjolopyFactory.create` (AJ-14) is deliberate.
This PR delivers a pure, testable compilation step (`compile_module`)
without touching the HTTP server, the lifecycle hooks, the env validator,
or `app.listen()`. AJ-14 then becomes thin glue.

## Public surface (v0.1)

### Declarative API

```python
from ajolopy import Module, forwardRef
from ajolopy.di import Container

@Module(
    imports=[DatabaseModule, AuthModule],
    providers=[UserService, UserRepository],
    controllers=[UserController],
    agents=[AssistantAgent],
    workflows=[SupportTeamWorkflow],
    evals=[AssistantEval],
    exports=[UserService],
)
class UsersModule: ...


@Module(global_=True, providers=[ConfigService], exports=[ConfigService])
class ConfigModule: ...


@Module(
    imports=[
        ConfigModule,
        UsersModule,
        forwardRef(lambda: BillingModule),  # circular: BillingModule imports back
    ]
)
class AppModule: ...
```

### Programmatic API (consumed by AJ-14)

```python
from ajolopy import compile_module

compiled = compile_module(AppModule)

# compiled.container — the populated Container ready to resolve()
# compiled.controllers — flat list of controller classes (mounted by AJ-14)
# compiled.agents / .workflows / .evals — flat lists, untouched here
# compiled.module_order — modules in compile order (for lifecycle hooks)
```

### Concrete types

```python
ModuleClass = type  # any class decorated with @Module

class CompiledModule:
    container: Container
    controllers: list[type]
    agents: list[type]
    workflows: list[type]
    evals: list[type]
    module_order: list[ModuleClass]


def Module(
    *,
    imports: list[ModuleClass | ForwardRef] | None = None,
    providers: list[type] | None = None,
    controllers: list[type] | None = None,
    agents: list[type] | None = None,
    workflows: list[type] | None = None,
    evals: list[type] | None = None,
    exports: list[type] | None = None,
    global_: bool = False,
) -> Callable[[type], type]: ...


def forwardRef(thunk: Callable[[], ModuleClass]) -> ForwardRef: ...


def compile_module(
    root: ModuleClass,
    *,
    container: Container | None = None,
) -> CompiledModule: ...
```

### Errors

```python
class ModuleError(RuntimeError): ...
class ModuleConfigError(ModuleError): ...        # decorator misuse at definition time
class NotAModuleError(ModuleError): ...          # @Module(imports=[NotDecorated])
class ModuleVisibilityError(ModuleError): ...    # provider resolved from non-exporting import
class CircularModuleImportError(ModuleError): ... # cycle without forwardRef
class UnresolvedForwardRefError(ModuleError): ... # thunk returned non-module
class DuplicateProviderError(ModuleError): ...   # same token registered twice across the graph
```

Every error message names the offending module class and (for the cycle /
visibility cases) prints the full module path.

## Design rules

- **Magical default**: `@Module(providers=[Foo], exports=[Foo])` is the
  one-line declaration. Importing modules see only what's in `exports`.
  Internals stay private.
- **Escape hatches**:
  - `global_=True` for cross-cutting modules (`ConfigModule`,
    `LoggerModule`) that every other module wants without re-importing.
  - `forwardRef(lambda: OtherModule)` for the rare circular import.
  - Pass a custom `Container` instance to `compile_module(root, container=...)`
    if the application needs to pre-seed providers (e.g. tests that mock a
    leaf service).

- **Module classes are metadata-only.** The class body itself is never
  instantiated by the framework. `@Module` stamps a `_ajolopy_module`
  attribute (frozen dataclass of the kwargs) on the class and returns it
  untouched. Tests should be able to assert `MyModule._ajolopy_module.imports`.

- **`providers=[Foo]` registers `Foo` into the container automatically.**
  If `Foo` has the `__ajolopy_scope__` attribute (set later by AJ-9's
  `@Injectable`), the compiler uses that scope; otherwise the scope
  defaults to `"singleton"`. This lets AJ-8 land before AJ-9 without a
  blocking dependency in the runtime (AJ-9 only adds the decorator that
  stamps the scope attribute; everything else already works).

- **`controllers=[Foo]`, `agents=[Foo]`, `workflows=[Foo]`, `evals=[Foo]`
  also register `Foo` as providers** (so they can be resolved with
  dependencies injected). The compiler additionally collects them into
  their respective `CompiledModule` list so downstream items (AJ-14 for
  controllers, future agent/workflow/eval mounters) can iterate them.

- **`exports=[Foo]` requires `Foo` to be in `providers` (or in a
  re-exported imported module — see open decision #3 below).** Exporting
  a token the module doesn't own raises `ModuleConfigError` at decoration
  time.

- **Visibility is enforced at compile time, not at runtime.** The compiler
  builds, for each module, the set of tokens it can resolve (own providers
  ∪ exports of direct imports ∪ all providers of global modules). During
  the populate phase, each module's providers are registered with the
  container under the full visibility set; the compiler validates that
  every `__init__` dependency of every provider in the module is
  resolvable from its visibility set, **before** the container is used.

- **Single flat container, not per-module sub-containers.** Doc 08's
  `Container` is a single object. The compiler enforces visibility on the
  declarative graph; at runtime, every registered provider lives in the
  same container. This keeps `resolve()` cheap and aligns with AJ-11's
  shipped semantics.

- **No automatic class introspection of module bodies.** A class becomes a
  module only via the `@Module(...)` decorator. The compiler refuses to
  treat any class without `_ajolopy_module` as an importable module
  (`NotAModuleError`). This prevents typos and shadow modules.

## Open design decisions (please confirm before implementation)

1. **`@Module` is `Module` (capital M, kwargs-only).** Following the
   Brief's primitive naming (`@Module`, `@Injectable`, `@Controller`,
   `@Agent`…) — capitalised, decorator-style. All seven knobs are
   keyword-only (`imports=`, `providers=`, `controllers=`, `agents=`,
   `workflows=`, `evals=`, `exports=`, plus `global_=`). The trailing
   underscore on `global_` mirrors `dataclasses.replace`. **Agreed?**

2. **Dynamic modules (NestJS `Module.forRoot()`) are post-v0.1.** Their
   primary use case is parameterised configuration (`ConfigModule.forRoot({...})`),
   which Ajolopy already covers cleanly with `ConfigService` + `@Injectable`
   from AJ-12. Adding them now would balloon the surface (async dynamic
   modules, module factories, async providers) and the wedge user can
   live without them. **Agreed?** (Alternative: ship them as a thin
   `Module.forRoot(cls, **kwargs)` class method that returns a
   pre-stamped dynamic module class. ~+50 LOC, but expands the test
   matrix considerably.)

3. **Re-exporting imports — not supported in v0.1.** NestJS lets you list
   another module in `exports=` ("re-export the whole module's public
   interface"). I propose we **forbid** this in v0.1: `exports=` accepts
   only `providers` of the current module. If the caller wants to re-
   expose `OtherModule`'s exports, they import `OtherModule` and let the
   importer import both. Simpler graph, easier visibility checks.
   **Agreed?**

4. **`agents=`, `workflows=`, `evals=` are typed as `list[type]` and
   registered as singletons by default.** v0.1 doesn't ship `@Agent` as a
   class (AJ-1 ships it as a function decorator), so today the lists are
   effectively empty for any `@Agent`-style code. The module signature
   already reserves the keys to match doc 08 and to keep the public API
   stable across the v0.1 roadmap. The compiler validates the lists
   contain only `type` objects but does **not** do any further mount logic
   here — that's owned by the future items that ship those primitives.
   **Agreed?**

5. **Global modules contribute to a single "global visibility set" that
   every module sees, regardless of imports.** Two global modules are
   independent (no implicit chain between them); a global module's
   `exports=` is what every other module can resolve. A non-global module
   importing a global module via `imports=` is redundant but not an error
   (the import is a no-op). **Agreed?**

6. **`forwardRef` resolves at compile time, not at decoration time.** The
   thunk is invoked once, during `compile_module`, when the compiler
   reaches the import position. If the thunk returns a non-`@Module`
   class, raise `UnresolvedForwardRefError` with the module path. The
   reason `forwardRef` is needed at all (instead of just referencing the
   module class) is that Python evaluates decorator arguments at class
   definition time, so two modules that import each other can't both
   reference each other by name. **Agreed?**

7. **Duplicate providers across modules are an error at compile time.**
   If two modules in the same graph both have `providers=[Foo]`, the
   compiler raises `DuplicateProviderError`. NestJS lets you "shadow" a
   provider; we keep semantics tight by refusing. Workaround: only one
   module owns `Foo`; other modules import the owner. **Agreed?**

## Out of scope for this item

- `@Injectable` decorator → `AJ-9`. The compiler reads `__ajolopy_scope__`
  if it's there; otherwise defaults to `"singleton"`.
- `@Controller` decorator → `AJ-10`. `controllers=[Foo]` accepts plain
  classes today; AJ-10 will add the prefix-aware class decorator that
  controllers grow into.
- Lifecycle hook firing → `AJ-13`. AJ-13 already fires
  `on_module_init` / `on_app_bootstrap` / `on_app_shutdown` by walking
  `Container.iter_singletons()` (first-resolution order). AJ-8's
  `module_order` exists for a different consumer — AJ-14 uses it to
  mount controllers / streams / agents in a deterministic, module-graph
  order. In practice top-down module compilation usually produces a
  resolution order that matches `module_order`, but they are distinct
  artifacts: never substitute one for the other.
- `AjolopyFactory.create` bootstrap → `AJ-14`. AJ-8 stops at the
  compiled-container handoff.
- Dynamic modules (`forRoot` / `forRootAsync`) — post-v0.1.
- Re-exporting imports in `exports=` — post-v0.1.
- Auto-discovery (scan a package for `@Module` classes) — post-v0.1.
- Provider scope override per-module (NestJS allows scope at injection
  site; we keep scope on the provider class only) — post-v0.1.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### Decorator — metadata stamping

- [ ] `@Module(providers=[Foo])` returns the class unchanged.
- [ ] The decorated class exposes `_ajolopy_module` (a frozen dataclass)
      with all eight fields populated (defaults for omitted lists are
      empty tuples, not shared list instances).
- [ ] `_ajolopy_module.global_` is `False` by default and `True` when
      `global_=True` is passed.
- [ ] `@Module(providers=[], exports=[NotAProvider])` raises
      `ModuleConfigError` at decoration time naming `NotAProvider`.
- [ ] `@Module(imports=[NotAModule])` does **not** raise at decoration
      time (validation is deferred to `compile_module`, because
      `forwardRef` can legitimately reference a not-yet-decorated class).
- [ ] `@Module(providers=[None])` and `@Module(providers=["not a type"])`
      raise `ModuleConfigError` at decoration time naming the offending
      entry. Same for `controllers=`, `agents=`, `workflows=`, `evals=`,
      `exports=`, and `imports=` (with the caveat that `imports=`
      additionally accepts `ForwardRef` sentinels).
- [ ] Re-decorating a class — `@Module(...) @Module(...) class X: ...` —
      raises `ModuleConfigError` referencing the already-decorated class.
      The decorator inspects `__ajolopy_module` on the target before
      stamping.
- [ ] `_ajolopy_module` is **not** inherited by subclasses: `class B(A): ...`
      where `A` is `@Module`-decorated does not gain its parent's module
      metadata. Subclassing is allowed (the decorator returns the class
      unchanged) but subclasses must be re-decorated explicitly to count
      as modules. Verified by `assert getattr(B, "_ajolopy_module", None) is None`.
- [ ] `CompiledModule` is a frozen dataclass — mutating `compiled.controllers`
      or any other field raises `dataclasses.FrozenInstanceError`.

### `forwardRef`

- [ ] `forwardRef(lambda: SomeModule)` returns a `ForwardRef` sentinel
      object that `compile_module` recognises.
- [ ] Calling the thunk during compile yields the module class; the
      compiler proceeds as if the thunk's result was in the original
      `imports=` list.
- [ ] A thunk that returns a non-`@Module` class raises
      `UnresolvedForwardRefError` with the offending object in the
      message.
- [ ] A thunk that raises an exception surfaces as
      `UnresolvedForwardRefError` with the original exception chained.

### `compile_module` — happy path

- [ ] `compile_module(AppModule)` returns a `CompiledModule` whose
      `container` resolves every provider declared anywhere in the graph.
- [ ] Resolved singletons in the returned container are shared across
      modules (a service exported by `A` and consumed by `B` is the same
      instance both modules see).
- [ ] `module_order` lists modules in dependency order (leaves first, root
      last) — leaves of the import graph appear before the modules that
      import them.
- [ ] `controllers` / `agents` / `workflows` / `evals` are flat lists in
      the order they appear during graph traversal (stable, deterministic).
- [ ] Passing `compile_module(root, container=custom_container)` populates
      the supplied container instead of creating a fresh one.

### Visibility

- [ ] Module `A` exports `FooService`; module `B` imports `A`. Compiling a
      root that uses both succeeds. A provider in `B` whose `__init__`
      takes `FooService` resolves correctly.
- [ ] Module `A` declares `providers=[FooService, BarService]` and
      `exports=[FooService]`. Module `B` imports `A`. A provider in `B`
      whose `__init__` takes `BarService` raises `ModuleVisibilityError`
      at compile time with both modules and the offending token in the
      message.
- [ ] A module imported by two different paths (diamond import) is
      compiled exactly once; its providers are registered exactly once.
- [ ] Re-exporting (`exports=[ImportedModule]`) raises `ModuleConfigError`
      at decoration time — only providers may be exported.

### Global modules

- [ ] `@Module(global_=True, providers=[ConfigService], exports=[ConfigService])`
      compiled as part of a root graph makes `ConfigService` resolvable
      from every other module without an explicit `imports=` entry.
- [ ] Providers in a global module that are **not** exported stay private
      (consistent with non-global modules).
- [ ] Two independent global modules do not see each other's
      non-exported internals.

### Circular imports

- [ ] Two modules that mutually import each other via
      `forwardRef(lambda: ...)` compile successfully.
- [ ] Two modules that mutually import each other **without**
      `forwardRef` raise `CircularModuleImportError` at compile time,
      with the cycle path in the message.
- [ ] A module that imports itself (`@Module(imports=[forwardRef(lambda: SelfModule)])`
      where the thunk returns `SelfModule` itself) raises
      `CircularModuleImportError` with `SelfModule → SelfModule` in the
      path — self-imports never compile, with or without `forwardRef`.
- [ ] A `forwardRef` thunk that returns another `forwardRef` raises
      `UnresolvedForwardRefError` — chained forward references are not
      supported (one level only).

### Duplicate providers

- [ ] If two modules in the same graph declare `providers=[Foo]`, the
      compiler raises `DuplicateProviderError` naming both modules.
- [ ] A provider in a global module that is also listed in a non-global
      module's `providers=` raises the same error (no "global wins"
      shortcut).
- [ ] A class listed both in `providers=[Foo]` and in `controllers=[Foo]`
      of the same module is **deduped silently** — the compiler
      registers `Foo` exactly once and includes it in `CompiledModule.controllers`.
      Same dedup applies to `agents=` / `workflows=` / `evals=` overlap
      with `providers=`. The motivation: declaring a controller in
      `controllers=` already implies it can be resolved; the extra
      `providers=` entry is redundant, not contradictory.

### `__init__` resolvability — early check

- [ ] If a provider's `__init__` takes a dependency that is not in its
      module's visibility set (own providers + direct-import exports +
      globals), `compile_module` raises `ModuleVisibilityError` naming
      both the provider and the missing token, **before** any
      `container.resolve()` call is attempted.
- [ ] The same check skips parameters annotated with HTTP markers
      (`Annotated[T, Body|Query|Param|Header]`) — those are AJ-15's
      domain, not DI; the compiler treats them as runtime-resolved.

### Error cases — sanity

- [ ] `compile_module(NotAModule)` raises `NotAModuleError`.
- [ ] `compile_module(EmptyModule)` (empty `@Module()` decorator) returns
      a `CompiledModule` with an empty container and empty lists — no
      crash.
- [ ] `compile_module(root, container=<already-has-Foo>)` where the
      supplied container already has `Foo` registered and `Foo` also
      appears in the module graph raises `DuplicateProviderError` —
      pre-populated containers do not bypass the graph's own dedup
      semantics. (Use case: test setup pre-seeds mocks; the test
      module should declare an *alternative* module that owns the
      mock, not collide with a graph that owns the real `Foo`.)

## Implementation pointers

- Source: `src/ajolopy/modules/` (new package).
  - `__init__.py` — public re-exports (`Module`, `forwardRef`,
    `compile_module`, `CompiledModule`, every error class).
  - `decorator.py` — `Module(...)` + `_ajolopy_module` dataclass.
  - `forward_ref.py` — `forwardRef` sentinel and helper.
  - `compiler.py` — `compile_module` walker + visibility validator +
    container populator.
  - `errors.py` — error hierarchy listed above.
- Tests: `tests/modules/` mirroring source layout. Use small synthetic
  modules defined inside each test (no real provider deps).
- Runtime deps: none new. Stdlib + the existing `ajolopy.di` package.
- Re-export the decorator + `forwardRef` from the top-level
  `ajolopy/__init__.py` so user code writes `from ajolopy import Module,
  forwardRef`.
- Naming consistency with doc 08: `forwardRef` is camelCase by design (it
  mirrors NestJS's helper name; the wedge user comes from that world). The
  Pythonic alternative `forward_ref` would shadow `typing.ForwardRef` and
  confuse readers.

## Implementation notes

<!-- Filled during implementation. Capture scope decisions taken at write
time, edge-case findings, coverage numbers, and any test-only quirks. -->
