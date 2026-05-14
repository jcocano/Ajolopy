# AJ-7 — `@MCP` decorator (consume external MCP servers)

> Tracked in [`board.json`](../board.json) as `AJ-7`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §4 (Killer demo Paso 3) and
> `01 - Primitivas core - especificacion detallada` §`@MCP`. If this file ever
> conflicts with the Brief, the Brief wins — with three recorded divergences
> noted under "Out of scope": publish is split out to AJ-60, the named
> registry of servers is dropped (explicit specs only), and the primitive
> count is now 11 (the user explicitly reopened the locked 10 to add
> `@MCPServer` to the contract).

## What

`@MCP` is a **class decorator** that turns a Python class into a
**connection-and-tool-discovery declaration** for one or more external MCP
servers. The decorator:

1. Validates its configuration at decoration time (`servers=` non-empty,
   each entry is a recognized spec, optional `auth=` keys exist in
   `servers=` when `servers=` is a dict).
2. Stamps the class with `_ajolopy_mcp` metadata (the parsed list of
   `(server_key, spec, auth)` triples).
3. Stays inert at decoration time — no processes are spawned, no
   connections opened. The class is a **declaration**, not a live object.
4. **Eager discovery happens at factory boot.** The factory (AJ-14)
   resolves every `@Agent` and `@Workflow` that references this `@MCP`
   class via `integrations=` (kwarg or class attribute), then asks the
   per-process `MCPRegistry` (a connection pool keyed by canonical spec)
   to open one connection per unique spec across the whole app and
   discover tools. Per-server failures are logged at `WARN` and continue;
   the affected server contributes zero tools to the agent's tool list.
5. **Per-process connection pool, shared across `@MCP` classes.** Two
   `@MCP` classes that both reference `"stdio:npx -y @mcp/github"` share
   ONE child process. The pool is keyed by the canonical spec string
   (normalised whitespace + casefolded scheme). Released on
   `on_app_shutdown` — every connection is closed and child processes
   killed cleanly.
6. **Tools surface to the LLM** with namespaced names
   `<server_key>__<tool_name>`. The agent's own `@Tool` methods keep
   their raw names. Collisions across servers raise `MCPConfigError` at
   discovery time (caught + logged + dropped, same as a server failure;
   the second-discovered tool is the one suppressed).

## Why

Brief v4.0 §4 names `@MCP` as the primitive that closes the killer demo
Paso 3: three specialist `@Agent` classes orchestrated by `@Workflow`,
each consuming tools from `["zendesk", "stripe", "linear"]` MCP servers.
The wedge user (AI Engineer at a Series A startup) hits this the moment
their support agent needs to actually DO something — open Zendesk
tickets, refund Stripe payments, file Linear bugs — instead of just
talking. Today they wire each integration manually (~50–100 LoC per
service: SDK setup, auth, schema synthesis, error handling). `@MCP`
collapses that to one decorator + one shared connection per server.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: pass `servers=[...]` with a list of explicit specs
  (no registry of named servers). The framework spawns/connects each at
  boot, discovers their tools, namespaces them, and injects them into
  every agent that references this `@MCP` class.
- **Escape hatch**: subclass `MCPClient` (an ABC) and pass an instance
  into `servers=` instead of a string spec. The framework uses your
  client verbatim — your `connect()`, `list_tools()`, `call_tool()`,
  `aclose()` implementations win.

## Public surface (v0.1)

```python
from typing import Annotated

from ajolopy import Agent, MCP, Stream, Workflow
from ajolopy.http import Body, create_app
from pydantic import BaseModel


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
    model="claude-sonnet-4-7",
    system="You are an engineering on-call assistant.",
    integrations=[Integrations],
)
class OnCall:
    """Handle incidents: open Linear bugs, look up GitHub PRs, ..."""


class ChatRequest(BaseModel):
    message: str


@Stream("/oncall")
async def respond(self, body: Annotated[ChatRequest, Body()]):
    async for chunk in self.stream(body.message):
        yield chunk


app = create_app(streams=[OnCall])
```

