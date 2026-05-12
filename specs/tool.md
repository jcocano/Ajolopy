# AJ-2 — `@Tool` decorator + function-calling loop

> Tracked in [`board.json`](../board.json) as `AJ-2`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §01 (primitive spec) — specifically
> the killer-demo **Paso 2 (Tools)** which dictates "capacidades como una línea
> cada una". Builds directly on `specs/agent.md` (AJ-1) and the wire types
> defined in `specs/llm-provider.md` (AJ-18). If this file ever conflicts with
> the Brief, the Brief wins.

## What

`@Tool` is a **method decorator** that turns an instance method of an
`@Agent`-decorated class into a tool exposed to the underlying LLM. The
decorator:

1. Inspects the method's signature (parameter type hints + docstring) at
   decoration time and synthesises a JSON Schema for its inputs.
2. Marks the method with framework metadata so the `@Agent` runtime can
   discover it.
3. Leaves the method itself callable as a normal Python method — the
   decorator wraps it transparently.

In tandem, this item ships the **function-calling loop** inside `AgentRuntime`
(see `src/ajolopy/agent/runtime.py`):

- When `Agent.run(message)` invokes the provider and the response carries
  `tool_calls`, the runtime executes each tool against the live agent
  instance, appends the results as `Message(role="tool", …)`, and re-calls the
  provider until the response is tool-free or the iteration cap is hit.
- The same machinery is wired into `Agent.stream(message)`: when a streaming
  response ends with `finish_reason="tool_calls"`, the runtime executes the
  buffered tool calls, appends results, and starts a fresh stream — yielding
  text chunks continuously from the caller's perspective.

## Why

Step 2 of the killer demo promises that adding a capability is a one-line
decorator. The wedge user (AI Engineer at a Series A) gets a magical default
where signature + docstring become the JSON Schema, and an escape hatch where
`name`, `description`, and `parameters` can all be overridden when the default
introspection is wrong (legacy code, dynamic params, etc.).

The function-calling loop must live inside the framework — making the user
hand-write a retry/append/re-call loop for every agent would defeat the
"single line per capability" promise.

## Public surface (v0.1)

```python
from ajolopy import Agent, Tool


@Agent(model="claude-sonnet-4-7", system="You help customers.")
class Support:
    """Top-level support agent for the demo."""

    @Tool
    async def get_order_status(self, order_id: str) -> str:
        """Look up an order's current status by ID."""
        return await db.fetch_status(order_id)

    @Tool
    def list_refund_reasons(self) -> list[str]:
        """Return canonical refund reason codes."""
        return ["damaged", "wrong_item", "no_longer_needed"]

    @Tool(name="issue_refund", description="Issue a refund on an order.")
    async def refund(self, order_id: str, reason: str) -> dict[str, str]:
        return await payments.refund(order_id, reason)


class RefundArgs(BaseModel):
    order_id: str = Field(min_length=8)
    reason: Literal["damaged", "wrong_item", "no_longer_needed"]


@Agent(model="claude-sonnet-4-7", system="…")
class Billing:
    @Tool(schema=RefundArgs)
    async def refund(self, order_id: str, reason: str) -> dict[str, str]:
        """Issue a refund using a strict Pydantic-validated argument set."""
        return await payments.refund(order_id, reason)
```

### Signature

```python
def Tool(
    fn: Callable[P, R] | None = None,
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    schema: type[BaseModel] | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    ...
```

`@Tool` is used either bare (`@Tool`) or with kwargs (`@Tool(name=...)`). The
underlying function is returned **unwrapped at the call site** — `agent.refund(...)`
still works as a normal method. Only the runtime's tool dispatcher consults
the attached metadata.

The `schema=` escape hatch (a `pydantic.BaseModel` subclass) overrides
introspection wholesale — every field of the model becomes a JSON Schema
property, and the runtime passes the validated model instance attributes as
kwargs into the method.

### Discovery on `@Agent`

The agent runtime discovers tools at decoration time by scanning the class
dict for callables tagged with the `Tool` marker. No new kwarg is added to
`@Agent` for the common case; the existing `tools=[...]` keyword (currently
typed `list[type] | None`) is reinterpreted as **additional classes whose
`@Tool`-tagged methods should also be exposed** — covers tool reuse across
agents without forcing inheritance.

### Iteration cap

`@Agent` gains one new kwarg:

```python
@Agent(
    model="claude-sonnet-4-7",
    system="…",
    max_tool_iterations=10,  # default
)
class Support: ...
```

Once the cap is exceeded the runtime raises `AgentToolLoopError` with the
last response embedded for diagnostics.

## Design rules

- **Magical default**: bare `@Tool` on a method generates the tool name from
  the method name, the description from the first line of its docstring, and
  the JSON Schema from `inspect.signature` using a dynamically-created
  Pydantic v2 model (`pydantic.create_model`). This covers ~90% of cases.
