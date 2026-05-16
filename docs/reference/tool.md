# `@Tool`

!!! note "Spec"
    Full specification: [`specs/tool.md`](https://github.com/jcocano/ajolopy/blob/main/specs/tool.md)
    · Item: `AJ-2`

## Purpose

`@Tool` is a method decorator that exposes a method of an
[`@Agent`](agent.md)-decorated class to the underlying LLM as a callable
tool. The decorator inspects the method's signature + docstring at
decoration time, synthesises a JSON Schema for the inputs, and stamps
framework metadata so the agent runtime can discover the tool. The
function-calling loop is built-in: the agent re-invokes the provider
until the response is tool-free.

Reach for `@Tool` whenever a single LLM call needs to look something up,
call an API, or perform a side-effecting action. One decorator per
capability — no JSON Schema by hand.

## Signature

```python
def Tool(
    fn: Callable[P, R] | None = None,
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    schema: type[BaseModel] | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]: ...
```

## Quick example

```python
from ajolopy import Agent, Tool


@Agent(
    model="claude-opus-4-7",
    system="You help customers manage orders and refunds.",
)
class Support:
    """Top-level support agent."""

    @Tool
    async def get_order_status(self, order_id: str) -> str:
        """Look up an order's current status by id."""
        return f"order {order_id} is in transit"

    @Tool(name="issue_refund", description="Issue a refund for an order.")
    async def refund(self, order_id: str, reason: str) -> dict[str, str]:
        return {"order_id": order_id, "reason": reason, "status": "ok"}
```

## Kwargs

| Kwarg          | Type                       | Default      | Description |
|----------------|----------------------------|--------------|-------------|
| `name`         | `str \| None`              | method name  | Override the tool name exposed to the LLM. |
| `description`  | `str \| None`              | docstring    | Override the description used in the JSON Schema. Defaults to the first non-empty line of the method's docstring. |
| `schema`       | `type[BaseModel] \| None`  | `None`       | Override signature introspection with a hand-written Pydantic model. The model's `model_json_schema()` is sent to the provider verbatim. |

## Escape hatches

- **Bare form (`@Tool`)** — magical default. Name comes from the method,
  description from the docstring, JSON Schema from the type hints.
- **Hand-rolled schema (`@Tool(schema=MyArgs)`)** — substitute a
  Pydantic `BaseModel` when you need validators, aliases, or stricter
  constraints than what type-hint introspection yields.
- **Tools defined elsewhere** — register them via
  `@Agent(tools=[OtherClass])` so the runtime discovers `@Tool` methods
  on classes the agent does not inherit from.
- **Sync OR async** — both are supported. Sync tools are dispatched via
  `asyncio.to_thread` so they cannot block the event loop.

## Common gotchas

- Methods without type hints raise `ToolDefinitionError` at decoration
  time. Annotate every parameter and return.
- Tool errors flow **back to the model** as a `tool_result` with
  `is_error=True`. The model decides whether to retry, apologise, or
  abandon. Your `run()` contract is still `-> str` — exceptions never
  bubble to the caller for normal tool failures.
- Tool name collisions across the agent's own methods and any
  `tools=[OtherClass]` raise `AgentConfigError` at decoration time. Pick
  unique names.
- The function-calling loop has a safety cap. Configure it via
  `@Agent(max_tool_iterations=...)` (default `10`); exceeding the cap
  raises `AgentToolLoopError`.
- The return value is stringified for the LLM via `json.dumps(default=str)`.
  Returning huge objects costs tokens — keep tool outputs concise.

## See also

- [`@Agent`](agent.md) — the host class for tools.
- [`@MCP`](mcp.md) — expose external MCP-server tools alongside `@Tool`
  methods on the same agent.
- [`@MCPServer`](mcp-server.md) — publish your `@Tool` methods to other
  MCP clients.
- Spec: [`specs/tool.md`](https://github.com/jcocano/ajolopy/blob/main/specs/tool.md).
