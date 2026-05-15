# `@Controller`

!!! note "Spec"
    Full specification: [`specs/controller.md`](https://github.com/jcocano/ajolopy/blob/main/specs/controller.md)
    · Item: `AJ-10`

## Purpose

`@Controller(prefix)` is a class decorator that binds HTTP routes to a
class with a shared path prefix. It stamps `__ajolopy_route_prefix__` on
the class and tells `mount_routes(app, [...])` to concatenate the prefix
with each method-level path before registering the route.

Method-level decorators (`@Get`, `@Post`, `@Put`, `@Patch`, `@Delete`)
already stamp per-method metadata; `@Controller` layers the class-level
prefix on top so you write `@Controller("/users")` once instead of
repeating `/users` in every method.

Reach for `@Controller` whenever you need non-streaming HTTP endpoints —
for streaming, use [`@Stream`](stream.md).

## Signature

```python
def Controller(prefix: str = "") -> Callable[[type], type]: ...
```

## Quick example

```python
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Controller, Get, Post
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
# Registered routes: GET /users/, GET /users/{user_id}, POST /users/
```

## Kwargs

| Kwarg     | Type   | Default | Description |
|-----------|--------|---------|-------------|
| `prefix`  | `str`  | `""`    | Path prefix concatenated with every method-level path. Empty string is legal. |

## Escape hatches

- **Root-level controllers.** `@Controller("")` produces unprefixed
  routes — useful for the app's root controller.
- **Plain classes.** Method decorators (`@Get` etc.) work without a
  `@Controller` wrapper for ad-hoc routes; `mount_routes` registers
  them with an empty prefix.
- **DI for controllers.** [`@Module`](module.md) registers controllers
  as singletons in the container; the constructor type hints drive
  dependency injection just like [`@Injectable`](injectable.md)
  providers.

## Common gotchas

- The `prefix` argument is **required** — `@Controller` without `()`
  is not supported (unlike `@Injectable`). Empty prefix is fine,
  no parentheses are not.
- Trailing slashes are stripped at decoration time:
  `@Controller("/users/")` and `@Controller("/users")` produce the
  same effective prefix. Method-level paths keep their own
  trailing-slash semantics.
- `__ajolopy_route_prefix__` is **not** inherited by subclasses. Mirror
  the `@Module` / `@Injectable` rule and re-decorate explicitly.
- Re-decoration raises `ControllerConfigError`. A class has exactly
  one prefix.
- `mount_routes` joins prefix + method-path with plain string
  concatenation. Double slashes in the method path are the user's bug;
  the framework does not deduplicate.

## See also

- [`@Stream`](stream.md) — for streaming HTTP endpoints.
- [`@UseGuards`](use-guards.md) — gate controllers behind a guard chain.
- [`@Module`](module.md) — register controllers via `controllers=`.
- Spec: [`specs/controller.md`](https://github.com/jcocano/ajolopy/blob/main/specs/controller.md).