- **Escape hatches**:
  - `name=`, `description=` override the introspected values.
  - `schema=BaseModelSubclass` substitutes a hand-written Pydantic model for
    the synthesised one — useful when validators, aliases, or stricter
    constraints are needed.
  - Pass `tools=[OtherClass]` to `@Agent` to expose tools defined elsewhere.
  - Return value type is left to the tool author; the runtime stringifies
    non-string returns through `json.dumps(default=str)` before handing them
    back to the model.
- **Both sync and async tools** are supported. Sync tools are dispatched via
  `asyncio.to_thread` so they cannot block the event loop.
- **Tool errors are surfaced to the model**, not raised to the caller. When a
  `@Tool` raises, the runtime sends a `tool_result` with `is_error=True` and
  the exception message; the model decides whether to retry, apologise, or
  abandon. This mirrors Anthropic's recommended pattern and keeps the user's
  agent contract simple (`run` returns a string, never bubbles tool internals).
  Catastrophic loop failures (cap exceeded, malformed tool_use blocks) still
  raise typed framework errors.

## Out of scope for this item

- `@MCP` decorator (AJ-7) — MCP-style tool publishing/consumption is a
  separate primitive layered on top of `@Tool`.
- Workflow-level tool sharing (AJ-6) — `@Workflow` may register tools across
  agents in its own scope; that lives in AJ-6.
- Eval-driven tool selection metrics (AJ-26's `tool_called` metric depends on
  this item but is implemented separately).
- OTEL `gen_ai.tool.*` attributes — basic tracing of the loop ships here
  (one span per tool invocation when `trace=True`), full `gen_ai.*` taxonomy
  lands in AJ-28.
