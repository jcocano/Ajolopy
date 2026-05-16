# `@MCP`

!!! note "Spec"
    Full specification: [`specs/mcp.md`](https://github.com/jcocano/ajolopy/blob/main/specs/mcp.md)
    · Item: `AJ-7`

## Purpose

`@MCP` is a class decorator that declares one or more external MCP
servers an agent or workflow wants to consume. The decorated class is a
**declaration**, not a live object — no processes spawn, no connections
open at decoration time. Eager discovery happens at factory boot: the
framework spawns / connects each server once per process (shared pool),
discovers their tools, namespaces them as `<server_key>__<tool_name>`,
and injects them into every [`@Agent`](agent.md) / [`@Workflow`](workflow.md)
that references the `@MCP` class via `integrations=`.

Reach for `@MCP` whenever your agent needs to talk to an existing MCP
ecosystem — GitHub, Linear, Stripe, internal company servers — instead
of hand-rolling each integration.

## Signature

```python
def MCP(
    *,
    servers: dict[str, ServerSpec] | list[ServerSpec],
    auth: dict[str, AuthSpec] | None = None,
    timeout: float = 30.0,
) -> Callable[[type[T]], type[T]]: ...
```

`ServerSpec` is `str | MCPClient`; `AuthSpec` is `dict[str, Any]`.

## Quick example

```python
from ajolopy import Agent, MCP


@MCP(
    servers={
        "github": "stdio:npx -y @modelcontextprotocol/server-github",
        "linear": "https://api.linear.app/mcp",
    },
    auth={
        "github": {"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}},
        "linear": {"token": "${LINEAR_API_KEY}"},
    },
)
class Integrations: ...


@Agent(
    model="claude-opus-4-7",
    system="You are an engineering on-call assistant.",
    integrations=[Integrations],
)
class OnCall:
    """Handle incidents: open Linear bugs, look up GitHub PRs, ..."""
```

## Kwargs

| Kwarg      | Type                                                | Default    | Description |
|------------|-----------------------------------------------------|------------|-------------|
| `servers`  | `dict[str, ServerSpec] \| list[ServerSpec]`         | required   | Non-empty. Dict form recommended (keys = `server_key` for namespacing). |
| `auth`     | `dict[str, AuthSpec] \| None`                       | `None`     | Per-server auth dict. Keys must match `servers=`. `${ENV_VAR}` substitution supported. |
| `timeout`  | `float`                                             | `30.0`     | Per-tool-call timeout in seconds. Connect / list-tools use a separate 10 s handshake budget. |

## Escape hatches

- **Custom transport.** Subclass `MCPClient` (the ABC), implement
  `connect` / `list_tools` / `call_tool` / `aclose`, and pass an
  instance into `servers=`. The framework uses your client verbatim;
  auth lives inside the instance.
- **List form for quick demos.** `servers=["stdio:..."]` auto-derives
  keys `server_0`, `server_1`, ... — dict form is recommended for
  anything non-trivial.
- **Inspect the registry.** `from ajolopy.mcp import get_mcp_registry`
  exposes `discovered_tools()`, `get_or_open()`, and `shutdown()` for
  test setup and advanced introspection.

## Common gotchas

- The `mcp` SDK is an **opt-in dependency**. `from ajolopy import MCP`
  works without it, but actually connecting raises
  `MCPDependencyError` — install with `pip install ajolopy[mcp]`.
- Unknown scheme prefixes (anything other than `stdio:`, `http://`,
  `https://`, `sse://`, `mcp+sse://`) raise `MCPConfigError` at
  decoration time. Pick a supported transport.
- Per-server failures are **isolated**: a broken server logs a `WARN`
  and contributes zero tools; the rest of the app boots normally.
  v0.1 does **not** auto-retry unhealthy servers — `ajolopy doctor`
  (AJ-40) surfaces them.
- Local [`@Tool`](tool.md) methods **always win** over MCP tools on a
  namespaced collision. The MCP tool is dropped at injection time with
  a `WARN`.
- `${VAR}` substitutions resolve at **boot time** against `os.environ`.
  Missing vars mark the server unhealthy (not a fatal error). Use
  `ajolopy env validate` to catch them at deploy time.

## See also

- [`@Agent`](agent.md) / [`@Workflow`](workflow.md) — the consumers of
  MCP tools via `integrations=`.
- [`@MCPServer`](mcp-server.md) — publish your own `@Tool` methods as
  an MCP server.
- [`@Tool`](tool.md) — local tools that coexist with MCP tools on the
  same agent.
- Spec: [`specs/mcp.md`](https://github.com/jcocano/ajolopy/blob/main/specs/mcp.md).
