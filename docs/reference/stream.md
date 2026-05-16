# `@Stream`

!!! note "Spec"
    Full specification: [`specs/stream.md`](https://github.com/jcocano/ajolopy/blob/main/specs/stream.md)
    · Item: `AJ-3`

## Purpose

`@Stream` is a method decorator that turns an `async def` generator into
a Server-Sent Events (SSE) HTTP endpoint. The decorator validates the
configuration at decoration time and stamps route metadata; at mount
time the framework wraps the bound method in a Starlette handler that
parses inputs through the same machinery as
[`@Controller`](controller.md), frames each yielded value as `data:
...\n\n`, emits keepalives, and cancels the generator on client
disconnect.

Reach for `@Stream` whenever a chat UI needs to render tokens as they
arrive. It composes on top of [`@Agent`](agent.md), [`@Workflow`](workflow.md),
or any plain class — the decorator never inspects the host.

## Signature

```python
def Stream(
    path: str,
    method: Literal["GET", "POST"] = "POST",
    *,
    auth: bool = False,
    heartbeat_seconds: float | None = 30.0,
) -> Callable[[F], F]: ...
```

## Quick example

```python
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream
from ajolopy.http import Body, create_app


class ChatRequest(BaseModel):
    message: str


@Agent(
    model="claude-opus-4-7",
    system="You are Acme Support.",
)
class Support:
    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]):
        async for chunk in self.stream(body.message):
            yield chunk


app = create_app(streams=[Support])
```

## Kwargs

| Kwarg                | Type                              | Default     | Description |
|----------------------|-----------------------------------|-------------|-------------|
| `path`               | `str`                             | required    | Starlette path pattern (`"/chat"`, `"/users/{user_id}/chat"`). |
| `method`             | `Literal["GET", "POST"]`          | `"POST"`    | HTTP verb. Only `GET` and `POST` are supported in v0.1. |
| `auth`               | `bool`                            | `False`     | When `True`, the method must also carry [`@UseGuards`](use-guards.md). |
| `heartbeat_seconds`  | `float \| None`                   | `30.0`      | Emit `: keepalive\n\n` SSE comments every N seconds. `None` disables. |

## Escape hatches

- **Structured events.** Yield `dict` or a Pydantic `BaseModel` instead
  of a string to emit JSON payloads (`data: {"event":"...","..."}\n\n`).
- **No heartbeats.** Pass `heartbeat_seconds=None` when your handler
  already emits its own keepalive cadence.
- **Bypass `mount_streams`.** Call `add_route(app, ...)` with a
  hand-written SSE handler; `@Stream` is opt-in.
- **Pre-built instance.** Pass an instance instead of the class into
  `create_app(streams=[instance])` when you need to inject constructor
  arguments.

## Common gotchas

- The decorated method **must** be an `async def` generator (uses
  `yield`). Regular async methods or sync generators raise
  `StreamConfigError` at decoration time.
- `auth=True` requires [`@UseGuards`](use-guards.md) on the method or
  host class. Without a guard, mount time raises a config error.
- The mount layer instantiates classes with `Cls()` (zero-arg). If your
  class needs constructor arguments, pass a pre-built instance into
  `streams=[support]`.
- Two `@Stream` decorators on the same method raise
  `StreamConfigError`. Stack `@UseGuards` outside, not another
  `@Stream`.
- Exceptions raised mid-stream produce a final
  `data: {"error": "..."}\n\n` envelope and close the connection. The
  original exception is logged at `ERROR` via `ajolopy.stream`.

## See also

- [`@Agent`](agent.md) / [`@Workflow`](workflow.md) — common hosts for
  `@Stream` handlers.
- [`@UseGuards`](use-guards.md) — gate streams behind a guard chain.
- [`@Controller`](controller.md) — non-streaming HTTP endpoints on the
  same `create_app(...)`.
- Spec: [`specs/stream.md`](https://github.com/jcocano/ajolopy/blob/main/specs/stream.md).