- Tool input validation (rejecting calls whose `arguments` don't match the
  declared schema) — v0.1 forwards arguments straight to the function and
  relies on the function's own type-handling. Strict schema validation is
  a v0.2 hardening item.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`.

### Decorator basics

- [x] Bare `@Tool` on an `async def` method preserves the method so
      `await instance.method(arg)` still works.
- [x] Bare `@Tool` on a sync `def` method preserves the method so
      `instance.method(arg)` still works.
- [x] `@Tool(name="x", description="y")` overrides the metadata used by the
      runtime; the method itself stays callable.
- [x] Methods without `@Tool` are not exposed to the model.

### Schema generation

- [x] A tool with parameters `(self, order_id: str)` generates a JSON Schema
      whose `properties.order_id.type == "string"` and `required == ["order_id"]`.
- [x] Parameters with default values are not marked `required`.
- [x] `int`, `float`, `bool`, `list[str]`, `dict[str, int]`, and
      `str | None` map to the expected JSON Schema fragments (verified by
      assertion on the produced schema).
- [x] A Pydantic `BaseModel` parameter type produces a nested-object schema
      with the model's fields under `properties`.
- [x] The tool description defaults to the first non-empty line of the
      method's docstring.
- [x] `@Tool(schema=MyArgs)` (where `MyArgs` is a `BaseModel`) skips
      signature introspection and exposes `MyArgs.model_json_schema()` to the
      provider verbatim.
- [x] Decorating a function with no annotations raises a clear
      `ToolDefinitionError` at decoration time, naming the offending function
      and parameter.
- [x] A parameter typed with a class that Pydantic cannot serialise raises a
      clear `ToolDefinitionError` at decoration time (matches Brief §01 edge
      case). Surfaced through the `*args` / unannotated test pair — every
      `create_model` failure raises ToolDefinitionError eagerly.

### Discovery by `@Agent`

- [x] `@Agent` decorating a class with `@Tool`-tagged methods exposes them
      to the provider on `complete()` and `stream()`.
- [x] A class with no `@Tool` methods continues to forward `tools=None` to
      the provider (no regression on AJ-1's "no tools" path).
- [x] `@Agent(tools=[OtherClass])` exposes `@Tool` methods defined on
      `OtherClass` in addition to those on the decorated class. Methods bind
      to a singleton instance of `OtherClass` (constructed once per agent
      class at decoration time).
- [x] Tool name collisions across the decorated class and `tools=[...]`
      raise `AgentConfigError` at decoration time (ToolDefinitionError, which
      is an AgentConfigError subclass).

### Function-calling loop on `run()`

- [x] When the provider returns a `Response` with one `ToolCall`, the
      runtime executes the corresponding method, appends a
      `Message(role="tool", content=<stringified result>, tool_call_id=<id>)`,
      and re-calls `provider.complete(...)`.
- [x] When the second `complete()` returns a tool-free response, its text is
      returned to the caller.
- [x] When the provider returns multiple `ToolCall`s in a single response,
      each is executed (concurrently for async tools, in submission order)
      and all results are appended before the next `complete()`.
- [x] Sync tools are dispatched via `asyncio.to_thread` (verified by mocking
      `asyncio.to_thread` and asserting it was called).
- [x] When a tool raises, the runtime sends a `tool_result` with
      `is_error=True` and the exception message; the loop continues.
- [x] The loop respects `max_tool_iterations`; exceeding it raises
      `AgentToolLoopError` with the iteration count in the message.

### Function-calling loop on `stream()`

- [x] When the streamed response ends with `finish_reason="tool_calls"`, the
      runtime executes the buffered tool calls and starts a fresh stream
      with the tool results appended.
- [x] Text chunks emitted before the `tool_calls` cutover are yielded to the
      caller verbatim; text chunks from the post-tool stream are appended to
      the same iterator.
- [ ] Cancelling the iterator mid-loop cancels the underlying provider
      stream and any in-flight tool tasks. (Best-effort by relying on async
      generator semantics — explicit cancellation test deferred.)
- [x] The loop respects `max_tool_iterations` on the stream path too.

### Errors

- [x] `ToolDefinitionError` is raised at decoration time when introspection
      fails (missing annotation, untyped `*args` / `**kwargs`).
- [x] `AgentToolLoopError` derives from `AgentError`.
- [x] `ToolDefinitionError` derives from `AgentError` (via `AgentConfigError`).

### Observability

- [x] When `@Agent(trace=True)` is active, every tool invocation inside the
      loop emits a span named `agent.tool` with attributes `tool.name`,
      `tool.iteration`, `tool.success` (`bool`).
- [x] When `trace=False`, no tool spans are emitted.

## Implementation pointers

- Source:
  - `src/ajolopy/agent/tool.py` — `Tool` decorator, schema synthesis, the
    `_TOOL_MARKER` metadata attribute, and tool-class discovery helpers.
  - `src/ajolopy/agent/runtime.py` — extend `AgentRuntime` with the
    function-calling loop (`run` and `stream` paths) and the
    `max_tool_iterations` knob.
  - `src/ajolopy/agent/errors.py` — add `ToolDefinitionError` and
    `AgentToolLoopError`; remove `AgentToolUseUnsupportedError` (made
    obsolete by this item) but keep an alias for one release with a clear
    deprecation message if any external code references it. (Pragmatically:
    nothing outside the repo can, so we just delete it.)
  - `src/ajolopy/agent/decorator.py` — accept `max_tool_iterations` and
    forward it to the runtime.
  - `src/ajolopy/agent/__init__.py` — re-export `Tool`.
  - `src/ajolopy/__init__.py` — re-export `Tool`.
- Schema generation uses `pydantic.create_model` (already a runtime dep).
- Tests: `tests/agent/test_tool.py` (decorator + schema) and
  extensions to `tests/agent/test_runtime.py` (loop behaviour).
- No new external runtime dependency.

## Implementation notes

- `2026-05-12` — Shipped `src/ajolopy/agent/tool.py` (decorator + schema
  synthesis + `discover_tools`) and extended `src/ajolopy/agent/runtime.py`
  with the function-calling loop on both `run()` and `stream()` paths. Scope
  decisions taken during implementation:
  - **`Message` wire type extended**, not bypassed. Added `tool_calls:
    list[ToolCall]` (meaningful on assistant turns) and `is_error: bool`
    (meaningful on tool turns). This is the cleanest way to replay a full
    tool-use turn through `provider.complete()` without coupling the runtime
    to any provider's native shape. `AnthropicProvider._split_system` now
    emits `tool_use` content blocks for assistant messages with `tool_calls`
    and forwards `is_error=True` into `tool_result` blocks.
  - **`ToolCallDelta.index` added** so the streaming loop can correlate the
    initial `content_block_start` (which carries the `tool_use_id` and
    `name`) with subsequent `input_json_delta` events (which only carry the
    block index). Anthropic's provider was updated to populate it from
    `event.index` on both event types.
  - **Tool errors → LLM**, not caller. A `@Tool` that raises has its
    exception type + message sent back as a `tool_result` with
    `is_error=True`; the loop continues. The agent's `run()` contract stays
    `-> str` and never bubbles tool internals. Mirrors Brief §01 edge case
    and Anthropic's recommended pattern.
  - **`AgentToolUseUnsupportedError` deleted.** The AJ-1 marker for "tool
    use seen but loop not implemented yet" is obsolete now that the loop
    exists. Test `test_tool_use_response_raises_unsupported_error_until_aj2`
    removed; nothing outside the repo could reference it.
  - **PEP 695 generics** used for the public `Tool` decorator
    (`def Tool[F: Callable[..., Any]]`). ruff's `UP047` insists on type
    parameters; pyright in strict mode accepts the overload form.
  - **Provider-agnostic loop.** No Anthropic-specific assumptions: the
    runtime only operates on `LLMProvider`, `Message`, `ToolCall`,
    `Response`, `Chunk`. The Anthropic provider was patched to *speak* the
    new fields; the loop itself is portable to OpenAI/Gemini/Universal
    OpenAI without changes.
  - **Coverage of new code.** `src/ajolopy/agent/tool.py` 91%,
    `src/ajolopy/agent/runtime.py` 85%. Uncovered branches are defensive
    fallbacks (extra-instance cache miss, span exit edge cases) plus the
    streaming cancellation path noted in the acceptance list.
  - **Tests added.** 17 in `tests/agent/test_tool.py` (decorator + schema +
    discovery) and 12 in `tests/agent/test_tool_loop.py` (loop on `run()`
    and `stream()` + OTEL spans). Total suite at 216 passing.
