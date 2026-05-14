# AJ-60 — `@MCPServer` decorator (publish `@Tool` methods via MCP transports)

> Tracked in [`board.json`](../board.json) as `AJ-60`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth: the user explicitly reopened the locked 10-primitive
> contract (now 11) to add `@MCPServer` alongside `@MCP` (AJ-7) as the
> publish-side counterpart. Brief v4.0 only references the consume side;
> the killer-demo Paso 3 does NOT exercise publish. This item exists so
> Ajolopy apps can expose their own `@Tool`-decorated logic to other MCP
> clients (Claude Desktop, other agent frameworks, web-MCP clients).
>
> The 12th-primitive `@Resource` is split out to AJ-61 (blocked_by AJ-60).

## What

`@MCPServer` is a **class decorator** that turns a class whose methods
are decorated with `@Tool` (AJ-2) into an MCP server reachable via one
of three transports:

| Transport       | Use case                                                                 | How it runs                                       |
|-----------------|--------------------------------------------------------------------------|---------------------------------------------------|
| `stdio`         | Claude Desktop, other CLI agent hosts that spawn the server as a child.  | CLI: `ajolopy mcp-serve <module>:<ClassName>`.    |
| `http`          | Web-MCP clients (streamable-HTTP per the new MCP spec).                  | Auto-mounted on `create_app(mcp_servers=[Cls])`.  |
| `sse`           | Older MCP clients still on the SSE transport.                            | Auto-mounted on `create_app(mcp_servers=[Cls])`.  |

The decorator:

1. Validates its configuration at decoration time (`transport=` valid,
   `path=` required and well-formed for HTTP/SSE / rejected for stdio,
   `name`/`version`/`instructions` typed when supplied, the host class
   has at least one `@Tool`-decorated method, no required-arg `__init__`,
   `auth=True` not allowed on `transport="stdio"`).
2. Discovers the host class's `@Tool` methods at decoration time via
   `ajolopy.agent.tool.discover_tools` (reuses AJ-2 plumbing). The set
   of wire tools is frozen at decoration; per-process the host class is
   instantiated **once** at server boot and the bound tools dispatch
   against that single instance.
3. Stamps `_ajolopy_mcp_server` metadata on the class (transport,
   path, protocol metadata, frozen wire tool list, original class).
4. Stays inert at decoration time — no server starts, no transport
   opens, no auth runs. Booting is the consumer's job (CLI for stdio,
   `create_app(mcp_servers=[...])` for HTTP/SSE).

`@UseGuards` (AJ-17) composes naturally with HTTP/SSE servers: any
guard on the class gates the underlying MCP route before protocol
negotiation runs. stdio rejects `@UseGuards` at decoration (no Request
to gate; the parent process is the trust boundary).

## Why

The wedge user (AI Engineer at a Series A) reaches for `@MCPServer` the
moment they want another agent — most commonly Claude Desktop — to be
able to call into their internal logic (database lookups, internal HTTP
APIs, refund flows). Today they hand-roll the MCP server scaffolding
per project (~200 LoC per service: JSON-RPC routing, tool schema
synthesis, stdio loop, lifecycle, auth). `@MCPServer` collapses that to
a single decorator over an already-existing class of `@Tool` methods.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: drop `@MCPServer(transport="stdio")` on a class
  with `@Tool` methods, run `ajolopy mcp-serve <module>:<ClassName>`,
  done. Or `@MCPServer(transport="http", path="/mcp")` and add the class
  to `create_app(mcp_servers=[Cls])`.
- **Escape hatch**: pass a custom `mcp.server.lowlevel.Server`-shaped
  object via the `server_factory=` kwarg (advanced; primarily for
  framework users who need to extend the MCP protocol surface).

## Public surface (v0.1)

### stdio (CLI launch)

```python
# myapp/integrations.py
from ajolopy import Tool, MCPServer


@MCPServer(transport="stdio")
class MyTools:
    """Order management helpers exposed to MCP clients."""

    def __init__(self) -> None:
        # User wires any deps explicitly here (env / globals).
        # DI via AjolopyFactory is out of scope; see Out-of-scope.
        self._db_url = os.environ["DATABASE_URL"]

    @Tool
    def lookup_order(self, order_id: str) -> dict:
        """Fetch a single order by id."""
        ...

    @Tool
    async def refund(self, order_id: str, reason: str) -> bool:
        """Issue a refund for an order."""
        ...
```