The LLM sees four tools on this agent:

```
github__list_issues
github__create_issue
linear__create_issue
linear__list_workflow_states
```

…the literal set depending on what the live MCP servers report at boot.

### Signature

```python
def MCP(
    *,
    servers: dict[str, ServerSpec] | list[ServerSpec],
    auth: dict[str, AuthSpec] | None = None,
    timeout: float = 30.0,
) -> Callable[[type[T]], type[T]]: ...

ServerSpec = str | MCPClient   # string spec OR custom-client instance
AuthSpec   = dict[str, Any]    # per-server auth dict (see "Auth" below)
```

- `servers` — non-empty; either a dict keyed by user-chosen server key
  (`"github"`, `"linear"`) or a list of specs (keys auto-derived as
  `"server_0"`, `"server_1"`, …). The dict form is strongly recommended
  for any non-trivial app; auto-keys are a convenience for quick demos.
- `auth` — optional. Dict keyed by the same server keys as in `servers=`.
  Unknown keys → `MCPConfigError` at decoration time. See "Auth" below
  for the per-transport contract.
- `timeout` — per-tool-call timeout in seconds. Default 30. Applies to
  `call_tool` operations; connect/list-tools at boot use a separate
  internal 10-second handshake timeout.

### Server spec format

A string `ServerSpec` is recognised by its scheme prefix (case-insensitive):

| Spec prefix         | Transport                                                                 |
|---------------------|---------------------------------------------------------------------------|
| `stdio:<command>`   | stdio. The command is split with `shlex.split`; argv[0] is the executable. Env vars come from `auth[<key>]["env"]`. |
| `http://`, `https://` | streamable-HTTP transport (MCP spec). Headers from `auth[<key>]`.       |
| `sse://`, `mcp+sse://` | SSE transport. Headers from `auth[<key>]`. `sse://...` is normalised to `https://...` for the underlying SSE channel. |

Anything else → `MCPConfigError` with a message listing accepted prefixes.

An instance `ServerSpec` (an `MCPClient` subclass) bypasses parsing — the
framework calls `client.connect()` directly. Auth is the instance's own
responsibility; passing `auth[<key>]` for an instance entry raises
`MCPConfigError`.

### Auth dict

Per-server auth dict is interpreted by the transport that handles it:

| Transport         | Recognised keys                                                                  |
|-------------------|----------------------------------------------------------------------------------|
| stdio             | `env: dict[str, str]` — environment variables for the child process.            |
| http / sse        | `token: str` → sets `Authorization: Bearer <token>` header. `headers: dict[str, str]` → merged into request headers (overrides `token`-derived header). |
| custom (`MCPClient` instance) | Auth dict MUST NOT be provided; instance owns its credentials.         |

`${ENV_VAR}` substitution is supported inside string values (recursive
into nested dicts). Missing env vars at boot → `MCPConfigError` (boot
fails for the affected server, log WARN + continue per the resilience
rule).

### `integrations=` wiring

The decorated `@MCP` class is referenced via the `integrations=` mechanism
on consumer primitives. Two forms are accepted (kwarg wins if both):

```python
# Form 1 — kwarg (recommended for consistency with other config):
@Agent(model="...", system="...", integrations=[Integrations])
class Worker: ...

# Form 2 — class attribute (per Brief v4.0):
@Agent(model="...", system="...")
class Worker:
    integrations = [Integrations]

# If both are present, kwarg wins. An INFO log notes the shadowed attribute.
```

The same shape applies to `@Workflow(integrations=[...])` (the kwarg was
reserved in AJ-6 and raised `WorkflowConfigError`; this item flips it to
real wiring). On `@Workflow`, MCP tools are injected into the **coordinator's**
synthetic tool list and ALSO into every agent in `agents=`. The
coordinator can delegate to a specialist OR call an MCP tool directly.

### `MCPClient` ABC (escape hatch)

