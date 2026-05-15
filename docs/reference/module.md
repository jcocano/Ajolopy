# `@Module`

!!! note "Spec"
    Full specification: [`specs/module.md`](https://github.com/jcocano/ajolopy/blob/main/specs/module.md)
    · Item: `AJ-8`

## Purpose

`@Module(...)` is the class decorator that groups a set of providers,
imports other modules, declares which providers leak to importers via
`exports=`, and serves as the **root** of the DI graph that
`AjolopyFactory.create` walks at boot.

The decorator is metadata-only at definition time: it stamps a frozen
`_ajolopy_module` dataclass on the class and returns the class
unchanged. `compile_module(root)` is the pure, testable function that
walks the import graph, validates visibility, and populates a
`Container`.

Reach for `@Module` as soon as the app outgrows a single file —
NestJS-style composition for the dependency graph.

## Signature

```python
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
```

## Quick example

```python
from ajolopy import Module, compile_module, forwardRef


@Module(global_=True, providers=[], exports=[])
class ConfigModule: ...


@Module(
    providers=[],
    controllers=[],
    exports=[],
)
class UsersModule: ...


@Module(
    imports=[
        ConfigModule,
        UsersModule,
        forwardRef(lambda: BillingModule),  # break a circular import
    ],
)
class AppModule: ...


@Module(imports=[UsersModule])
class BillingModule: ...


compiled = compile_module(AppModule)
# compiled.container — populated Container ready to resolve()
# compiled.controllers / .agents / .workflows / .evals — flat lists
# compiled.module_order — modules in compile order
```

## Kwargs

| Kwarg          | Type                                       | Default      | Description |
|----------------|--------------------------------------------|--------------|-------------|
| `imports`      | `list[ModuleClass \| ForwardRef] \| None`  | `None`       | Other `@Module` classes to compose. `forwardRef(lambda: ...)` breaks circular imports. |
| `providers`    | `list[type] \| None`                       | `None`       | Classes owned by this module. Registered into the container with the scope from `@Injectable`. |
| `controllers`  | `list[type] \| None`                       | `None`       | [`@Controller`](controller.md) classes mounted via this module. |
| `agents`       | `list[type] \| None`                       | `None`       | [`@Agent`](agent.md) classes owned by this module. |
| `workflows`    | `list[type] \| None`                       | `None`       | [`@Workflow`](workflow.md) classes owned by this module. |
| `evals`        | `list[type] \| None`                       | `None`       | [`@Eval`](eval.md) suites owned by this module. |
| `exports`      | `list[type] \| None`                       | `None`       | Providers visible to importers. Must be a subset of `providers=`. |
| `global_`      | `bool`                                     | `False`      | When `True`, the module's `exports=` become resolvable from every other module without an explicit `imports=` entry. |

## Escape hatches

- **`global_=True`** for cross-cutting modules (`ConfigModule`,
  `LoggerModule`) that every other module wants without re-importing.
- **`forwardRef(lambda: OtherModule)`** for circular imports — resolves
  once during `compile_module`.
- **Custom `Container`.** Pass `compile_module(root, container=...)` to
  pre-seed providers (test mocks, etc.) into a known container.

## Common gotchas

- A class becomes a module **only** via the `@Module(...)` decorator.
  `compile_module(NotAModule)` raises `NotAModuleError`. There is no
  auto-discovery.
- `exports=` must be a subset of `providers=`. Re-exporting an
  imported module's surface is **not** supported in v0.1 — import the
  upstream module directly instead.
- Two modules declaring the same provider in the same graph raise
  `DuplicateProviderError` at compile time. Only one module owns each
  token; other modules import the owner.
- `_ajolopy_module` is **not** inherited by subclasses. Re-decorate the
  subclass if you want it to count as a module.
- `agents=` / `workflows=` / `evals=` accept `list[type]` and register
  the classes as singletons. The downstream items that mount them
  (factory, controllers, etc.) iterate these lists; `@Module` itself
  does no mount logic.

## See also

- [`@Injectable`](injectable.md) — declare per-class scope.
- [`@Controller`](controller.md) — HTTP entry points registered via
  `controllers=`.
- Spec: [`specs/module.md`](https://github.com/jcocano/ajolopy/blob/main/specs/module.md).