```toml
# Claude Desktop / mcp-host config:
[mcpServers.my-tools]
command = "ajolopy"
args = ["mcp-serve", "myapp.integrations:MyTools"]
```

### HTTP (mounted on the Ajolopy Starlette app)

```python
# myapp/integrations.py
from ajolopy import Tool, MCPServer, UseGuards
from ajolopy.guards import BearerTokenGuard


@UseGuards(BearerTokenGuard(token_env="API_TOKEN"))
@MCPServer(transport="http", path="/mcp", name="my-tools", version="1.0.0")
class MyTools:
    @Tool
    def lookup_order(self, order_id: str) -> dict: ...
```

```python
# myapp/app.py
from ajolopy.http import create_app
from myapp.integrations import MyTools

app = create_app(mcp_servers=[MyTools])
# POST /mcp now serves streamable-HTTP MCP for authenticated clients.
```

### SSE (mounted on the Ajolopy Starlette app)

```python
@MCPServer(transport="sse", path="/mcp-sse")
class MyTools: ...

app = create_app(mcp_servers=[MyTools])
# GET /mcp-sse + POST /mcp-sse/messages handle the SSE handshake pair.
```

### Signature

```python
def MCPServer(
    *,
    transport: Literal["stdio", "http", "sse"],
    path: str | None = None,                # required for http/sse; rejected for stdio
    name: str | None = None,                # default: class.__name__ kebab-cased
    version: str = "0.0.0",                 # user-supplied semantic version
    instructions: str | None = None,        # default: class.__doc__ (stripped)
    server_factory: ServerFactory | None = None,   # escape hatch
) -> Callable[[type[T]], type[T]]: ...
```

- `transport` — required. No default; the user must pick.
- `path` — required (and validated as `^/[a-zA-Z0-9_\-/]*$`) for `http`
  and `sse`. `MCPServerConfigError` at decoration time when missing or
  malformed. Rejected for stdio (no path concept).
- `name` — optional. Default = class name converted from PascalCase to
  kebab-case (`"MyTools"` → `"my-tools"`). MCP `initialize` reports
  this string.
- `version` — optional, default `"0.0.0"`. The framework does NOT try
  to read `__version__` of the user's package — too brittle. Users who
  care override explicitly.
- `instructions` — optional. Default = the class's docstring stripped,
  or `None` if empty.
- `server_factory` — escape hatch. A callable
  `(metadata, tool_bindings) -> mcp.server.lowlevel.Server` that the
  framework calls in place of building the default lowlevel `Server`.
  Allows users to extend the MCP surface (resources, prompts, sampling)
  without waiting for AJ-61.

### Decorated class shape

```python
@MCPServer(transport=..., ...)
class MyTools:
    def __init__(self) -> None: ...    # zero-arg; required-arg → MCPServerConfigError

    @Tool
    def my_method(self, arg: str) -> ReturnType: ...

    @Tool
    async def my_async_method(self, arg: str) -> ReturnType: ...
```

Must have **at least one** `@Tool`-decorated method; the framework
calls `discover_tools(cls, tools=None)` from AJ-2 to extract the
bindings. Zero `@Tool` methods → `MCPServerConfigError` at decoration.

### Auth: `@UseGuards` integration

The decorator composes with `@UseGuards`:

- **`transport="stdio"` + `@UseGuards`** → `MCPServerConfigError` at
  decoration time with the message:
  ```
  @UseGuards is not supported on transport="stdio" — the parent
  process is the trust boundary. Use transport="http" / "sse" if
  you need request-level auth.
  ```
- **`transport="http"` or `"sse"` + `@UseGuards`** → guards run via the
  existing `apply_guard_chain` from AJ-17 BEFORE protocol negotiation.
  A guard rejection produces a normal JSON 401/403 — the MCP client
  sees a transport-level failure, not an MCP error.

### CLI: `ajolopy mcp-serve <module>:<ClassName>`

