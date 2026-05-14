"""``MCPRegistry`` — per-process connection pool and tool registry.

The registry is the heart of the @MCP runtime:

- Decoration time stamps each ``@MCP`` class with a list of
  ``ServerEntry`` declarations. The decorator never spawns processes
  or opens sockets — that work waits for the registry.
- At factory boot the registry walks every collected ``@MCP`` class,
  deduplicates server specs by their canonical-key, opens exactly one
  client per unique spec in parallel, calls ``list_tools()``, and
  stores the resulting :class:`ToolSchema` list keyed by
  ``(mcp_cls, server_key)``.
- Boot-time failures (connect raise, list_tools raise, missing env var
  for ``${VAR}`` substitution) become WARN logs and mark the
  ``(mcp_cls, server_key)`` pair as unhealthy; the affected agents
  boot with reduced tool sets. The factory never aborts because of an
  MCP failure.
- Shutdown closes every client (stdio child processes included). Order
  is irrelevant — every client owns its own resources.

The registry is a process-wide singleton accessed via
:func:`get_mcp_registry`; :func:`reset_mcp_registry` builds a fresh
instance for tests.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.trace import Status, StatusCode

from ajolopy.observability import (
    MCP_DURATION_MS,
    MCP_IS_ERROR,
    MCP_SERVER_KEY,
    MCP_TOOL_NAME,
    MCP_TRANSPORT,
    get_tracer,
    mcp_call_tool_span_name,
    mcp_discover_span_name,
)

from .client import MCPClient, ToolSchema, build_builtin_client
from .errors import MCPRuntimeError, MCPToolTimeoutError
from .spec import Transport, canonicalize_spec, substitute_env

_LOGGER = logging.getLogger("ajolopy.mcp")
_TRACER = get_tracer("ajolopy.mcp")

# Internal handshake timeout for the boot-time connect + list_tools roundtrip.
# Independent of the user-facing ``timeout=`` kwarg (which gates tool calls).
_BOOT_HANDSHAKE_TIMEOUT_S = 10.0


@dataclass(slots=True)
class ServerEntry:
    """Decoration-time record of a single server in a ``@MCP`` class.

    ``spec`` is either the raw string (e.g. ``"stdio:npx ..."``) or an
    :class:`MCPClient` instance for the escape-hatch path. ``auth`` is
    the per-server auth dict (already validated against the transport's
    expected keys; ``${VAR}`` references syntactically checked).
    ``transport`` is ``"custom"`` for instance entries and the parsed
    family for string specs.
    """

    key: str
    spec: str | MCPClient
    transport: Transport
    auth: dict[str, Any] | None


@dataclass(slots=True)
class _PooledClient:
    """A live client + the canonical spec it was opened against."""

    client: MCPClient
    canonical: str
    transport: Transport
    tools: list[ToolSchema] = field(default_factory=list[ToolSchema])
    healthy: bool = True


@dataclass(slots=True)
class _RegistryState:
    """Mutable state of one :class:`MCPRegistry` instance.

    Held on a single instance so static analysers see the cross-method
    read/write pattern explicitly. Mirrors the convention used by
    :mod:`ajolopy.observability.logging`.
    """

    # Pool of clients keyed by canonical spec string. Instance-provided
    # clients are NOT pooled — they live in ``instance_clients`` keyed by
    # their ``id()``.
    pool: dict[str, _PooledClient] = field(default_factory=dict[str, _PooledClient])
    # Instance entries: one entry per unique ``MCPClient`` instance.
    instance_clients: dict[int, _PooledClient] = field(default_factory=dict[int, _PooledClient])
    # ``(mcp_cls, server_key) -> [namespaced_tool_name, ...]``. The
    # AgentRuntime / WorkflowRuntime consult this map to materialise
    # their wire tool lists once boot completes.
    tools_by_mcp: dict[type, dict[str, list[ToolSchema]]] = field(
        default_factory=dict[type, dict[str, list[ToolSchema]]]
    )
    # ``namespaced_name -> (canonical_or_id, raw_tool_name, transport, timeout)``
    # — populated only for tools actually injected into an agent via
    # ``MCPRegistry.tools_for``. The dispatch path looks here when an
    # LLM tool call carries a namespaced name.
    dispatch_table: dict[str, _DispatchEntry] = field(default_factory=dict[str, "_DispatchEntry"])


@dataclass(slots=True, frozen=True)
class _DispatchEntry:
    """Routing data for one namespaced tool call."""

    pool_key: str  # canonical spec OR str(id(instance)) for instance entries
    server_key: str
    raw_name: str
    transport: Transport
    timeout: float


class MCPRegistry:
    """Per-process pool of MCP clients + discovered tools.

    Public methods:

    - :meth:`register_class` — called by ``@MCP`` at decoration time to
      stamp the registry with the class's server list (the actual
      connect happens at boot).
    - :meth:`connect_all_for` — async; called once during factory
      bootstrap. Walks every collected ``@MCP`` class, dedupes specs,
      opens unique clients in parallel, and discovers tools.
    - :meth:`tools_for` — synchronous; queries the wire tool list for
      one ``@MCP`` class. AgentRuntime calls this after boot to
      compose its wire tool list.
    - :meth:`call_tool` — async; dispatches one namespaced tool call.
      The agent runtime's ``_execute_single_tool`` routes here when the
      tool name matches a namespaced entry.
    - :meth:`shutdown` — async; closes every client. Called from the
      factory's ``on_app_shutdown`` handler.
    """

    def __init__(self) -> None:
        self._state = _RegistryState()
        # Classes registered via @MCP. The decorator pushes a
        # (mcp_cls, [ServerEntry, ...], timeout) tuple per class so the
        # registry can iterate at boot.
        self._classes: dict[type, _ClassRecord] = {}

    # ------------------------------------------------------------------
    # decoration-time hooks
    # ------------------------------------------------------------------

    def register_class(
        self,
        cls: type,
        *,
        entries: list[ServerEntry],
        timeout: float,
    ) -> None:
        """Stamp the registry with a newly-decorated ``@MCP`` class."""
        self._classes[cls] = _ClassRecord(cls=cls, entries=entries, timeout=timeout)

    def registered_classes(self) -> list[type]:
        """List the classes decorated with ``@MCP`` (test introspection)."""
        return list(self._classes.keys())

    # ------------------------------------------------------------------
    # boot-time discovery
    # ------------------------------------------------------------------

    async def connect_all_for(self, module: object) -> None:
        """Discover MCP integrations referenced by ``module`` and connect.

        ``module`` is the application's root module class as passed to
        :class:`~ajolopy.factory.AjolopyFactory`. The registry walks every
        ``@Agent`` and ``@Workflow`` under it, collects every ``@MCP``
        class referenced via ``integrations=`` (kwarg OR class
        attribute), and opens one client per unique canonical spec.

        Connection / handshake failures are caught, WARN-logged, and the
        affected ``(class, server_key)`` pair is marked unhealthy. The
        factory never aborts because of an MCP failure.
        """
        mcp_classes = _collect_integrations(module, registered=self._classes.keys())
        # Gather every unique (canonical_key, ServerEntry, timeout)
        # across the participating classes. The timeout is per-class but
        # the canonical key dedupes across classes — pick the smallest
        # timeout if two classes disagree (safer default for boot).
        unique_specs: dict[str, _PoolPlan] = {}
        instance_entries: list[_InstancePlan] = []
        for cls in mcp_classes:
            record = self._classes[cls]
            for entry in record.entries:
                if isinstance(entry.spec, MCPClient):
                    instance_entries.append(
                        _InstancePlan(
                            cls=cls,
                            entry=entry,
                            timeout=record.timeout,
                        )
                    )
                    continue
                resolved_auth, missing = _resolve_auth(entry.auth)
                if missing:
                    _LOGGER.warning(
                        "MCP server %r (%s) is missing env vars %s — marking unhealthy.",
                        entry.key,
                        entry.spec,
                        sorted(set(missing)),
                    )
                    # Drop into tools_by_mcp with an empty list so the
                    # agent runtime sees the server but gets zero tools.
                    self._state.tools_by_mcp.setdefault(cls, {})[entry.key] = []
                    continue
                canonical = canonicalize_spec(entry.spec)
                plan = unique_specs.get(canonical)
                if plan is None:
                    unique_specs[canonical] = _PoolPlan(
                        canonical=canonical,
                        spec=entry.spec,
                        transport=entry.transport,
                        auth=resolved_auth,
                        timeout=record.timeout,
                        consumers=[(cls, entry.key)],
                    )
                else:
                    plan.consumers.append((cls, entry.key))
                    plan.timeout = min(plan.timeout, record.timeout)

        # Open each unique canonical spec in parallel.
        connect_tasks = [self._open_pool_entry(plan) for plan in unique_specs.values()]
        instance_tasks = [self._open_instance_entry(plan) for plan in instance_entries]
        await asyncio.gather(*connect_tasks, *instance_tasks, return_exceptions=True)

    async def _open_pool_entry(self, plan: _PoolPlan) -> None:
        with _TRACER.start_as_current_span(mcp_discover_span_name(plan.consumers[0][1])) as span:
            span.set_attribute(MCP_TRANSPORT, plan.transport)
            try:
                client = build_builtin_client(
                    plan.spec,
                    transport=plan.transport,
                    auth=plan.auth,
                )
                await asyncio.wait_for(client.connect(), timeout=_BOOT_HANDSHAKE_TIMEOUT_S)
                tools = await asyncio.wait_for(
                    client.list_tools(),
                    timeout=_BOOT_HANDSHAKE_TIMEOUT_S,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "MCP connect failed for %s: %s — server marked unhealthy.",
                    plan.spec,
                    exc,
                )
                span.record_exception(exc)
                span.set_attribute(MCP_IS_ERROR, True)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                for cls, server_key in plan.consumers:
                    self._state.tools_by_mcp.setdefault(cls, {})[server_key] = []
                return
            pooled = _PooledClient(
                client=client,
                canonical=plan.canonical,
                transport=plan.transport,
                tools=tools,
            )
            self._state.pool[plan.canonical] = pooled
            for cls, server_key in plan.consumers:
                self._state.tools_by_mcp.setdefault(cls, {})[server_key] = tools

    async def _open_instance_entry(self, plan: _InstancePlan) -> None:
        spec = plan.entry.spec
        if not isinstance(spec, MCPClient):  # pragma: no cover - typed at call site
            return
        with _TRACER.start_as_current_span(mcp_discover_span_name(plan.entry.key)) as span:
            span.set_attribute(MCP_TRANSPORT, "custom")
            try:
                await asyncio.wait_for(spec.connect(), timeout=_BOOT_HANDSHAKE_TIMEOUT_S)
                tools = await asyncio.wait_for(
                    spec.list_tools(),
                    timeout=_BOOT_HANDSHAKE_TIMEOUT_S,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "MCP instance client for %r failed at boot: %s — server marked unhealthy.",
                    plan.entry.key,
                    exc,
                )
                span.record_exception(exc)
                span.set_attribute(MCP_IS_ERROR, True)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._state.tools_by_mcp.setdefault(plan.cls, {})[plan.entry.key] = []
                return
            pooled = _PooledClient(
                client=spec,
                canonical=spec.canonical_spec,
                transport="custom",
                tools=tools,
            )
            self._state.instance_clients[id(spec)] = pooled
            self._state.tools_by_mcp.setdefault(plan.cls, {})[plan.entry.key] = tools

    # ------------------------------------------------------------------
    # boot-time tool injection (called by AgentRuntime / WorkflowRuntime)
    # ------------------------------------------------------------------

    def tools_for(self, mcp_cls: type) -> list[tuple[str, ToolSchema]]:
        """Return ``(namespaced_name, schema)`` pairs for one ``@MCP`` class.

        Collisions inside a single ``@MCP`` class produce a WARN log and
        the second-discovered tool is dropped. The caller (the runtime
        wiring path) is responsible for the agent-side collision with
        local ``@Tool`` methods.
        """
        per_server = self._state.tools_by_mcp.get(mcp_cls, {})
        out: list[tuple[str, ToolSchema]] = []
        seen: set[str] = set()
        for server_key, tools in per_server.items():
            for tool in tools:
                namespaced = f"{server_key}__{tool.name}"
                if namespaced in seen:
                    _LOGGER.warning(
                        "MCP tool name collision %r on @%s — dropping the duplicate.",
                        namespaced,
                        mcp_cls.__name__,
                    )
                    continue
                seen.add(namespaced)
                out.append((namespaced, tool))
        return out

    def register_dispatch(
        self,
        mcp_cls: type,
        *,
        namespaced_name: str,
        server_key: str,
        raw_name: str,
    ) -> None:
        """Record the dispatch route for one injected namespaced tool.

        Called by the agent / workflow runtime once it finalises the
        wire tool list. The mapping is shared across consumers because
        the canonical pool is shared — two agents that route through
        ``github__create_issue`` both end up at the same pooled client.
        """
        record = self._classes.get(mcp_cls)
        timeout = record.timeout if record is not None else 30.0
        # Look up the pool key. Instance entries hash by id(instance);
        # built-in entries by canonical spec.
        if record is None:
            return
        for entry in record.entries:
            if entry.key != server_key:
                continue
            if isinstance(entry.spec, MCPClient):
                pool_key = f"instance:{id(entry.spec)}"
                transport: Transport = "custom"
            else:
                pool_key = canonicalize_spec(entry.spec)
                transport = entry.transport
            self._state.dispatch_table[namespaced_name] = _DispatchEntry(
                pool_key=pool_key,
                server_key=server_key,
                raw_name=raw_name,
                transport=transport,
                timeout=timeout,
            )
            return

    def has_dispatch(self, namespaced_name: str) -> bool:
        return namespaced_name in self._state.dispatch_table

    # ------------------------------------------------------------------
    # tool dispatch
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        namespaced_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Dispatch a namespaced MCP tool call and return the result text.

        Emits an ``mcp.call_tool`` span carrying the per-call attrs.
        Raises :class:`MCPToolTimeoutError` on timeout and
        :class:`MCPRuntimeError` on every other failure (transport
        error, ``isError=true`` from the server). The agent runtime
        translates both into ``tool_result`` messages with
        ``is_error=True`` so the LLM can recover.
        """
        entry = self._state.dispatch_table.get(namespaced_name)
        if entry is None:
            raise MCPRuntimeError(
                f"No MCP dispatch registered for {namespaced_name!r}. "
                f"Did factory bootstrap run before this tool dispatch?"
            )
        client = self._resolve_client(entry.pool_key)
        if client is None:
            raise MCPRuntimeError(
                f"No live client for {namespaced_name!r}; server may be unhealthy."
            )

        with _TRACER.start_as_current_span(
            mcp_call_tool_span_name(entry.server_key, entry.raw_name),
        ) as span:
            span.set_attribute(MCP_SERVER_KEY, entry.server_key)
            span.set_attribute(MCP_TOOL_NAME, entry.raw_name)
            span.set_attribute(MCP_TRANSPORT, entry.transport)
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    client.call_tool(entry.raw_name, arguments),
                    timeout=entry.timeout,
                )
            except TimeoutError as exc:
                duration_ms = (time.perf_counter() - started) * 1000.0
                span.set_attribute(MCP_DURATION_MS, duration_ms)
                span.set_attribute(MCP_IS_ERROR, True)
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "timeout"))
                raise MCPToolTimeoutError(
                    f"MCP tool {namespaced_name!r} timed out after {entry.timeout}s."
                ) from exc
            except Exception as exc:
                duration_ms = (time.perf_counter() - started) * 1000.0
                span.set_attribute(MCP_DURATION_MS, duration_ms)
                span.set_attribute(MCP_IS_ERROR, True)
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                if isinstance(exc, MCPRuntimeError):
                    raise
                raise MCPRuntimeError(
                    f"MCP tool {namespaced_name!r} raised {type(exc).__name__}: {exc}"
                ) from exc
            duration_ms = (time.perf_counter() - started) * 1000.0
            span.set_attribute(MCP_DURATION_MS, duration_ms)
            span.set_attribute(MCP_IS_ERROR, False)
            return result

    def _resolve_client(self, pool_key: str) -> MCPClient | None:
        if pool_key.startswith("instance:"):
            try:
                ident = int(pool_key.split(":", 1)[1])
            except ValueError:
                return None
            entry = self._state.instance_clients.get(ident)
            return entry.client if entry is not None else None
        entry = self._state.pool.get(pool_key)
        return entry.client if entry is not None else None

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Close every live client. Idempotent."""
        clients: list[MCPClient] = []
        clients.extend(entry.client for entry in self._state.pool.values())
        clients.extend(entry.client for entry in self._state.instance_clients.values())
        self._state.pool.clear()
        self._state.instance_clients.clear()
        await asyncio.gather(
            *(client.aclose() for client in clients),
            return_exceptions=True,
        )

    # Useful for tests — read-only view of what got discovered.
    def discovered_tools(self) -> dict[str, list[ToolSchema]]:
        merged: dict[str, list[ToolSchema]] = {}
        for per_server in self._state.tools_by_mcp.values():
            for server_key, tools in per_server.items():
                merged.setdefault(server_key, []).extend(tools)
        return merged


# ---------------------------------------------------------------------------
# Boot-time planning helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ClassRecord:
    """Decoration-time record of a ``@MCP``-decorated class."""

    cls: type
    entries: list[ServerEntry]
    timeout: float


@dataclass(slots=True)
class _PoolPlan:
    """One unique canonical spec the registry will open at boot."""

    canonical: str
    spec: str
    transport: Transport
    auth: dict[str, Any] | None
    timeout: float
    consumers: list[tuple[type, str]]


@dataclass(slots=True)
class _InstancePlan:
    """One :class:`MCPClient` instance to open at boot."""

    cls: type
    entry: ServerEntry
    timeout: float


def _resolve_auth(auth: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Substitute ``${VAR}`` in ``auth`` against ``os.environ``.

    Returns ``(resolved, missing)``: ``missing`` is the list of env
    variable names that were referenced but absent. The caller treats a
    non-empty ``missing`` list as "mark server unhealthy" and does NOT
    raise.
    """
    if auth is None:
        return None, []
    missing: list[str] = []
    resolved = substitute_env(auth, dict(os.environ), source="auth", missing=missing)
    return resolved, missing