```python
class MCPClient(abc.ABC):
    """Custom transport / client. Pass an instance into `servers=`."""

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def list_tools(self) -> list[ToolSchema]: ...

    @abc.abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...

    @abc.abstractmethod
    async def aclose(self) -> None: ...

    @property
    @abc.abstractmethod
    def canonical_spec(self) -> str:
        """Unique identifier used by the registry to dedupe connections."""
```

`ToolSchema` is a small dataclass: `name: str`, `description: str`,
`input_schema: dict[str, Any]` (JSON Schema for the tool's arguments).
This is the same shape we re-wrap MCP SDK `Tool` objects into.

### `MCPRegistry` (process-wide pool)

Internal but importable for advanced users (e.g., test setup):

```python
class MCPRegistry:
    async def get_or_open(self, spec: str | MCPClient, auth: AuthSpec | None) -> MCPClient: ...
    async def shutdown(self) -> None: ...
    def discovered_tools(self) -> dict[str, list[ToolSchema]]: ...
```

The registry is a module-level singleton (`get_mcp_registry()`) lazily
initialised. `AjolopyFactory.create()` calls `registry.connect_all_for(module)`
during bootstrap (after DI resolution, before lifecycle `on_app_bootstrap`),
and registers `registry.shutdown()` as an `on_app_shutdown` handler.

Standalone use (no factory): users must drive the registry themselves —
typically inside `asyncio.run(...)` with a `try/finally registry.shutdown()`.
The `@MCP` decorator metadata is enough to discover what to connect.

### Tool naming and injection

For each `@MCP` class referenced by an agent:

1. The registry returns the merged tool list per `(server_key, tool_name)`
   pair (every server contributes its discovered tools).
2. Each tool is re-wrapped as a `Tool` wire object with `name =
   f"{server_key}__{tool_name}"` and `description` / `input_schema`
   copied from the MCP-discovered schema.
3. These wire tools are appended to the agent's tool list (after the
   agent's own `@Tool`-decorated methods). The agent's `AgentRuntime`
   resolves them at execution time via a new lookup path
   (`_mcp_by_namespaced_name`).
4. On invocation, the runtime calls `registry.call_tool(server_key,
   raw_name, args, timeout=self._mcp_timeout)`. The returned string is
   the `tool_result` content. MCP errors (`isError=true` from the server)
   become `tool_result` with `is_error=True` so the LLM can adapt.
5. Tool name collisions: if two MCP servers in the same `@MCP` class
   expose tools that produce identical namespaced names (impossible if
   keys are unique, possible if the auto-key path collides), or if an
   MCP tool's namespaced name collides with the agent's own `@Tool`
   method name, the MCP tool is **dropped** at injection time with a
   WARN log — local `@Tool` methods always win.

### Boot-time resilience

- Connection / handshake failure for a server → log WARN with the spec
  and reason, mark `server_key` as `unhealthy`, register zero tools from
  it, **do not** abort the factory boot. Agents that use the affected
  `@MCP` class boot with reduced tool sets.
- Tool-list call fails after a successful connect → same treatment; the
  connection is closed and the server is unhealthy.
- Unknown auth env var (`${VAR}` unset) → log WARN, mark server unhealthy.
- An unhealthy server is **not retried** in v0.1. (`ajolopy doctor`
  helper for live diagnostics is AJ-40.)

### Observability (mirrors AJ-28)

Every MCP tool call emits a child span underneath the existing
`execute_tool {namespaced_name}` span the agent runtime already opens:

```
execute_tool {server_key__tool_name}                ← existing (AJ-28)
└── mcp.call_tool {server_key}/{tool_name}          ← new
```

New span attributes (in `src/ajolopy/observability/conventions.py`):

| Attribute              | Where             | Value |
|------------------------|-------------------|-------|
| `mcp.server.key`       | `mcp.call_tool`   | server key (`"github"`). |
| `mcp.tool.name`        | `mcp.call_tool`   | raw tool name (`"create_issue"`). |
| `mcp.transport`        | `mcp.call_tool`   | `"stdio"`, `"http"`, `"sse"`, or `"custom"`. |
| `mcp.duration_ms`      | `mcp.call_tool`   | wall-clock duration of the call. |
| `mcp.is_error`         | `mcp.call_tool`   | `true` when the server returned `isError=true`. |

Boot-time discovery also emits ephemeral spans
`mcp.discover {server_key}` for the connect + list_tools roundtrip;
useful for diagnosing slow MCP boots.

Cost: MCP tool calls have no LLM cost so they DO NOT contribute to
`ajolopy.cost_usd.total`. The roll-up keeps ignoring `mcp.call_tool`
spans.

### Lifecycle integration

`AjolopyFactory.create(AppModule, ...)` gains one new step:

```
1. Resolve DI graph
2. Validate env / configs
3. Discover MCP integrations:
   - Walk every @Agent and @Workflow under the module tree.
   - Collect every @MCP class referenced via integrations=
     (kwarg OR class attribute, kwarg wins).
   - For each unique spec across all collected @MCP classes:
     - registry.get_or_open(spec, auth) → MCPClient
     - client.list_tools() → register namespaced ToolSchemas
4. Wire tools into every consuming agent
5. Run on_app_bootstrap hooks
```

`on_app_shutdown` calls `registry.shutdown()` which iterates the pool and
closes each client gracefully (stdio: `aclose` sends SIGTERM with a 5s
grace period, then SIGKILL).

## Design rules

- **Magical default**: one decorator + a server map. The framework
  handles connection lifecycle, tool discovery, tool injection, error
  isolation, and shutdown. The user writes zero MCP plumbing.
- **Escape hatches**:
  - Subclass `MCPClient` and pass an instance into `servers=` for
    non-standard transports.
  - Reach into `get_mcp_registry()` for custom warmup / introspection.
- **Strictly opt-in dependency**: importing `from ajolopy.mcp import MCP`
  works without the `mcp` extra installed; instantiating the decorator
  works (it only validates config). Actually CONNECTING (factory boot or
  standalone registry use) raises `MCPDependencyError` with a clear
  `pip install ajolopy[mcp]` pointer if the SDK is missing.
- **Per-server failure isolation**: never let one bad MCP server tank
  the whole app's startup.
- **No silent globals**: the registry is a singleton but is fully
  resettable via `reset_mcp_registry()` for tests.

## Out of scope for this item

- **`@MCPServer` publish** → AJ-60. Reuses the canonical-spec utilities,
  observability conventions, and the lifecycle hook integration that
  AJ-7 establishes, but exposes its own decorator + transport surface.
- **Named-server registry** (e.g. `servers=["github"]` mapped to a known
  command) → not in v0.1. Brief shows the named form; we deviate to
  avoid maintaining a curated table that goes stale. Users write the
  explicit `stdio:npx -y @modelcontextprotocol/server-github` string.
- **Auto-retry of unhealthy servers** → not in v0.1. `ajolopy doctor`
  (AJ-40) will surface this. v0.1: one connect attempt at boot.
- **Dynamic re-discovery** → not in v0.1. Tool sets are frozen at boot.
- **MCP `roots`, `prompts`, `sampling`, `resources`** → not in v0.1.
  Only `tools` are consumed. The MCP SDK exposes these surfaces but
  Ajolopy v0.1 limits itself to the function-calling story.
- **OAuth / dynamic credential refresh for HTTP/SSE** → not in v0.1.
  Headers / tokens are static; `${ENV_VAR}` substitution at boot covers
  the 90% case. AJ-17 (`@UseGuards`) may unlock more later.
- **Concurrency caps on MCP tool calls** → not in v0.1. Calls are
  dispatched concurrently with the rest of the tool-loop's
  `asyncio.gather`. A `concurrency: int | None = None` kwarg can land
  later if needed.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. **Network is mocked** at the `MCPClient` interface;
no real MCP servers or child processes run in CI. Use a fake `MCPClient`
implementation in `tests/mcp/fakes.py`.

### Decoration-time validation

- [ ] `@MCP(servers={"github": "stdio:npx -y @mcp/github"})` on a class
      returns a class whose `_ajolopy_mcp` metadata contains exactly
      one parsed entry `(key="github", spec_str="stdio:npx -y @mcp/github",
      transport="stdio", auth=None)`. The class type is preserved
      (pyright sees the original class).
- [ ] `@MCP(servers=[])` raises `MCPConfigError` at decoration time
      naming the class.
- [ ] `@MCP(servers={"github": "ftp://..."})` (unrecognised scheme)
      raises `MCPConfigError` listing accepted prefixes.
- [ ] `@MCP(servers=["stdio:..."])` (list form) auto-derives the key
      `"server_0"`; a two-entry list yields `"server_0"` and
      `"server_1"`.
- [ ] `@MCP(servers={"a": "stdio:..."}, auth={"b": {...}})` raises
      `MCPConfigError` because `b` is not a server key.
- [ ] `@MCP(servers={"x": CustomClient()}, auth={"x": {...}})` raises
      `MCPConfigError` because instance entries own their auth.
- [ ] `@MCP(servers={"x": "stdio:..."}, timeout=0)` and any negative
      timeout raise `MCPConfigError`.
- [ ] `${VAR}` substitution inside auth string values is resolved at
      DECORATION time when the env var is present; absent vars are
      tolerated until boot (where they emit a WARN and mark unhealthy).

### Server spec parsing

- [ ] `stdio:npx -y @mcp/github` parses to `command=["npx", "-y",
      "@mcp/github"]` with `shlex.split` semantics.
- [ ] `stdio:python -m my.server --flag "hello world"` honours quoted
      args.
- [ ] `https://api.example.com/mcp` and `http://localhost:9000/mcp`
      both classify as `transport="http"`.
- [ ] `sse://example.com/sse` and `mcp+sse://example.com/sse` both
      classify as `transport="sse"`. The framework normalises to a
      runnable URL form internally.
- [ ] An `MCPClient` instance entry sets `transport="custom"` and
      copies the instance verbatim into metadata.

### `integrations=` wiring (cross-cuts to AJ-1, AJ-6)

- [ ] `@Agent(model="...", system="...", integrations=[Integrations])`
      stamps the agent runtime with the `@MCP` class set; the agent's
      wire tool list (post-boot) contains both `@Tool` methods and
      `<server_key>__<tool_name>` MCP entries.
- [ ] `@Agent(model="...", system="...")` on a class that defines
      `integrations = [Integrations]` as a class attribute works
      identically.
- [ ] When BOTH kwarg and class attribute are present, the kwarg's
      list is used and an INFO message logs the shadowed attribute.
- [ ] `@Workflow(coordinator=..., agents=[A, B], integrations=[I])`
      no longer raises (the AJ-6 reservation flips to wiring). MCP
      tools are exposed in the coordinator's synthetic tool list
      AND in each delegated agent's wire tool list.
- [ ] `@Workflow(agents=[A, B])` on a class that defines
      `integrations = [I]` works identically.
- [ ] Two agents that both reference the same `@MCP` class share the
      same set of registered tools (one discovery roundtrip across
      the whole app).
- [ ] An agent that references a `@MCP` class with two servers, one
      healthy and one unhealthy, boots with only the healthy server's
      tools and a WARN log for the unhealthy one.

### Registry / process sharing

- [ ] Two `@MCP` classes that both reference `"stdio:npx -y @mcp/x"`
      open exactly ONE child process at boot (verified by patching the
      MCP SDK stdio client and asserting one connect call). Both
      classes see the same tool list.
- [ ] The same string with leading/trailing whitespace or extra
      internal spaces is canonicalised before pool lookup so it still
      dedupes.
- [ ] `MCPClient` instances are NOT deduped — passing two instances
      with the same `canonical_spec` still results in two `connect()`
      calls (the framework trusts that instances are intentionally
      separate).
- [ ] `registry.shutdown()` closes every open client and returns only
      after all `aclose()` coroutines complete (verified by ordering
      assertions on a fake client).
- [ ] `reset_mcp_registry()` builds a fresh registry instance;
      subsequent calls to `get_mcp_registry()` return the new one
      (used by tests).

### Tool injection

- [ ] An MCP server exposing two tools (`create_issue`, `list_issues`)
      under server key `"github"` results in agent wire tools named
      `github__create_issue` and `github__list_issues`.
- [ ] Tool descriptions and input schemas from the MCP SDK are copied
      verbatim into the `Tool` wire object.
- [ ] An agent's own `@Tool` method `create_issue` and an MCP tool
      `<key>__create_issue` coexist without collision (different
      namespaced names).
- [ ] An MCP tool whose namespaced name collides with an existing
      tool on the same agent (e.g. two `@MCP` classes accidentally
      generating the same `<key>__<name>`) is DROPPED at injection
      with a WARN; the first one registered wins. The boot does NOT
      abort.

### MCP tool dispatch

- [ ] An LLM tool_call for `github__create_issue` causes the agent
      runtime to call `registry.call_tool("github",
      "create_issue", args)`, get back a string result, and return a
      `tool_result` message with the result as `content`.
- [ ] An MCP tool that returns `isError=true` produces a `tool_result`
      with `is_error=True`. The error body matches the server's
      reported message.
- [ ] An MCP tool call that exceeds `timeout` (default 30s) raises an
      `MCPToolTimeoutError` which is converted to a `tool_result` with
      `is_error=True` and a clear message.
- [ ] Concurrent tool_calls from one LLM turn (one `@Tool` method and
      one MCP tool) execute concurrently via `asyncio.gather` (verified
      with timed fakes).

### Boot resilience

- [ ] A server whose `connect()` raises causes a WARN log and zero
      registered tools for that server; the factory still completes
      bootstrap and other servers in the same `@MCP` class continue
      normally.
- [ ] A server whose `list_tools()` raises after a successful
      `connect()` is closed and marked unhealthy; the factory continues.
- [ ] A `${VAR}` substitution missing at boot logs a WARN, marks the
      server unhealthy, and the factory completes.
- [ ] Boot succeeds even when every server in every `@MCP` class is
      unhealthy (the app comes up with no MCP tools).

### Observability

- [ ] Each MCP tool call produces a `mcp.call_tool {server_key}/{tool_name}`
      span that is a child of the agent runtime's
      `execute_tool {namespaced_name}` span. Attributes
      `mcp.server.key`, `mcp.tool.name`, `mcp.transport`,
      `mcp.duration_ms`, and `mcp.is_error` are populated.
- [ ] Boot discovery produces one `mcp.discover {server_key}` span
      per UNIQUE spec (not one per `@MCP` class referencing it).
- [ ] `mcp.call_tool` spans DO NOT contribute to
      `ajolopy.cost_usd.total` (cost roll-up ignores them).
- [ ] An unhealthy server's `mcp.discover` span carries
      `mcp.is_error=true` and an exception record.

### `MCPClient` escape hatch

- [ ] A user-defined `MCPClient` subclass passed as an entry of
      `servers=` is used verbatim (its `connect`, `list_tools`,
      `call_tool`, `aclose` are called by the registry).
- [ ] Custom-client tool calls produce `mcp.call_tool` spans with
      `mcp.transport="custom"`.
- [ ] A subclass that fails to implement an abstract method raises
      `TypeError` at instantiation (Python's normal ABC behaviour); no
      special framework error.

### Dependency surface

- [ ] `from ajolopy import MCP` works without the `mcp` extra
      installed.
- [ ] `@MCP(servers={...})` at decoration time works without the `mcp`
      extra.
- [ ] Calling `await registry.connect_all_for(module)` (or factory
      bootstrap) without the `mcp` extra raises `MCPDependencyError`
      with a message naming the extra.

### Public re-exports

- [ ] `from ajolopy import MCP` works.
- [ ] `from ajolopy.mcp import (MCPClient, MCPConfigError, MCPError,
      MCPDependencyError, MCPToolTimeoutError, MCPRegistry,
      get_mcp_registry, reset_mcp_registry, ToolSchema)` works.
- [ ] `MCP` is added to `src/ajolopy/__init__.py`'s `__all__` next to
      the other primitive names.

## Implementation pointers

- Source: `src/ajolopy/mcp/` (new package).
  - `__init__.py` — public re-exports.
  - `decorator.py` — the `MCP(...)` factory; validates config + stamps
    `_ajolopy_mcp` metadata + parses specs.
  - `spec.py` — `ServerSpec` parser (string → `(transport, parsed)`),
    `canonicalize_spec()` helper.
  - `client.py` — `MCPClient` ABC, `ToolSchema` dataclass, the three
    built-in client implementations (`StdioMCPClient`,
    `HTTPMCPClient`, `SSEMCPClient`) each wrapping the MCP SDK.
  - `registry.py` — `MCPRegistry`, the per-process singleton,
    `get_mcp_registry`, `reset_mcp_registry`, `connect_all_for(module)`
    discovery driver.
  - `errors.py` — `MCPError`, `MCPConfigError`, `MCPDependencyError`,
    `MCPToolTimeoutError`, `MCPRuntimeError`.
- Extend `src/ajolopy/observability/conventions.py`:
  - `mcp_call_tool_span_name(server_key, tool_name) -> str`
  - `mcp_discover_span_name(server_key) -> str`
  - New attr constants `MCP_SERVER_KEY`, `MCP_TOOL_NAME`,
    `MCP_TRANSPORT`, `MCP_DURATION_MS`, `MCP_IS_ERROR`.
- Cross-cut to `src/ajolopy/agent/`:
  - `decorator.py`: add `integrations: list[type] | None = None` kwarg.
    Forward to `AgentRuntime`.
  - `runtime.py`: accept `integrations` in `__init__`; resolve the
    set of `@MCP` classes (kwarg wins over class attribute, INFO log
    if both); add `_mcp_by_namespaced_name` lookup and a new branch in
    `_execute_single_tool` for namespaced names; widen
    `discover_tools` callers to merge MCP wire tools into `_wire_tools`
    after boot.
  - The agent's MCP tool wiring is finalised at boot, NOT at decoration
    time (the registry hasn't discovered yet). Provide a hook
    `AgentRuntime.wire_mcp_tools(registry)` that the factory calls
    after discovery completes.
- Cross-cut to `src/ajolopy/workflow/`:
  - `decorator.py`: drop the `integrations=` raise, accept it as real
    config, forward to `WorkflowRuntime`.
  - `runtime.py`: in the coordinator path, append MCP wire tools to
    the coordinator's tool list AND to each delegated agent's
    bootable runtime. In the `route()` override path, the agent's own
    wiring already covers the tools (no extra work).
- Cross-cut to `src/ajolopy/factory/`:
  - In `factory.py`'s bootstrap, between DI resolution and
    `on_app_bootstrap`, call
    `await get_mcp_registry().connect_all_for(module)`. Register
    `registry.shutdown` as an `on_app_shutdown` handler.
- pyproject.toml: add `[project.optional-dependencies] mcp = ["mcp>=1.0.0"]`.
- Tests: `tests/mcp/` (new) + extensions to `tests/agent/` and
  `tests/workflow/` for the `integrations=` wiring.
  - `tests/mcp/fakes.py` — `FakeMCPClient` implementing the ABC, used
    EVERYWHERE the real SDK would be imported.
  - `tests/mcp/test_decorator_validation.py`
  - `tests/mcp/test_spec_parser.py`
  - `tests/mcp/test_registry.py`
  - `tests/mcp/test_tool_injection.py`
  - `tests/mcp/test_boot_resilience.py`
  - `tests/mcp/test_observability.py`
  - `tests/mcp/test_public_api.py`
  - `tests/agent/test_integrations_kwarg.py` (extends AJ-1 surface)
  - `tests/workflow/test_integrations_kwarg.py` (flips AJ-6 raise)
- Runtime deps: none new in the core. `mcp>=1.0.0` lands behind the
  `ajolopy[mcp]` extra.

## Implementation notes

(Empty — populated by the implementation PR.)