AJ-60 introduces the FIRST `ajolopy` console-script entry point in the
project. Future CLI work (AJ-32 `new`, AJ-33 `dev`, AJ-34 `generate`,
AJ-36 `env`, AJ-37 `deploy`, AJ-38 `build`, AJ-39 `info`, AJ-40
`doctor`) will extend the same dispatch.

Surface in v0.1:

```text
$ ajolopy --help
usage: ajolopy [-h] {mcp-serve} ...

Ajolopy command-line interface.

subcommands:
  mcp-serve  Run an @MCPServer(transport="stdio") class as a stdio MCP server.

$ ajolopy mcp-serve --help
usage: ajolopy mcp-serve [-h] target

positional arguments:
  target  Module path and class name in the form 'package.module:ClassName'.
```

CLI semantics:

1. Parse `<module>:<class>`. Malformed → `SystemExit(2)` with a usage
   message.
2. Import the module via `importlib.import_module`. Import errors
   bubble with an `EXIT_IMPORT_ERROR` (1).
3. `getattr` the class. Missing attribute → `EXIT_TARGET_NOT_FOUND` (1).
4. Verify the target carries `_ajolopy_mcp_server` metadata AND that
   the transport is `"stdio"`. Otherwise `EXIT_NOT_STDIO_SERVER` (1)
   with a hint pointing at `transport="stdio"`.
5. Instantiate `Cls()`. Required-arg `__init__` raises a clear error.
6. Build the MCP lowlevel `Server`, wire `list_tools`/`call_tool`
   handlers, and run the stdio loop via `mcp.server.stdio.stdio_server`.

### Mount API for HTTP / SSE

`create_app(mcp_servers=[Cls, ...])` mirrors AJ-3's `streams=` kwarg
exactly:

```python
def create_app(
    ...
    streams: list[type | object] | None = None,
    mcp_servers: list[type | object] | None = None,
) -> Starlette: ...
```

A helper `mount_mcp_servers(app, servers)` is the standalone API and
the kwarg is sugar that calls it lazily (same pattern as
`mount_streams`).

Per item:

- **Classes** — instantiated via `Cls()`; one instance per process,
  per `@MCPServer` class.
- **Instances** — bound verbatim (allows the user to wire deps via
  `MyTools(db=...)`).

`mount_mcp_servers` walks each item, reads `_ajolopy_mcp_server`
metadata, builds the lowlevel `Server` once per item, resolves the
`@UseGuards` chain (if any) via `resolve_guard_chain`, and adds routes
to the Starlette app:

| Transport | Routes added                                                                |
|-----------|-----------------------------------------------------------------------------|
| `http`    | `POST <path>` — the streamable-HTTP endpoint.                                |
| `sse`     | `GET <path>` + `POST <path>/messages` — the SSE handshake pair.             |

Both routes pass through `apply_guard_chain` from AJ-17 when guards
are configured. Guards run BEFORE the MCP `StreamableHTTPSessionManager`
/ `SseServerTransport` is invoked.

### Tool dispatch contract

For each incoming MCP `tools/call` request:

1. Look up the tool by name in the frozen wire-tool list.
2. Validate arguments via the `ToolBinding.metadata.validate_arguments`
   helper (reuses AJ-2's Pydantic-backed validation).
3. Resolve the bound `self` (the cached single instance).
4. Async `@Tool` method → `await fn(self, **kwargs)`.
   Sync `@Tool` method → `await asyncio.to_thread(fn, self, **kwargs)`
   (same pattern as `AgentRuntime._execute_single_tool`).
5. Return the result wrapped as MCP `TextContent` (string results pass
   through; structured results are JSON-encoded via the same
   `_stringify_tool_result` shape).
6. Tool exceptions (ValidationError, generic `Exception`) are captured
   and returned to the MCP client as `CallToolResult(isError=True,
   content=[TextContent(text=str(exc))])` — the client decides whether
   to surface to the LLM or retry. The exception is also logged at
   `ERROR` via the framework logger.

The tool name visible to MCP clients is the `@Tool` method's name (raw,
NOT namespaced — namespace prefixes are a consume-side concern from
AJ-7).

### Observability (mirrors AJ-28 / AJ-7)

Each tool invocation produces:

```
mcp_server.call_tool {server_name}/{tool_name}
```

