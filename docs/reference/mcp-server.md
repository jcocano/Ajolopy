# `@MCPServer`

!!! note "Spec"
    Full specification: [`specs/mcp-server.md`](https://github.com/jcocano/ajolopy/blob/main/specs/mcp-server.md)
    · Item: `AJ-60`

## Purpose

`@MCPServer` is a class decorator that publishes a class of
[`@Tool`](tool.md)-decorated methods as an MCP server reachable via
`stdio`, `http`, or `sse`. The decorator discovers tools via the same
machinery [`@Agent`](agent.md) uses and stamps frozen metadata on the
class; booting is the consumer's job (the `ajolopy mcp-serve` CLI for
stdio, `create_app(mcp_servers=[...])` for HTTP / SSE).

Reach for `@MCPServer` whenever you want another agent — most commonly
Claude Desktop — to call into your existing `@Tool` methods.
[`@UseGuards`](use-guards.md) composes naturally with HTTP / SSE
transports for auth.

## Signature

```python
def MCPServer(
    *,
    transport: Literal["stdio", "http", "sse"],
    path: str | None = None,
    name: str | None = None,
    version: str = "0.0.0",
    instructions: str | None = None,
    server_factory: ServerFactory | None = None,
) -> Callable[[type[T]], type[T]]: ...
```

## Quick example

```python
import os

from ajolopy import MCPServer, Tool


@MCPServer(transport="stdio")
class MyTools:
    """Order management helpers exposed to MCP clients."""

    def __init__(self) -> None:
        self._db_url = os.environ["DATABASE_URL"]

    @Tool
    def lookup_order(self, order_id: str) -> dict[str, str]:
        """Fetch a single order by id."""
        return {"id": order_id, "status": "in_transit"}

    @Tool
    async def refund(self, order_id: str, reason: str) -> bool:
        """Issue a refund for an order."""
        return True
```

```text
$ ajolopy mcp-serve myapp.integrations:MyTools
```

## Kwargs

| Kwarg            | Type                                    | Default           | Description |
|------------------|-----------------------------------------|-------------------|-------------|
| `transport`      | `Literal["stdio", "http", "sse"]`       | required          | No default — the user picks. |
| `path`           | `str \| None`                           | `None`            | Required for `http` / `sse`; rejected for `stdio`. Must match `^/[a-zA-Z0-9_\-/]*$`. |
| `name`           | `str \| None`                           | kebab-cased class | MCP `initialize` reports this string. Defaults to the class name kebab-cased (`MyTools` → `"my-tools"`). |
| `version`        | `str`                                   | `"0.0.0"`         | User-supplied semantic version. The framework does NOT auto-read `__version__`. |
| `instructions`   | `str \| None`                           | docstring         | Class docstring (stripped) by default. Set to `None` to omit. |
| `server_factory` | `ServerFactory \| None`                 | `None`            | Custom callable returning a `mcp.server.lowlevel.Server` — escape hatch for the protocol surface. |

## Escape hatches

- **HTTP / SSE mount.** Use `create_app(mcp_servers=[Cls])` (or
  `mount_mcp_servers(app, [...])`) instead of the stdio CLI. Pass a
  pre-built instance to inject constructor arguments:
  `create_app(mcp_servers=[MyTools(db=...)])`.
- **Gate with [`@UseGuards`](use-guards.md).** HTTP / SSE servers
  compose with `@UseGuards` cleanly — guards run before MCP protocol
  negotiation. `stdio` transports reject guards (the parent process is
  the trust boundary).
- **Custom protocol surface.** Pass `server_factory=` a callable that
  returns a lowlevel `Server` to extend the MCP surface (prompts,
  sampling, resources) without waiting for `@Resource`.

## Common gotchas

- The class must declare at least one `@Tool` method. Empty classes
  raise `MCPServerConfigError` at decoration time.
- `@UseGuards` on a `transport="stdio"` server raises
  `MCPServerConfigError` — there is no request to gate. Switch to
  `http` / `sse` for request-level auth.
- Required-arg `__init__` raises at mount time if the class is passed
  directly. Pass a pre-built instance via the mount API instead.
- Tool names visible to MCP clients are the raw `@Tool` method names
  (no `server_key__` prefix — namespacing is a consume-side concern in
  [`@MCP`](mcp.md)).
- The `mcp` SDK is an opt-in dependency. `from ajolopy import MCPServer`
  works without it; booting raises `MCPDependencyError`. Install with
  `pip install ajolopy[mcp]`.

## See also

- [`@MCP`](mcp.md) — the consume-side counterpart.
- [`@Tool`](tool.md) — the methods this primitive publishes.
- [`@UseGuards`](use-guards.md) — auth for HTTP / SSE transports.
- Spec: [`specs/mcp-server.md`](https://github.com/jcocano/ajolopy/blob/main/specs/mcp-server.md).
