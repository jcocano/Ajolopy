# `@Agent`

!!! note "Spec"
    Full specification: [`specs/agent.md`](https://github.com/jcocano/ajolopy/blob/main/specs/agent.md)
    · Item: `AJ-1`

## Purpose

`@Agent` is a class decorator that turns a Python class into an
LLM-powered agent. It validates the model + provider at definition time,
wires retry / fallback / tracing / memory / prompt-caching from kwargs,
and injects `run(message)` and `stream(message)` methods on the class.

Reach for `@Agent` whenever you need one LLM call to drive one
conversational surface. For multi-agent orchestration use
[`@Workflow`](workflow.md); for capabilities use [`@Tool`](tool.md).

## Signature

```python
@Agent(
    model: str,
    system: str | Callable[..., str],
    *,
    memory: str | dict | type[Memory] | None = None,
    trace: bool = False,
    cache: Literal["prompt"] | None = None,
    fallback: str | list[str] | Callable | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_tool_iterations: int = 10,
    tools: list[type] | None = None,
    integrations: list[type] | None = None,
)
```

## Quick example

```python
from ajolopy import Agent


@Agent(
    model="claude-sonnet-4-7",
    system="You are a concise, friendly support assistant.",
)
class Support:
    """Top-level support agent."""


async def main() -> None:
    agent = Support()
    answer = await agent.run("where is my order?")
    print(answer)

    async for token in agent.stream("any updates?"):
        print(token, end="")
```

## Kwargs

| Kwarg                  | Type                                          | Default       | Description |
|------------------------|-----------------------------------------------|---------------|-------------|
| `model`                | `str`                                         | required      | Model string routed via prefix (`claude-*`, `gpt-*`, `gemini-*`, `ollama:*`, ...). |
| `system`               | `str \| Callable[..., str]`                   | required      | Static system prompt, or a callable for per-request prompts. |
| `memory`               | `str \| dict \| type[Memory] \| None`         | `None`        | URL string (`redis://...`), config dict, or `Memory` subclass. |
| `trace`                | `bool`                                        | `False`       | Emit one OpenTelemetry span per `run` / `stream`. |
| `cache`                | `Literal["prompt"] \| None`                   | `None`        | `"prompt"` forwards to the provider's prompt-caching hook (static `system` only). |
| `fallback`             | `str \| list[str] \| Callable \| None`        | `None`        | Model(s) to retry on retriable provider failure, or a custom callable. |
| `temperature`          | `float \| None`                               | `None`        | Sampling temperature forwarded to the provider. |
| `max_tokens`           | `int \| None`                                 | `None`        | Hard cap on response tokens forwarded to the provider. |
| `max_tool_iterations`  | `int`                                         | `10`          | Safety cap on the function-calling loop ([`@Tool`](tool.md)). |
| `tools`                | `list[type] \| None`                          | `None`        | Extra classes whose `@Tool` methods this agent should expose. |
| `integrations`         | `list[type] \| None`                          | `None`        | List of [`@MCP`](mcp.md)-decorated classes to source MCP tools from. |

## Escape hatches

- **Per-request system prompts.** Pass `system=` a callable; the framework
  invokes it on every `run` / `stream` to build the prompt.
- **Custom memory backends.** Subclass `Memory` and pass the subclass (or
  a pre-built instance) via `memory=`.
- **Custom fallback policy.** Pass a callable into `fallback=`; the
  framework hands it the original request payload on primary failure and
  surfaces its return value as the agent's answer.
- **Subclass the runtime.** Power users can extend `AgentRuntime`
  directly for unusual flows (custom retry policy, alternate streaming
  contract).
- **Bring your own tools.** Pass `tools=[OtherClass]` to expose
  `@Tool`-decorated methods defined elsewhere without inheritance.

## Common gotchas

- `cache="prompt"` requires a **static** `system` string. Combining
  `cache="prompt"` with a callable `system` raises
  `AgentConfigError` at decoration time.
- Provider env vars (e.g. `ANTHROPIC_API_KEY`) are validated at
  decoration time. A missing var fails fast — fix the env, do not catch
  the error.
- `model="..."` strings without a recognised prefix raise
  `AgentConfigError` with the supported-prefix list in the message.
- The decorator preserves the class type so type checkers still see
  the original methods — do not wrap your class manually.
- Cancelling the `stream()` async iterator cancels the underlying
  provider call. Wrap consumption in `try/finally` to release resources
  deterministically.

## See also

- [`@Tool`](tool.md) — add capabilities to an agent.
- [`@Stream`](stream.md) — expose an agent over Server-Sent Events.
- [`@Workflow`](workflow.md) — orchestrate multiple agents.
- [`@MCP`](mcp.md) — inject MCP-server tools into the agent.
- Spec: [`specs/agent.md`](https://github.com/jcocano/ajolopy/blob/main/specs/agent.md).
