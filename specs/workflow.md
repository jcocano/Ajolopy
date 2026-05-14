# AJ-6 — `@Workflow` decorator (multi-agent orchestration)

> Tracked in [`board.json`](../board.json) as `AJ-6`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §4 (Killer demo Paso 3) and
> `01 - Primitivas core - especificacion detallada` §`@Workflow`. If this file
> ever conflicts with the Brief, the Brief wins — with two recorded
> divergences noted under "Out of scope": the `trace=` kwarg is dropped
> (always-emit, mirroring AJ-28) and `integrations=` is reserved until AJ-7.

## What

`@Workflow` is a **class decorator** that turns a Python class into a
multi-agent orchestrator. The decorator:

1. Validates its configuration at decoration time (`agents=` non-empty and
   each entry `@Agent`-decorated, `coordinator=` resolvable through the
   provider registry when supplied, `integrations=` rejected until AJ-7,
   `max_steps >= 1`).
2. Requires either a non-`None` `coordinator=` string **or** an overridden
   `route()` method on the class — never both as a no-op. Missing both →
   `WorkflowConfigError` at decoration time.
3. Injects two instance methods:
   - `async run(message: str, **context: Any) -> str` — drives the
     orchestration to completion and returns the final coordinator text.
   - `def stream(message: str, **context: Any) -> AsyncIterator[dict]` —
     yields discriminated JSON-friendly events in real time.
4. Preserves the class type for pyright (decorator returns `type[T]`).
5. Composes with `@Stream` (AJ-3) — a `@Stream`-decorated method on a
   `@Workflow` class works exactly the same way it does on `@Agent`, because
   AJ-3 is host-agnostic. `@Eval(workflow=...)` (AJ-4) consumes `run()` /
   `stream()` directly.

## Why

Brief v4.0 §4 names `@Workflow` as the primitive that closes the killer-demo
arc (Paso 3): three single-purpose `@Agent` classes orchestrated by one
coordinator, collapsing what is currently 800+ lines of agent-handoff
plumbing into a single decorator. The wedge user (AI Engineer at a Series A
startup) hits this the moment their support / triage / billing agent stops
fitting in one prompt.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: pass `coordinator="claude-sonnet-4-7"` and a list of
  `@Agent` classes; the framework presents each agent to the coordinator as
  a synthetic tool and runs a function-calling loop until the coordinator
  stops delegating.
- **Escape hatch**: override `async def route(self, message, context)` to
  return a single agent class deterministically — no LLM coordinator runs.

## Public surface (v0.1)

```python
from typing import Annotated

from ajolopy import Agent, Workflow, Stream
from ajolopy.http import Body, create_app
from pydantic import BaseModel


@Agent(model="claude-haiku-4-5", system="You triage support requests.")
class Triage:
    """Classify the user's message: billing, technical, or general."""


@Agent(model="claude-sonnet-4-7", system="You handle billing questions.")
class Billing:
    """Refunds, invoices, subscription changes, payment failures."""


@Agent(model="claude-sonnet-4-7", system="You handle technical issues.")
class Technical:
    """Bugs, errors, integration help, API questions."""


class ChatRequest(BaseModel):
    message: str


@Workflow(
    coordinator="claude-sonnet-4-7",
    agents=[Triage, Billing, Technical],
)
class SupportTeam:
    """Route support requests to the right specialist agent."""

    @Stream("/chat")
    async def handle(self, body: Annotated[ChatRequest, Body()]):
        async for event in self.stream(body.message):
            yield event


app = create_app(streams=[SupportTeam])
```

### Signature

```python
def Workflow(
    *,
    agents: list[type],
    coordinator: str | None = None,
    integrations: list[type] | None = None,
    max_steps: int = 10,
) -> Callable[[type[T]], type[T]]: ...
```

- `agents` — non-empty list of `@Agent`-decorated classes. Validated at
  decoration time. Order is preserved and surfaced to the coordinator in the
  same order as a stable tool list.
- `coordinator` — LLM model string resolved through the provider registry
  (same prefix routing as `@Agent.model`). Required unless the class
  overrides `route()`.
- `integrations` — reserved for AJ-7 (`@MCP`). Any non-`None` value raises
  `WorkflowConfigError` at decoration time with the AJ-7 pointer. Default
  `None` is a no-op.