Span attributes:

| Attribute                       | Value                                     |
|---------------------------------|-------------------------------------------|
| `ajolopy.mcp_server.name`       | `name` (kebab-cased class name by default). |
| `ajolopy.mcp_server.transport`  | `"stdio"`, `"http"`, or `"sse"`.            |
| `ajolopy.mcp_server.tool.name`  | the raw tool method name.                  |
| `ajolopy.mcp_server.is_error`   | `true` if the dispatch raised.            |
| `ajolopy.mcp_server.duration_ms`| wall-clock duration.                      |

The server boot path (stdio loop start or HTTP/SSE mount) emits one
`mcp_server.boot {server_name}` span for visibility on slow `__init__`
or env-var resolution.

No cost roll-up — tool calls don't consume LLM tokens.

### Lifecycle integration

- **stdio**: lifetime = the CLI process. On EOF on stdin or SIGTERM,
  the stdio loop tears down via `mcp.server.stdio.stdio_server`'s
  context manager. The class instance is garbage-collected after the
  loop exits.
- **HTTP / SSE**: lifetime = the host Starlette app's lifetime. The
  class instances are created at `create_app` time (or at the
  `mount_mcp_servers` call site for the standalone path) and live for
  the duration of the ASGI process. No `on_app_shutdown` hook required
  in v0.1 — the lowlevel `Server` and its transports clean up via
  Starlette's existing shutdown lifecycle.

## Design rules

- **Magical default**: one decorator + the transport + (path for
  HTTP/SSE) is the entire surface for 90% of cases. Tool schemas come
  from `@Tool` automatically. Auth comes from `@UseGuards`
  automatically.
- **Escape hatch**: `server_factory=` lets the user replace the
  framework-built `Server`. This is also the planned extension point
  for AJ-61 (`@Resource`) — the framework will wrap the user's
  resource declarations into a `server_factory` internally so AJ-60
  remains untouched.
- **Two parallel packages**: `src/ajolopy/mcp/` stays AJ-7 consume
  only. `src/ajolopy/mcp_server/` is the new AJ-60 publish home. They
  share the `ajolopy[mcp]` extra but have NO import-time dependency on
  each other.
- **CLI is minimal**: a single `mcp-serve` subcommand and a thin
  dispatcher. The CLI infrastructure (`src/ajolopy/cli/`) is
  intentionally tiny so it does not preempt design decisions for the
  larger CLI items (AJ-32 ff).
- **Per-process single instance**: tool methods can share `self`
  state freely. The user is responsible for thread/coroutine safety
  inside those methods (same as `@Stream` mount-instance
  semantics — AJ-3).
- **No `@Agent` exposure**: this item does NOT expose `@Agent` classes
  as MCP servers. That semantic mismatch (agents converse, MCP servers
  expose discrete tools) is intentionally deferred.

## Out of scope for this item

- **`@Resource` / resources protocol surface** → AJ-61. The
  `server_factory=` escape hatch is the planned integration point.
- **`prompts` protocol surface** → not in v0.1. Stretch goal for v0.2.
- **`sampling` (server-initiated LLM requests)** → not in v0.1.
- **DI for `@MCPServer` instances** → not in v0.1. Zero-arg `Cls()`
  for the class path; pre-built instances for the with-deps path. Full
  DI via `AjolopyFactory` is a v0.2 concern (AJ-14 cross-cut).
- **Multi-instance fan-out on HTTP** → not in v0.1. Each `@MCPServer`
  class boots ONE instance per process. Stateful tools that need
  per-request isolation should be split into smaller methods or
  designed without instance state.
- **Streaming tool results** → not in v0.1. Tool dispatch is
  request/response; partial streaming responses are an MCP optional
  feature deferred to v0.2.
- **Auto-restart on stdio crash** → not in v0.1. If the stdio loop
  raises, the process exits and the parent (Claude Desktop / mcp-host)
  is responsible for restarting.
