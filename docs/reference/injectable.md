# `@Injectable`

!!! note "Spec"
    Full specification: [`specs/injectable.md`](https://github.com/jcocano/ajolopy/blob/main/specs/injectable.md)
    · Item: `AJ-9`

## Purpose

`@Injectable` is the thinnest decorator in the framework. It stamps a
single attribute (`__ajolopy_scope__`) on the target class so the
[`@Module`](module.md) compiler can register the class with the right
scope when it walks a module's `providers=` list. The class is returned
unchanged — there is no runtime container interaction in the decorator
itself.

Use `@Injectable` to declare services that other classes depend on —
repositories, clients, mailers, anything you wire via constructor type
hints.

## Signature

```python
type Scope = Literal["singleton", "request", "transient"]


@overload
def Injectable(cls: type, /) -> type: ...                           # bare
@overload
def Injectable(*, scope: Scope = "singleton") -> Callable[[type], type]: ...  # parameterised
```

## Quick example

```python
from ajolopy import Injectable, Module, compile_module


@Injectable
class Logger:
    def info(self, msg: str) -> None:
        print(msg)


@Injectable(scope="singleton")
class DatabaseService:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger


@Injectable(scope="request")
class RequestContext: ...


@Module(
    providers=[Logger, DatabaseService, RequestContext],
    exports=[DatabaseService],
)
class CoreModule: ...


compiled = compile_module(CoreModule)
# compiled.container resolves DatabaseService with Logger injected.
```

## Kwargs

| Kwarg    | Type                                                 | Default        | Description |
|----------|------------------------------------------------------|----------------|-------------|
| `scope`  | `Literal["singleton", "request", "transient"]`        | `"singleton"`  | Lifetime in the container. `"singleton"` = one per process; `"request"` = one per HTTP request; `"transient"` = new instance per resolve. |

## Escape hatches

- **Bare form (`@Injectable`)** — magical default. Scope defaults to
  `"singleton"`, which is what 90% of services want.
- **Parameterised form (`@Injectable(scope="...")`)** — for the 10%
  case (request-scoped DB session, transient ID generator, ...).
- **Skip the decorator entirely.** `@Module(providers=[Foo])` registers
  `Foo` with `"singleton"` scope when `Foo` has no
  `__ajolopy_scope__`. The decorator is the **declarative** way to set
  scope; the compiler reads the attribute defensively.

## Common gotchas

- Unknown scope values raise `InjectableConfigError` at decoration
  time. The only valid strings are `"singleton"`, `"request"`,
  `"transient"`.
- `__ajolopy_scope__` is **not** inherited. Subclassing an
  `@Injectable`-decorated class does not propagate the scope — the
  subclass needs its own `@Injectable` if you want it registered.
- Re-decoration (`@Injectable @Injectable class Foo: ...`) raises
  `InjectableConfigError`. A class has exactly one scope.
- The decorator does **not** register the class anywhere by itself. The
  class must appear in some `@Module(providers=[...])` to become
  resolvable.
- `__init__` annotations drive DI. Missing annotations raise
  `MissingAnnotationError` at resolve time (via the container).

## See also

- [`@Module`](module.md) — the decorator that actually registers
  injectables into the container.
- [`@Controller`](controller.md) — controllers also resolve via the
  same DI graph.
- Spec: [`specs/injectable.md`](https://github.com/jcocano/ajolopy/blob/main/specs/injectable.md).