- `max_steps` — safety cap on the coordinator tool-calling loop. Must be
  `>= 1`. Default `10`. Unused when `route()` is overridden (single hop).

### Decorated class shape

Either:

```python
@Workflow(coordinator="claude-sonnet-4-7", agents=[Triage, Billing])
class Team:
    """Class docstring becomes the workflow description for traces."""
```

Or:

```python
@Workflow(agents=[Triage, Billing, Technical])
class Team:
    async def route(self, message: str, context: dict) -> type:
        if "billing" in message.lower():
            return Billing
        if "error" in message.lower():
            return Technical
        return Triage
```

If both `coordinator=` and `route()` are present, `route()` wins (matches
Brief §`@Workflow` "edge cases"). The framework logs an `INFO`-level
warning at decoration time so the user notices the dead `coordinator=`.

### Injected API

```python
team = SupportTeam()

# Run to completion → final text:
answer: str = await team.run("my refund hasn't arrived, order #4392")

# Stream JSON events in real time:
async for event in team.stream("my refund hasn't arrived"):
    handle(event)  # event is a dict, never a bare string
```

Both methods accept arbitrary `**context` kwargs which the framework forwards
to the `route()` override as the `context: dict` parameter. The coordinator
loop ignores context kwargs in v0.1 (they are not surfaced to the LLM); the
override path consumes them.

### Stream event schema

`stream()` yields `dict` objects with a discriminator key `type`. Four event
shapes ship in v0.1:

| `type`         | Fields                                            | Meaning |
|----------------|---------------------------------------------------|---------|
| `handoff`      | `agent: str`, `message: str`                      | Coordinator (or `route()`) delegated to this agent with this message. |
| `agent_result` | `agent: str`, `output: str`                       | The agent finished and returned this text. |
| `token`        | `text: str`                                       | The coordinator's final-answer token (after it stopped emitting tool_calls). Streaming-only events. |
| `done`         | `text: str`                                       | Terminal event with the full final text. Always the last event in a successful stream. |

Schema is locked for v0.1. New event types in v0.2+ must add a new discriminator
value, never repurpose an existing one. Clients are expected to ignore unknown
`type` values forward-compatibly.

`run()` is a thin wrapper that consumes its own `stream()` internally and
returns the `text` of the `done` event — never iterates a separate code path.

### Coordinator tool-calling loop (default path)

When `route()` is not overridden, the framework runs this loop:

1. Build the coordinator agent: a transient `AgentRuntime` configured with
   `model=coordinator` and one synthetic tool per entry in `agents=`:
   `delegate_to_<lowercased_class_name>(message: str)`. Each tool's
   description is the agent class's docstring; empty docstring falls back to
   `f"Delegate to the {ClassName} agent."` (no warning — the user already
   asked for "lo obvio es lo obvio").
2. Build the coordinator's system prompt:
   ```
   You are a coordinator. Delegate the user's request to one of the
   specialist agents using the provided tools. After agents respond, write
   a final answer to the user in plain text.
   ```
3. Loop, up to `max_steps` iterations:
   - Call `coordinator.complete()` with the accumulated history + tools.
   - If response has **no** tool_calls → emit `token` events for the
     response text, then emit `done` with the full text, return.
   - If response has tool_calls → for each call **in arrival order**:
     - Emit `handoff` event with the call's `message` arg and target agent.
     - Look up the agent class and call `agent_instance.run(message)`.
     - On success: emit `agent_result` and push a `tool_result` message
       with `output` as `content`.
     - On `AgentError`: emit `agent_result` with `output = f"<error>"`
       string (NOT raised) and push a `tool_result` with `is_error=True`
       so the coordinator can decide whether to retry / fall back to a
       different agent. The framework does NOT silently retry.
   - Push the accumulated tool_results as the next user message and loop.
4. If `max_steps` is exceeded → raise `WorkflowMaxStepsError` (terminal,
   propagates out of `run()` / `stream()`). The last `agent_result` event
   has been emitted; no `done` event is emitted.

The coordinator runs `complete()` (not `stream()`) for every turn except the
**last** one (the one with no tool_calls). The last turn streams via
`provider.stream()` so the `token` events arrive in real time. The framework
detects "last turn" by speculative streaming + buffering: it always streams,
and if a tool_call surfaces it suppresses any previously-yielded `token`
events for that turn (none have been yielded yet because we wait until the
first content delta to decide). Implementation pointer: the runtime needs a
small state machine, not a separate `complete()` call.

