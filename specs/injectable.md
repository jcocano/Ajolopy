# AJ-9 — `@Injectable` decorator (provider registration marker)

> Tracked in [`board.json`](../board.json) as `AJ-9`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §02 (framework primitives — the
> three foundational decorators `@Module` / `@Injectable` / `@Controller`)
> and `08 - Foundation - DI Módulos y HTTP` §`DI Container` / §`Scopes`. If
> this file ever conflicts with the Brief or doc 08, those win.

## What

`@Injectable` is the thinnest decorator in the framework. It stamps a
single attribute (`__ajolopy_scope__`) on the target class so the AJ-8
module compiler can register it with the right scope when it walks a
`@Module`'s `providers=` list.

The decorator works with **or** without arguments — both
`@Injectable` and `@Injectable(scope="...")` are valid — and the
class is returned unchanged. There is no runtime container interaction;
this item ships **only** the marker.

This item delivers:

1. The `Injectable` decorator that supports both bare (`@Injectable`)
   and parameterised (`@Injectable(scope="...")`) usage.
2. The `__ajolopy_scope__` attribute stamp.
3. Validation that the scope value is one of `"singleton"` / `"request"` /
   `"transient"` at decoration time.

This item does **not** ship:

- Any container registration (`@Module`'s compiler from AJ-8 already
  reads `__ajolopy_scope__` and registers via `Container.register`).
- Any introspection or resolution logic (the container handles that).
- Any dependency-injection magic beyond what `__init__` type hints
  already give us.

## Why

The Brief locks `@Module` / `@Injectable` / `@Controller` as the three
framework primitives. AJ-8 ships `@Module`; AJ-10 ships `@Controller`;
AJ-9 fills the middle slot. Doc 08 shows the decorator in every user-
facing snippet involving a service class, so the public API is locked:

```python
@Injectable(scope="singleton")
class TicketService: ...
```

Splitting `@Injectable` from `@Module` keeps the surface honest — the
module compiler already reads `__ajolopy_scope__` defensively (falls
back to `"singleton"` when missing), so AJ-9 doesn't add new runtime
behaviour, it just gives users a declarative way to set the scope.

## Public surface (v0.1)

### Three usage forms

```python
from ajolopy import Injectable

# Bare — defaults to singleton scope.
@Injectable
class Logger: ...

# Parameterised, explicit scope.
@Injectable(scope="singleton")
class DatabaseService: ...

@Injectable(scope="request")
class RequestContext: ...

@Injectable(scope="transient")
class IdGenerator: ...
```

After decoration, the class carries `__ajolopy_scope__`:

```python
assert Logger.__ajolopy_scope__ == "singleton"
assert RequestContext.__ajolopy_scope__ == "request"
```

### Signature

```python
from typing import Literal, overload

type Scope = Literal["singleton", "request", "transient"]


@overload
def Injectable(cls: type, /) -> type: ...           # bare: @Injectable

@overload
def Injectable(*, scope: Scope = "singleton") -> Callable[[type], type]: ...
                                                    # parameterised: @Injectable(scope=...)

def Injectable(
    cls: type | None = None,
    *,
    scope: Scope = "singleton",
) -> type | Callable[[type], type]: ...
```

### Errors

```python
class InjectableError(RuntimeError): ...
class InjectableConfigError(InjectableError): ...   # invalid scope, etc.
```

## Design rules

- **Magical default**: `@Injectable` (bare) is enough for the 90% case.
  The scope defaults to `"singleton"` — the most common choice in the
  Brief and doc 08.
- **Escape hatch**: `@Injectable(scope="...")` for the 10% who want
  request or transient scope.
- **Thin contract**: the decorator stamps one attribute and returns
  the class. No runtime container interaction, no introspection, no
  validation of `__init__`. Those are the container's job at resolve
  time (and AJ-11 already has typed errors for them).
- **Scope-value validation is decoration-time.** Passing an
  unrecognised scope raises `InjectableConfigError` immediately —
  before the class is even fully defined. The user fixes the typo
  without waiting for the first `compile_module(...)` call.
- **The decorator is `Injectable`, capital-I.** Follows the Brief's
  naming convention (`@Module`, `@Injectable`, `@Controller`,
  `@Agent`…). Brief locks this; do not reopen.

## Open design decisions (please confirm before implementation)

1. **Bare-decorator support — `@Injectable` and `@Injectable(scope=...)`
   are both valid.** Python distinguishes by what the decorator
   receives at decoration time: a class (bare) vs. nothing (paren-
   isation). The implementation uses an overloaded signature to keep
   typing precise. This matches doc 08's "implicit default" snippet.
   **Agreed?**

2. **Default scope is `"singleton"`.** Matches doc 08 and the
   container's default. **Agreed?**

3. **`__ajolopy_scope__` is *not* inherited.** Subclasses must be
   re-decorated to count as injectable. We check `cls.__dict__`
   instead of `getattr` so a subclass of an `@Injectable`-decorated
   class does not silently inherit the scope of its parent. This
   mirrors `@Module`'s no-inheritance rule from AJ-8 and avoids
   surprises like "I copy-pasted a class and now I have two
   `singleton` instances when I expected `transient`". **Agreed?**