- **MCP server discovery** (advertising via DNS-SD or similar) → not
  in v0.1. Out of MCP spec scope too.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`. **The `mcp` SDK is mocked at the transport
seam** — no real subprocesses, no real MCP clients in CI. Use a fake
lowlevel `Server` in `tests/mcp_server/fakes.py` for dispatch tests;
the CLI smoke test exercises the real `stdio_server` context manager
but with stdin/stdout piped from the test process.

### Decoration-time validation

- [x] `@MCPServer(transport="stdio")` on a class with at least one
      `@Tool` method stamps `_ajolopy_mcp_server` metadata and
      preserves the class type for pyright.
- [x] `@MCPServer(transport="http", path="/mcp")` works similarly.
- [x] `@MCPServer(transport="sse", path="/mcp-sse")` works similarly.
- [x] `@MCPServer(transport="stdio", path="/x")` raises
      `MCPServerConfigError` ("path is not applicable to stdio").
- [x] `@MCPServer(transport="http")` (no `path`) raises
      `MCPServerConfigError`.
- [x] `@MCPServer(transport="http", path="no-leading-slash")` raises
      `MCPServerConfigError`.
- [x] `@MCPServer(transport="bogus")` raises `MCPServerConfigError`
      listing the accepted values.
- [x] `@MCPServer(transport="stdio")` on a class with NO `@Tool`
      methods raises `MCPServerConfigError`.
- [x] `@MCPServer(transport="stdio")` on a class whose `__init__`
      requires arguments raises `MCPServerConfigError` with a hint to
      pass a pre-built instance via the mount API or rewrite the
      class.
- [x] `name="..."` overrides the default kebab-case derivation.
      Missing → `MyToolsBundle` becomes `"my-tools-bundle"`.
- [x] `version="..."` overrides the default `"0.0.0"`. Default
      remains `"0.0.0"`; the framework does NOT try to introspect the
      user's package version.
- [x] `instructions="..."` overrides the docstring-derived default.
      Empty / missing docstring + missing kwarg → `instructions=None`
      on the protocol handshake.
- [x] `server_factory=` accepts any zero-arg callable; non-callable →
      `MCPServerConfigError`.

### `@UseGuards` composition

- [x] `@UseGuards(BearerTokenGuard(...))` above
      `@MCPServer(transport="http", path="/mcp")` mounts cleanly and
      gates the route (a missing/invalid token returns 401/403 BEFORE
      MCP protocol negotiation).
- [x] Same for `transport="sse"`.
- [x] `@UseGuards(...)` on `transport="stdio"` raises
      `MCPServerConfigError` at decoration time with the message
      naming stdio's trust boundary.

### CLI: `ajolopy mcp-serve`

- [x] `ajolopy --help` runs successfully and lists `mcp-serve` as the
      single subcommand.
- [x] `ajolopy mcp-serve --help` prints usage referencing
      `package.module:ClassName`.
- [x] `ajolopy mcp-serve invalid-target-format` exits with code 2 and
      a usage message.
- [x] `ajolopy mcp-serve no_such_module:Cls` exits with code 1 and a
      clear "module not found" error.
- [x] `ajolopy mcp-serve mod:no_such_class` exits with code 1 and a
      clear "attribute not found" error.
- [x] `ajolopy mcp-serve mod:NotAnMCPServer` exits with code 1
      pointing at `@MCPServer(transport="stdio")`.
- [x] `ajolopy mcp-serve mod:HTTPOnlyServer` exits with code 1
      explaining that the target is `transport="http"` (not stdio).
- [x] `ajolopy mcp-serve mod:GoodStdioServer` against a class with a
      fake stdio loop returns 0 after a clean shutdown
      (`StopAsyncIteration` from a piped stdin reader).

### HTTP / SSE mount

- [x] `create_app(mcp_servers=[Cls])` adds the expected route(s):
      `POST <path>` for HTTP; `GET <path>` + `POST <path>/messages`
      for SSE.
- [x] `create_app(mcp_servers=[instance])` does NOT call `Cls()` and
      binds the supplied instance.
- [x] `mount_mcp_servers(app, items)` is the standalone API and
      `create_app(mcp_servers=...)` is equivalent.
- [x] A class with required-arg `__init__` mounted via
      `[Cls]` (not an instance) raises `MCPServerConfigError` at mount
      time with the "pass a pre-built instance" hint.
- [x] Two `@MCPServer` classes with overlapping `path` raise
      `MCPServerConfigError` listing both class names.

### Tool dispatch

- [x] An MCP `tools/list` request returns the wire tool list matching
      `discover_tools(cls)`: each tool's `name`, `description`, and
      `input_schema` mirror AJ-2's `to_wire_tool()`.
- [x] An MCP `tools/call` for an async `@Tool` method runs the
      coroutine and returns the result as `TextContent`.
- [x] An MCP `tools/call` for a sync `@Tool` method runs via
      `asyncio.to_thread`.
- [x] Tool arguments are validated through the Pydantic schema; bad
      arguments return `CallToolResult(isError=True, ...)` with the
      validation message.
- [x] A tool method raising an exception returns
      `CallToolResult(isError=True, ...)` with `str(exc)` as the body;
      the exception is logged at `ERROR`.
- [x] String results pass through verbatim.
- [x] Dict / Pydantic-model results are JSON-encoded (same shape as
      `_stringify_tool_result`).
- [x] One instance is created at boot; subsequent tool calls share
      `self` (verified by mutating a counter across calls).

### Observability

- [x] `mcp_server.call_tool {server_name}/{tool_name}` span fires per
      dispatch with the documented attribute set.
- [x] `mcp_server.boot {server_name}` span fires once per server
      startup (CLI stdio boot + each HTTP/SSE mount).
- [x] `ajolopy.mcp_server.is_error=true` set on dispatch failures.
- [x] Spans DO NOT contribute to `ajolopy.cost_usd.total`.

### Public re-exports

- [x] `from ajolopy import MCPServer` works.
- [x] `from ajolopy.mcp_server import (MCPServer, MCPServerError,
      MCPServerConfigError, MCPServerRuntimeError, mount_mcp_servers,
      ServerFactory)` works.
- [x] `MCPServer` is added to `src/ajolopy/__init__.py`'s `__all__`
      alongside other primitives.
- [x] `create_app(mcp_servers=...)` kwarg signature matches the new
      surface; passing `None` (the default) is a no-op (the existing
      `streams` kwarg behaviour is unchanged).

### Dependency surface

- [x] `from ajolopy import MCPServer` works without the `mcp` extra
      installed (same lazy-import pattern as AJ-7).
- [x] `@MCPServer(transport=...)` at decoration time works without
      the `mcp` extra.
- [x] Booting a server (CLI invocation or `create_app(mcp_servers=...)`)
      without `mcp` installed raises `MCPDependencyError` with a
      `pip install ajolopy[mcp]` hint.

## Implementation pointers

- Source: `src/ajolopy/mcp_server/` (new package).
  - `__init__.py` — public re-exports.
  - `decorator.py` — `MCPServer(...)` factory; validation; metadata
    stamping. Imports `discover_tools` from
    `ajolopy.agent.tool` to extract the frozen wire tool list at
    decoration time.
  - `metadata.py` — `MCPServerMetadata` dataclass + helpers for the
    kebab-case `name` default + docstring stripping.
  - `runtime.py` — `MCPServerRuntime`: builds the lowlevel `Server`
    from metadata + tool bindings, wires `list_tools`/`call_tool`
    handlers, owns the dispatch path.
  - `transports/__init__.py`
  - `transports/stdio.py` — `run_stdio(runtime)` async entry called by
    the CLI.
  - `transports/http.py` — ASGI handler factory using
    `mcp.server.streamable_http.StreamableHTTPSessionManager`.
  - `transports/sse.py` — ASGI handler factory using
    `mcp.server.sse.SseServerTransport`.
  - `mount.py` — `mount_mcp_servers(app, items)`, dedup, guard
    integration via `resolve_guard_chain` + `apply_guard_chain`
    (AJ-17), path-collision detection.
  - `errors.py` — `MCPServerError`, `MCPServerConfigError`,
    `MCPServerRuntimeError`, plus reuse of `MCPDependencyError`
    from `ajolopy.mcp.errors`.
- Source: `src/ajolopy/cli/` (new package, FIRST CLI entry).
  - `__init__.py` — exports `main()`.
  - `dispatcher.py` — argparse root + subcommand registry. Future CLI
    items (AJ-32 ff) extend the registry without touching `main()`.
  - `commands/__init__.py`
  - `commands/mcp_serve.py` — the `mcp-serve` subcommand handler.
- `pyproject.toml` — add `[project.scripts] ajolopy = "ajolopy.cli:main"`.
- Cross-cut to `src/ajolopy/http/app.py`:
  - Add `mcp_servers: list[type | object] | None = None` kwarg on
    `create_app`. Lazy import `mount_mcp_servers` to avoid a cycle.
- Cross-cut to `src/ajolopy/observability/conventions.py`:
  - New span name helpers `mcp_server_call_tool_span_name`,
    `mcp_server_boot_span_name`.
  - New attribute constants `AJOLOPY_MCP_SERVER_NAME`,
    `AJOLOPY_MCP_SERVER_TRANSPORT`, `AJOLOPY_MCP_SERVER_TOOL_NAME`,
    `AJOLOPY_MCP_SERVER_IS_ERROR`, `AJOLOPY_MCP_SERVER_DURATION_MS`.
- Tests: `tests/mcp_server/` (new).
  - `fakes.py` — `FakeMCPLowLevelServer` + helpers.
  - `test_decorator_validation.py`
  - `test_metadata_defaults.py`
  - `test_tool_dispatch.py`
  - `test_guards_composition.py`
  - `test_cli_mcp_serve.py`
  - `test_http_mount.py`
  - `test_sse_mount.py`
  - `test_observability.py`
  - `test_public_api.py`
  - `test_dependency_surface.py`
- Runtime deps: none new. `mcp>=1.0.0` already ships via the
  `ajolopy[mcp]` extra from AJ-7.

## Implementation notes

- **2026-05-14 (PR landing notes).**
  - `@UseGuards(stdio)` is detected in two places: the decorator's
    `_validate_no_stdio_guards` catches the "guards-below-MCPServer"
    ordering at decoration time (the only case where Python's decorator
    semantics let `@MCPServer` see the guard stamp). The "guards-above"
    ordering is caught at mount time via `_read_metadata` in
    `mount.py`, so HTTP / SSE callers still get a clear
    `MCPServerConfigError` if they accidentally pair the stamps with a
    stdio target. The CLI never sees guards (stdio targets reject
    `@UseGuards` at decoration), so the CLI does not duplicate the
    check.
  - The `mcp` SDK's `StreamableHTTPSessionManager.run()` is documented
    as call-once and must live inside the host app's lifespan. The
    mount layer composes it into the Starlette router's
    `lifespan_context` via a thin `@asynccontextmanager`-wrapped
    helper (`_chain_lifespan`). SSE uses `SseServerTransport`
    directly; each request opens its own connect_sse session so no
    long-lived lifespan plumbing is required there.
  - Sentinel `_AlreadySentResponse` (`transports/http.py` +
    `transports/sse.py`) is a `starlette.responses.Response` subclass
    whose `__call__` is a no-op. The MCP transports speak ASGI
    directly via `request._send`; Starlette's `Route` will still call
    the returned `Response` as ASGI, and the no-op `__call__` prevents
    a second response from being written.
  - The lowlevel SDK's `Server.run(read_stream, write_stream,
    initialization_options)` takes positional streams plus options;
    the SDK reference snippets in the task instructions were
    accurate. The session manager's run() context is required even
    for stateful mode -- not just for streaming.
  - The `[project.scripts] ajolopy = "ajolopy.cli:main"` entry point
    runs `uv sync` is required after first install for the binary to
    show up in `.venv/bin`.
  - The CLI smoke test (`test_runs_stdio_target_with_real_sdk_eof`)
    exercises the real `mcp.server.stdio.stdio_server` with an
    immediate-EOF `BytesIO` stdin. The reader's memory object stream
    closes cleanly, which causes `Server.run` to return and the CLI
    to exit 0 -- no subprocess required.
  - The runtime emits `mcp_server.boot` once per mounted server. The
    HTTP / SSE mount calls `runtime.emit_boot_span()` + materialises
    `runtime.instance` at registration time so slow `__init__` /
    env-var resolution surfaces in traces without waiting for the
    first request.
  - `discover_tools(cls, None)` (AJ-2) is reused verbatim; we ignore
    its returned `extra_instances` because `@MCPServer` does not
    expose external `tools=[...]` plumbing in v0.1.