### `route()` override path

When the decorated class defines `async def route(self, message, context)`:

1. The framework calls `route(message, context_dict)` once. Return value
   must be a class from `agents=`. Otherwise → `WorkflowConfigError`
   wrapped as `WorkflowRouteError` at runtime.
2. Emit `handoff` event with `message` = the original user message,
   `agent` = the returned class name.
3. Call `agent.run(original_message)` (NOT some modified message — the
   user-overridden route() owns the routing decision; the message is
   passed through verbatim).
4. Emit `agent_result` with the agent's text.
5. Emit `done` with the same text (the agent's output IS the final answer
   in the override path — no coordinator LLM massages it).

`max_steps` is unused (single hop by design). Streaming `token` events are
NOT emitted on the override path (there is no coordinator). The agent's
output is emitted in a single `agent_result` + `done` pair, even if the
underlying agent's `stream()` would emit tokens — `run()` is called, not
`stream()`. (Streaming the delegated agent's tokens through the workflow
event stream is out of scope for v0.1; it would require interleaving and
re-discriminating which agent each token belongs to.)

### Error envelope

The decorator does NOT catch user code exceptions or coordinator failures
into the event stream — they propagate as exceptions out of `run()` /
`stream()`. Specifically:

- **Coordinator LLM failure** (any `LLMProviderError`) → propagates as-is
  out of `run()` / `stream()`. The next `agent_result` / `done` event is
  not emitted; the stream raises.
- **Delegated agent failure** (any `AgentError`) → caught and surfaced as
  `agent_result` with `output = f"<error message>"` + `is_error=True` on
  the tool_result fed back to the coordinator. The coordinator decides what
  to do next; the framework does not retry on its own.
- **`route()` returning a non-agent class or `None`** → `WorkflowRouteError`
  propagates out.
- **`max_steps` exceeded** → `WorkflowMaxStepsError` propagates out.

### Observability (mirrors AJ-28 always-emit)

Span tree per `run()` / `stream()`:

```
workflow.invoke {WorkflowName}                       ← root for this invoke
├── chat {coordinator_model}                         ← coordinator turn 1
├── agent.invoke {AgentName}                         ← delegated agent invocation
│   └── chat {agent_model}                           ← agent's own LLM call
├── chat {coordinator_model}                         ← coordinator turn 2 (post tool_result)
├── agent.invoke {AgentName}                         ← second delegation
│   └── chat {agent_model}
└── chat {coordinator_model}                         ← final turn (no tool_calls; streams text)
```

For the `route()` override path:

```
workflow.invoke {WorkflowName}
└── agent.invoke {AgentName}
    └── chat {agent_model}
```

New span attributes (added in `src/ajolopy/observability/conventions.py`):

| Attribute                           | Where             | Value |
|-------------------------------------|-------------------|-------|
| `ajolopy.workflow.name`             | `workflow.invoke` | The decorated class's `__name__`. |
| `ajolopy.workflow.operation`        | `workflow.invoke` | `"run"` or `"stream"`. |
| `ajolopy.workflow.coordinator.model`| `workflow.invoke` | The `coordinator=` value, or absent when `route()` overrides. |
| `ajolopy.workflow.max_steps`        | `workflow.invoke` | `max_steps`. Absent when `route()` overrides. |
| `ajolopy.workflow.step_count`       | `workflow.invoke` | Number of coordinator turns actually executed. |
| `ajolopy.workflow.handoff.count`    | `workflow.invoke` | Number of delegations performed. |

The existing `ajolopy.cost_usd.total` roll-up (AJ-30) is computed on the
`workflow.invoke` span and aggregates **all** descendant `chat` spans —
coordinator turns + delegated agents + their nested tool-loop turns. The
underlying `set_root_cost_total()` helper already walks child costs; the
workflow runtime just needs to feed its accumulator the same way
`AgentRuntime` does.

Span names use existing helpers where possible. New helpers:

- `workflow_invoke_span_name(name: str) -> str` →
  `f"workflow.invoke {name}"`. Lives in `ajolopy.observability.conventions`.

The `agent_invoke_span_name` and `chat_span_name` helpers stay verbatim — no
duplication.

