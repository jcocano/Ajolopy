# `@Workflow`

!!! note "Spec"
    Full specification: [`specs/workflow.md`](https://github.com/jcocano/ajolopy/blob/main/specs/workflow.md)
    · Item: `AJ-6`

## Purpose

`@Workflow` is a class decorator that turns a Python class into a
multi-agent orchestrator. It accepts a list of [`@Agent`](agent.md)
classes and either an LLM `coordinator=` model string (default mágico)
or an overridden `route()` method (escape hatch). The injected
`run(message)` / `stream(message)` methods mirror `@Agent` so the
primitive composes with [`@Stream`](stream.md) and [`@Eval`](eval.md)
without special-casing the host.

Reach for `@Workflow` the moment a single prompt stops fitting a single
agent — triage that hands off to billing, technical, or sales
specialists.

## Signature

```python
def Workflow(
    *,
    agents: list[type],
    coordinator: str | None = None,
    integrations: list[type] | None = None,
    max_steps: int = 10,
) -> Callable[[type[T]], type[T]]: ...
```

## Quick example

```python
from ajolopy import Agent, Workflow


@Agent(model="claude-haiku-4-5", system="You triage support requests.")
class Triage:
    """Classify the user's message: billing, technical, or general."""


@Agent(model="claude-opus-4-7", system="You handle billing.")
class Billing:
    """Refunds, invoices, subscriptions."""


@Agent(model="claude-opus-4-7", system="You handle technical issues.")
class Technical:
    """Bugs, errors, integration help."""


@Workflow(
    coordinator="claude-opus-4-7",
    agents=[Triage, Billing, Technical],
)
class SupportTeam:
    """Route support requests to the right specialist."""


async def main() -> None:
    team = SupportTeam()
    answer = await team.run("my refund hasn't arrived, order #4392")
    print(answer)
```

## Kwargs

| Kwarg          | Type                       | Default     | Description |
|----------------|----------------------------|-------------|-------------|
| `agents`       | `list[type]`               | required    | Non-empty list of [`@Agent`](agent.md)-decorated classes. Order is preserved. |
| `coordinator`  | `str \| None`              | `None`      | Model string for the LLM coordinator. Required unless `route()` is overridden. |
| `integrations` | `list[type] \| None`       | `None`      | List of [`@MCP`](mcp.md) classes — tools are exposed to the coordinator AND each delegated agent. |
| `max_steps`    | `int`                      | `10`        | Cap on the coordinator's tool-calling loop. Must be `>= 1`. |

## Escape hatches

- **`route()` override.** Override `async def route(self, message,
  context) -> type` to pick an agent class deterministically. The
  coordinator never runs; `max_steps` is unused.
- **Per-invocation context.** Forward kwargs through `run(message,
  **context)` / `stream(message, **context)`; they reach `route()` as a
  `context: dict` parameter (the LLM coordinator ignores them in v0.1).
- **Compose with [`@Stream`](stream.md).** `@Workflow` classes can carry
  `@Stream` methods; the workflow event stream becomes SSE JSON events
  with no extra wiring.
- **Subclass `WorkflowRuntime`** for unusual coordinator policies, span
  semantics, or hand-off accounting.

## Common gotchas

- Exactly one of `coordinator=` or `route()` must be present. Passing
  both logs an `INFO` message (`route()` wins); passing neither raises
  `WorkflowConfigError` at decoration time.
- Each item in `agents=` must itself carry `@Agent`. Plain classes are
  rejected with the class name in the error message.
- `wf.stream(...)` yields **dicts** (`type` discriminator:
  `handoff` / `agent_result` / `token` / `done`), never bare strings.
  Clients must ignore unknown `type` values forward-compatibly.
- A delegated agent's `AgentError` does NOT propagate; it surfaces as an
  `agent_result` event with `is_error=True` on the tool result, and the
  coordinator decides whether to retry or abandon.
- `WorkflowMaxStepsError` carries `max_steps` and `step_count`. If you
  see it in production, raise the cap — but inspect the trace first.

## See also

- [`@Agent`](agent.md) — the building block this primitive orchestrates.
- [`@Stream`](stream.md) — turn workflow events into SSE.
- [`@MCP`](mcp.md) — share MCP tools across coordinator and delegates.
- [`@Eval`](eval.md) — regression-detect entire workflows.
- Spec: [`specs/workflow.md`](https://github.com/jcocano/ajolopy/blob/main/specs/workflow.md).