4. **Re-decoration is rejected.** `@Injectable @Injectable class Foo:`
   raises `InjectableConfigError` at decoration time. The decorator
   inspects the class's own `__dict__` (not `getattr`) so subclassing
   an already-decorated class is fine, but two `@Injectable`s on the
   same class is unambiguously a bug. Mirrors `@Module`'s
   `ModuleConfigError` semantics. **Agreed?**

5. **`@Injectable` does NOT register the class anywhere.** The class
   must still appear in some `@Module(providers=[...])` to be
   resolvable. The marker only declares "if this class is in a
   module, use *this* scope". This is intentional — automatic
   registration would require global state, which the container
   explicitly avoids (Brief §02). **Agreed?**

6. **`@Injectable` does NOT validate the target class's `__init__`.**
   The container's `MissingAnnotationError` (AJ-11) covers that at
   resolve time. The marker should stay a no-cost stamp; adding
   `__init__` validation would slow class definition down and the
   container's message is already actionable. **Agreed?**

## Out of scope for this item

- Registration mechanism (`@Module`'s compiler in AJ-8 + `Container.register`
  from AJ-11 already cover this).
- `__init__` introspection (AJ-11's `Container.resolve` raises typed
  errors when annotations are missing or unresolvable).
- HTTP marker rejection (`Annotated[T, Body|Query|Param|Header]`) —
  AJ-11 covers it at resolve time, AJ-8 covers it at compile time;
  AJ-9 has no opinion.
- Multi-tenancy / per-tenant scopes — post-v0.1 (Brief §wedge user).
- Conditional registration (`@Injectable(if_env="...")`) — post-v0.1.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### Bare-decorator form

- [ ] `@Injectable` (no parens) on a class stamps
      `__ajolopy_scope__ = "singleton"` and returns the class
      unchanged.
- [ ] The decorated class continues to have its own attributes and
      `__init__` untouched.

### Parameterised form

- [ ] `@Injectable(scope="singleton")` stamps
      `__ajolopy_scope__ = "singleton"`.
- [ ] `@Injectable(scope="request")` stamps the request scope.
- [ ] `@Injectable(scope="transient")` stamps the transient scope.
- [ ] `@Injectable()` (parens with no kwargs) defaults to singleton
      scope — keeps parity with the bare form.

### Scope-value validation

- [ ] `@Injectable(scope="bogus")` raises `InjectableConfigError`
      at decoration time naming the offending value and listing the
      three legal scopes.
- [ ] `@Injectable(scope=None)` raises `InjectableConfigError`.
- [ ] `@Injectable(scope=123)` raises `InjectableConfigError`.

### Inheritance

- [ ] `class Child(InjectableParent): ...` (where `InjectableParent`
      is `@Injectable`-decorated) does **not** inherit
      `__ajolopy_scope__` in `Child.__dict__`. The attribute is
      present on `Parent.__dict__` only. (Test asserts
      `"__ajolopy_scope__" in Parent.__dict__` and
      `"__ajolopy_scope__" not in Child.__dict__`.)

### Re-decoration

- [ ] `@Injectable @Injectable class Foo:` raises
      `InjectableConfigError` referencing the already-decorated class.

### Integration with `@Module` (AJ-8) — smoke test

- [ ] A class decorated `@Injectable(scope="request")` and placed in a
      `@Module(providers=[Service])` is registered under request scope
      in the resulting `CompiledModule.container`. Verified by reading
      the container's registration record or by exercising the scope
      semantics (`request_scope` lifecycle) end-to-end.
- [ ] A class decorated `@Injectable` (bare) and placed in a module is
      registered as a singleton — the compiler's fallback already
      delivers this, but we test the explicit path too.
- [ ] A class **not** decorated with `@Injectable` placed in
      `providers=[]` is still registered (the compiler's default
      fallback to `"singleton"` covers it).

### Public surface

- [ ] `from ajolopy import Injectable` resolves.
- [ ] `from ajolopy.di import Injectable` (the more specific path)
      also resolves, since the decorator lives next to the container.

## Implementation pointers

- Source: extend `src/ajolopy/di/` (no new package — `Injectable`
  belongs next to `Container` since it stamps the scope the container
  consumes).
  - `injectable.py` — the decorator + signature overloads.
  - `errors.py` — add `InjectableError` and `InjectableConfigError`
    to the existing hierarchy.
  - `__init__.py` — public re-exports.
- Top-level `src/ajolopy/__init__.py` — re-export `Injectable` so
  user code writes `from ajolopy import Injectable`.
- Tests: `tests/di/test_injectable.py` covering each acceptance
  item. Use small synthetic classes defined inline.
- Runtime deps: none new. Stdlib only.
- Naming: `Injectable` is `Injectable`, not `Provider` — the Brief
  locks the name and the wedge user (NestJS-origin AI Engineer)
  expects this spelling.

## Implementation notes

<!-- Filled during implementation. Capture scope decisions taken at write
time, edge-case findings, coverage numbers, and any test-only quirks. -->