## Design rules

- **Magical default**: one decorator + one model string + a list of
  `@Agent` classes. The framework handles tool synthesis, the coordinator
  loop, hand-off accounting, and span emission. The user writes zero
  routing code.
- **Escape hatch**: override `async def route(self, message, context)`.
  The framework keeps the same surface (`run()` / `stream()`), the same
  event schema (`handoff` / `agent_result` / `done`), and the same span
  shape (just simpler — no coordinator `chat` spans). No second API to
  learn.
- **Mirror of `@Agent`**: `run(message)` / `stream(message)` is the same
  contract as `@Agent`. `@Stream` (AJ-3) and `@Eval` (AJ-4) consume them
  without special-casing the host.
- **Composability**: `@Workflow`-decorated classes are valid hosts for
  `@Stream` and (later) `@UseGuards`. The decorator never inspects host-class
  methods other than `route()`.
- **No global state**: the coordinator's transient `AgentRuntime` is built
  per-workflow at decoration time, never shared across invocations.
- **No silent fallbacks**: `coordinator=` does not get a default model
  string; missing both `coordinator=` and `route()` is a config error.

## Out of scope for this item

- **`@MCP` integrations** → AJ-7. `integrations=[...]` raises
  `WorkflowConfigError` at decoration time until AJ-7 lands and wires the
  shared-tool surface. The kwarg is reserved so AJ-7 does not bump the
  signature.
- **`@Eval(workflow=...)` plumbing** → AJ-4. The eval decorator will
  consume `wf.run()` / `wf.stream()`; this item exposes that surface
  cleanly but does not import or reference `@Eval`.
- **Workflow-level memory** → not a v0.1 concern. Each `@Agent` already
  owns its own `memory=` via AJ-1 / AJ-24. The workflow does not maintain
  cross-agent conversational state; each delegation starts fresh from the
  message the coordinator passes in.
- **Parallel agent hand-offs (fan-out)** → post-v0.1. The coordinator runs
  tool_calls in arrival order even if the provider emits multiple
  tool_calls in one turn. Multi-agent fan-out (run two agents
  concurrently, merge outputs) is intentionally deferred.
- **Streaming tokens from delegated agents through the workflow event
  stream** → post-v0.1. Delegations call `agent.run()`, not
  `agent.stream()`. The workflow's `token` events come only from the
  coordinator's final turn.
- **`trace=True` kwarg** → dropped. Observability is always-on per the
  AJ-28 precedent for `@Agent`. The Brief v4.0 snippet still shows
  `trace=True`; Brief / README copy update tracked in the launch-prep
  punch list.
- **DI-driven instantiation** → AJ-14 wires DI through `AjolopyFactory`;
  in this item, `mount_streams` / direct construction still uses
  zero-arg `Cls()`, identical to AJ-3.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All LLM provider interactions are mocked at the
`LLMProvider` interface; no real network calls in CI.

### Decoration-time validation

- [ ] `@Workflow(coordinator="claude-sonnet-4-7", agents=[A, B])` on a
      class produces a class whose instances have `run` and `stream`
      methods and whose type is preserved (pyright sees the original
      class).
- [ ] `@Workflow(agents=[])` raises `WorkflowConfigError` at decoration
      time with a message naming the workflow class.
- [ ] `@Workflow(coordinator="claude-sonnet-4-7", agents=[A, NotAgent])`
      where `NotAgent` is not `@Agent`-decorated raises
      `WorkflowConfigError` with a message naming `NotAgent`.
- [ ] `@Workflow(agents=[A, B])` on a class that does NOT override
      `route()` raises `WorkflowConfigError` with a message pointing the
      user at the two options: pass `coordinator=` or implement `route()`.
- [ ] `@Workflow(coordinator="claude-sonnet-4-7", agents=[A], integrations=[I])`
      raises `WorkflowConfigError` referencing AJ-7 (`@MCP`).
- [ ] `@Workflow(coordinator="claude-sonnet-4-7", agents=[A], max_steps=0)`
      raises `WorkflowConfigError`. `max_steps=-1` too.
- [ ] `@Workflow(coordinator="not-a-real-model", agents=[A])` raises
      `WorkflowConfigError` referencing the provider registry (same error
      type the agent decorator raises for unknown models).