def _collect_integrations(
    module: object,
    *,
    registered: Any,
) -> list[type]:
    """Walk the module graph and return every referenced ``@MCP`` class.

    Recognises ``integrations=`` on the AgentRuntime and on the
    WorkflowRuntime; the kwarg wins over the class attribute (the
    runtimes have already applied that precedence and stored the
    effective list in their own state). The result preserves first-seen
    order so multiple consumers of the same class are deduped.
    """
    registered_set = set(registered)
    seen: list[type] = []
    seen_set: set[type] = set()

    def consider(cls_obj: object) -> None:
        if not isinstance(cls_obj, type):
            return
        if cls_obj in seen_set or cls_obj not in registered_set:
            return
        seen.append(cls_obj)
        seen_set.add(cls_obj)

    def visit_runtime_attr(runtime: object) -> None:
        # AgentRuntime and WorkflowRuntime both store the resolved list
        # under ``_integrations`` once we add the kwarg below.
        for integration in getattr(runtime, "_integrations", []) or []:
            consider(integration)

    # The module graph is composed via the AJ-8 ``@Module`` decorator
    # which exposes a ``_ajolopy_module`` attribute carrying the lists
    # of agents / workflows / etc. Walk it lazily so we do not import
    # the modules package at the top of this file.
    visited: set[type] = set()

    def walk(node: object) -> None:
        if not isinstance(node, type) or node in visited:
            return
        visited.add(node)
        meta = getattr(node, "_ajolopy_module", None)
        if meta is None:
            return
        for cls_obj in getattr(meta, "agents", []) or []:
            runtime = getattr(cls_obj, "_agent_runtime", None)
            if runtime is not None:
                visit_runtime_attr(runtime)
        for cls_obj in getattr(meta, "workflows", []) or []:
            runtime = getattr(cls_obj, "_workflow_runtime", None)
            if runtime is not None:
                visit_runtime_attr(runtime)
        for cls_obj in getattr(meta, "controllers", []) or []:
            runtime = getattr(cls_obj, "_agent_runtime", None)
            if runtime is not None:
                visit_runtime_attr(runtime)
            runtime = getattr(cls_obj, "_workflow_runtime", None)
            if runtime is not None:
                visit_runtime_attr(runtime)
        for imported in getattr(meta, "imports", []) or []:
            target = getattr(imported, "resolve", None)
            if callable(target):
                walk(target())
            else:
                walk(imported)

    walk(module)
    # Fallback: if the module graph is empty (no @Module yet) or did not
    # surface any @MCP classes, still register every class for which a
    # ``register_class`` call ran. Callers that drive the registry
    # directly (tests, standalone scripts) rely on this.
    for cls_obj in registered_set:
        consider(cls_obj)
    return seen


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Singleton:
    instance: MCPRegistry | None = None


_singleton = _Singleton()


def get_mcp_registry() -> MCPRegistry:
    """Return the process-wide :class:`MCPRegistry`, building it on demand."""
    if _singleton.instance is None:
        _singleton.instance = MCPRegistry()
    return _singleton.instance


def reset_mcp_registry() -> MCPRegistry:
    """Replace the process-wide registry with a fresh instance.

    Returns the new instance for convenience. Test fixtures call this
    between cases so MCP state never leaks across boundaries.
    """
    _singleton.instance = MCPRegistry()
    return _singleton.instance


__all__ = [
    "MCPRegistry",
    "ServerEntry",
    "get_mcp_registry",
    "reset_mcp_registry",
]