- [ ] `@Workflow(coordinator="claude-...", agents=[A])` on a class that
      ALSO overrides `route()` logs an `INFO`-level message to
      `ajolopy.workflow` saying `coordinator=` is shadowed by `route()`;
      no error.

### Coordinator tool-calling loop (default path)

- [ ] With a coordinator that returns a single `delegate_to_<a>` tool_call
      and then a tool-free response, `await wf.run("...")` returns the
      coordinator's final text.
- [ ] The coordinator is presented with one synthetic tool per agent named
      `delegate_to_<lowercased_class_name>` (e.g. `delegate_to_billing`).
- [ ] Each synthetic tool's description is the agent class's docstring;
      classes with no docstring get
      `f"Delegate to the {ClassName} agent."` as a fallback (verified by
      mocking the provider and asserting the request's tool list).
- [ ] The coordinator can delegate to the same agent more than once in a
      single invocation (verified with a mock that emits the same
      tool_call twice across turns).
- [ ] Multiple tool_calls in one coordinator turn are run sequentially in
      arrival order; `handoff` + `agent_result` event pairs appear in
      that order in `stream()`.
- [ ] After `max_steps` coordinator turns with tool_calls still emitted,
      `await wf.run(...)` raises `WorkflowMaxStepsError`.

### `route()` override path

- [ ] A `@Workflow(agents=[A, B, C])` class with an overridden
      `route(message, context)` returning `B` calls `B().run(message)` and
      returns that output verbatim from `wf.run(message)`.
- [ ] The context dict received by `route` contains exactly the kwargs
      the caller passed to `wf.run(message, **kwargs)`.
- [ ] `route()` returning a class that is **not** in `agents=` raises
      `WorkflowRouteError` at runtime, with a message naming the bad
      return and the legal set.
- [ ] `route()` returning `None` raises `WorkflowRouteError`.
- [ ] `route()` raising a user exception propagates out of `run()` as
      `WorkflowRouteError` wrapping the original.

### Stream event schema

- [ ] `wf.stream("...")` yields `dict` objects with a `type` key; no bare
      strings, no `BaseModel` instances.
- [ ] Default path: the event sequence is `handoff` → `agent_result` per
      delegation, then zero or more `token` events, then exactly one
      `done` event.
- [ ] `route()` override path: the event sequence is exactly
      `handoff` → `agent_result` → `done`. No `token` events.
- [ ] Every `done` event's `text` equals the awaited result of `wf.run()`
      with the same input (verified with the same mocked provider).
- [ ] `run()` is implemented in terms of `stream()` (it iterates internally
      and reads `done.text`). Verified by asserting that mock providers
      see exactly the same call sequence for `run("x")` vs `stream("x")`.

### Composability with `@Stream` (AJ-3)

- [ ] A `@Workflow` class with a `@Stream("/chat")` method whose body is
      `async for event in self.stream(message): yield event` mounts via
      `create_app(streams=[Cls])` and serves SSE events whose `data:`
      payload is JSON of each workflow event.
- [ ] Calling `wf.stream(message)` directly (no HTTP) yields the same dicts
      in the same order as the SSE payload sequence (with framing
      stripped). Confirms `@Stream` adds zero semantic transformation on
      top of `@Workflow`.

### Observability

- [ ] `wf.run(...)` opens exactly one `workflow.invoke {Name}` span with
      attributes `ajolopy.workflow.name`, `ajolopy.workflow.operation`,
      `ajolopy.workflow.coordinator.model`, `ajolopy.workflow.max_steps`,
      `ajolopy.workflow.step_count`, `ajolopy.workflow.handoff.count`.
- [ ] In the default path, the `workflow.invoke` span has one child
      `chat {coordinator_model}` span per coordinator turn plus one child
      `agent.invoke {AgentName}` span per delegation. Order is preserved.
- [ ] In the `route()` override path, the `workflow.invoke` span has
      exactly one child `agent.invoke` span and zero coordinator `chat`
      spans. `ajolopy.workflow.coordinator.model` is absent.
- [ ] The `ajolopy.cost_usd.total` attribute on `workflow.invoke` equals
      the sum of `gen_ai.cost_usd` across all descendant chat spans
      (coordinator + agents + their tool loops). Verified with a fake
      pricing catalog.
- [ ] `ajolopy.workflow.handoff.from` and `ajolopy.workflow.handoff.to`
      appear on each `agent.invoke` span as breadcrumbs for the
      hand-off chain (`from = "coordinator"` for the default path,
      `from = "route"` for the override path).

### Error handling

- [ ] A delegated agent raising `AgentError` does NOT propagate; the
      coordinator sees a `tool_result` with `is_error=True` and an error
      message body, and the workflow emits an `agent_result` event whose
      `output` carries the same error message (verified with a mock agent
      whose `run()` raises).
- [ ] A coordinator `LLMProviderError` propagates out of `run()` /
      `stream()` immediately. The last successfully-emitted event was
      the prior `agent_result` (or nothing, if the failure was on turn 1).
- [ ] `WorkflowMaxStepsError` carries `max_steps` and `step_count` on the
      exception object for telemetry.

### Public re-exports

- [ ] `from ajolopy import Workflow` works.
- [ ] `from ajolopy.workflow import WorkflowConfigError, WorkflowError,
      WorkflowMaxStepsError, WorkflowRouteError` works.
- [ ] `Workflow` is added to `src/ajolopy/__init__.py`'s `__all__` next
      to the other primitive names.

## Implementation pointers

- Source: `src/ajolopy/workflow/` (new package).
  - `__init__.py` — public re-exports: `Workflow`, `WorkflowError`,
    `WorkflowConfigError`, `WorkflowMaxStepsError`, `WorkflowRouteError`,
    event `TypedDict`s.
  - `decorator.py` — the `Workflow(...)` decorator factory; validates
    config + binds `WorkflowRuntime` + injects `run`/`stream` methods.
  - `runtime.py` — `WorkflowRuntime`: owns the coordinator agent (a
    transient `AgentRuntime`), the synthetic-tool wire shape, the
    coordinator loop state machine, the `route()` override path, and the
    span emission.
  - `events.py` — `TypedDict` definitions for each event variant +
    helpers to construct them (`make_handoff`, `make_agent_result`,
    `make_token`, `make_done`).
  - `errors.py` — `WorkflowError` base, `WorkflowConfigError`,
    `WorkflowMaxStepsError`, `WorkflowRouteError`.
- New helper in `src/ajolopy/observability/conventions.py`:
  - `workflow_invoke_span_name(name: str) -> str`
  - New attr constants: `AJOLOPY_WORKFLOW_NAME`,
    `AJOLOPY_WORKFLOW_OPERATION`, `AJOLOPY_WORKFLOW_COORDINATOR_MODEL`,
    `AJOLOPY_WORKFLOW_MAX_STEPS`, `AJOLOPY_WORKFLOW_STEP_COUNT`,
    `AJOLOPY_WORKFLOW_HANDOFF_COUNT`, `AJOLOPY_WORKFLOW_HANDOFF_FROM`,
    `AJOLOPY_WORKFLOW_HANDOFF_TO`.
- Reuses without modification:
  - `AgentRuntime` from `ajolopy.agent.runtime` — the coordinator IS an
    agent, instantiated transiently inside the workflow runtime with
    a synthetic system prompt + the synthetic tool list. The tool-call
    handler is overridden to intercept `delegate_to_*` calls (which never
    reach a real `@Tool` binding).
  - `set_chat_cost_attrs` / `set_root_cost_total` from
    `ajolopy.observability.pricing_emit`.
  - `Tool`, `ToolCall`, `Message`, `LLMProviderError` from
    `ajolopy.providers`.
- Tests: `tests/workflow/`.
  - `test_decorator_validation.py` — every config-error case.
  - `test_coordinator_loop.py` — single hop, multi-hop, parallel
    tool_calls, max_steps cap, agent error propagation through tool_result.
  - `test_route_override.py` — override return values, context dict
    forwarding, error cases.
  - `test_events.py` — stream schema invariants and event ordering.
  - `test_observability.py` — span tree shape, attributes, cost roll-up.
  - `test_composability.py` — `@Stream` mounting, `run()`/`stream()`
    parity, `wf.run` = `done.text` from `wf.stream`.
  - `test_public_api.py` — re-exports and `__all__` membership.
- Runtime deps: none new. Reuses Anthropic / OpenAI / Gemini providers
  via the registry. `opentelemetry-api` is already a runtime dep.
- Dev deps: none new.

## Implementation notes

(Empty — populated by the implementation PR.)
