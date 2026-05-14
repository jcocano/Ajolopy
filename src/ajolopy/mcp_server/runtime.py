"""``MCPServerRuntime`` -- single-instance dispatch + lowlevel server wiring.

Holds the metadata + ``@Tool`` bindings captured by the decorator, lazily
builds the optional ``mcp.server.lowlevel.Server`` on first boot, owns
the cached host-class instance (one per process / runtime), and exposes
``handle_list_tools`` / ``handle_call_tool`` coroutines that the
transport layers register as the SDK's request handlers.

Tool dispatch mirrors :class:`ajolopy.agent.runtime.AgentRuntime` for the
basics (async vs sync via ``asyncio.to_thread``, structured returns
JSON-encoded via :func:`stringify_tool_result`, exceptions mapped to
``CallToolResult(isError=True, ...)``) but stays a separate module
because the agent runtime drives a function-calling loop and this
runtime is a one-shot request/response surface.
"""

import asyncio
import inspect
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from ajolopy.observability import (
    get_tracer,
    mcp_server_boot_span_name,
    mcp_server_call_tool_span_name,
)
from ajolopy.observability.conventions import (
    AJOLOPY_MCP_SERVER_DURATION_MS,
    AJOLOPY_MCP_SERVER_IS_ERROR,
    AJOLOPY_MCP_SERVER_NAME,
    AJOLOPY_MCP_SERVER_TOOL_NAME,
    AJOLOPY_MCP_SERVER_TRANSPORT,
)

from .errors import MCPDependencyError, MCPServerConfigError, MCPServerRuntimeError

if TYPE_CHECKING:
    from ajolopy.agent.tool import ToolBinding

    from .metadata import MCPServerMetadata


_TRACER = get_tracer("ajolopy.mcp_server")
_LOGGER = logging.getLogger(__name__)


class MCPServerRuntime:
    """Stateful façade that backs every ``@MCPServer`` transport.

    Built once per ``(class, transport, path)`` triple at mount time
    (HTTP / SSE) or at CLI boot (stdio). The runtime owns:

    - the cached single instance (``Cls()`` for class targets, or the
      user-supplied instance from ``mount_mcp_servers([instance])``);
    - the lazily-built ``mcp.server.lowlevel.Server`` (built on first
      ``build_server`` call -- the import only happens then);
    - the dispatch lookup ``{tool_name: ToolBinding}``.
    """

    def __init__(
        self,
        metadata: MCPServerMetadata,
        *,
        instance: Any = None,
    ) -> None:
        self._metadata = metadata
        self._tool_by_name: dict[str, ToolBinding] = {b.metadata.name: b for b in metadata.bindings}
        self._instance: Any = instance
        # The lowlevel ``mcp.server.lowlevel.Server`` (or whatever the
        # ``server_factory`` returns) cached after the first call to
        # :meth:`build_server`. Held as :data:`Any` because the type
        # belongs to the optional ``mcp`` SDK.
        self._server: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def metadata(self) -> MCPServerMetadata:
        return self._metadata

    @property
    def instance(self) -> Any:
        """Return the bound host-class instance, creating it on first call."""
        if self._instance is None:
            self._instance = self._instantiate_host()
        return self._instance

    def emit_boot_span(self) -> None:
        """Emit the ``mcp_server.boot {name}`` span for visibility on slow init."""
        with _TRACER.start_as_current_span(mcp_server_boot_span_name(self._metadata.name)) as span:
            span.set_attribute(AJOLOPY_MCP_SERVER_NAME, self._metadata.name)
            span.set_attribute(AJOLOPY_MCP_SERVER_TRANSPORT, self._metadata.transport)

    def build_server(self) -> Any:
        """Return the lowlevel ``mcp.server.lowlevel.Server`` for this runtime.

        Cached after the first call. Imports the ``mcp`` SDK lazily so
        the module remains import-clean for users who only need the
        decorator. The optional ``server_factory=`` escape hatch
        replaces the default builder wholesale.
        """
        if self._server is not None:
            return self._server

        if self._metadata.server_factory is not None:
            try:
                server = self._metadata.server_factory(
                    self._metadata,
                    list(self._metadata.bindings),
                )
            except Exception as exc:
                raise MCPServerRuntimeError(
                    f"server_factory for {self._metadata.name!r} raised: {exc}"
                ) from exc
            self._server = server
            return server

        # Lazy import: a user that ``from ajolopy.mcp_server import MCPServer`` and
        # never boots a server must not be forced to install the SDK.
        try:
            from mcp.server.lowlevel import Server
        except ImportError as exc:
            raise MCPDependencyError(
                "The 'mcp' SDK is required to run an @MCPServer. Install it "
                "with 'pip install ajolopy[mcp]'."
            ) from exc

        server = Server(
            name=self._metadata.name,
            version=self._metadata.version,
            instructions=self._metadata.instructions,
        )

        # Register the framework's list_tools / call_tool handlers via the
        # SDK's decorator surface. ``server.list_tools()`` and
        # ``server.call_tool()`` both return decorators; we feed them our
        # coroutine helpers and discard the returned function.
        server.list_tools()(self._build_list_tools_handler())
        server.call_tool()(self._build_call_tool_handler())

        self._server = server
        return server

    # ------------------------------------------------------------------
    # Handler factories
    # ------------------------------------------------------------------

    def _build_list_tools_handler(self) -> Any:
        """Return the ``async list_tools()`` coroutine for the SDK."""
        # Import ``types`` lazily inside this scope; the SDK is guaranteed
        # to be on the path by the time :meth:`build_server` is called.
        from mcp import types

        bindings = self._metadata.bindings

        async def list_tools() -> list[types.Tool]:
            return [_binding_to_mcp_tool(b, types_module=types) for b in bindings]

        return list_tools

    def _build_call_tool_handler(self) -> Any:
        """Return the ``async call_tool(name, arguments)`` coroutine for the SDK."""
        # The ``types`` module is used both as a runtime constructor (via
        # the dispatch path that builds ``CallToolResult``) and as the
        # return-type annotation below. ``noqa`` on the import keeps
        # ruff from flagging this as a TYPE_CHECKING-only candidate.
        from mcp import types  # noqa: TC001

        runtime = self

        async def call_tool(
            name: str,
            arguments: dict[str, Any],
        ) -> types.CallToolResult:
            return await runtime.dispatch_tool(name, arguments)

        return call_tool

    # ------------------------------------------------------------------
    # Dispatch (also the public seam for tests + the future @Resource glue)
    # ------------------------------------------------------------------

    async def dispatch_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke the bound ``@Tool`` and return a ``CallToolResult``.

        Exposed as a coroutine so tests can drive dispatch without
        speaking JSON-RPC. The return value is the SDK's
        ``types.CallToolResult`` -- we always speak the structured shape
        so the ``isError`` flag round-trips cleanly. Unknown tool name,
        argument validation errors, and unexpected exceptions all
        normalise to ``CallToolResult(isError=True, content=[...])``.
        """
        from mcp import types

        with _TRACER.start_as_current_span(
            mcp_server_call_tool_span_name(self._metadata.name, name)
        ) as span:
            span.set_attribute(AJOLOPY_MCP_SERVER_NAME, self._metadata.name)
            span.set_attribute(AJOLOPY_MCP_SERVER_TRANSPORT, self._metadata.transport)
            span.set_attribute(AJOLOPY_MCP_SERVER_TOOL_NAME, name)
            started = time.perf_counter()

            binding = self._tool_by_name.get(name)
            if binding is None:
                duration_ms = (time.perf_counter() - started) * 1000.0
                span.set_attribute(AJOLOPY_MCP_SERVER_DURATION_MS, duration_ms)
                span.set_attribute(AJOLOPY_MCP_SERVER_IS_ERROR, True)
                return _error_result(types, f"Unknown tool {name!r}.")

            try:
                kwargs = binding.metadata.validate_arguments(arguments or {})
            except ValidationError as exc:
                duration_ms = (time.perf_counter() - started) * 1000.0
                span.set_attribute(AJOLOPY_MCP_SERVER_DURATION_MS, duration_ms)
                span.set_attribute(AJOLOPY_MCP_SERVER_IS_ERROR, True)
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, "invalid arguments"))
                return _error_result(types, f"Invalid arguments for {name!r}: {exc}")

            owner = self.instance
            try:
                if binding.metadata.is_async:
                    result = await binding.metadata.fn(owner, **kwargs)
                else:
                    result = await asyncio.to_thread(binding.metadata.fn, owner, **kwargs)
            except Exception as exc:
                duration_ms = (time.perf_counter() - started) * 1000.0
                span.set_attribute(AJOLOPY_MCP_SERVER_DURATION_MS, duration_ms)
                span.set_attribute(AJOLOPY_MCP_SERVER_IS_ERROR, True)
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                _LOGGER.error(
                    "Tool %r on @MCPServer %r raised: %s",
                    name,
                    self._metadata.name,
                    exc,
                )
                return _error_result(types, f"{type(exc).__name__}: {exc}")

            duration_ms = (time.perf_counter() - started) * 1000.0
            span.set_attribute(AJOLOPY_MCP_SERVER_DURATION_MS, duration_ms)
            span.set_attribute(AJOLOPY_MCP_SERVER_IS_ERROR, False)
            text = stringify_tool_result(result)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
                isError=False,
            )

    # ------------------------------------------------------------------
    # Instance management
    # ------------------------------------------------------------------

    def _instantiate_host(self) -> Any:
        cls = self._metadata.original_cls
        try:
            sig = inspect.signature(cls)
        except (TypeError, ValueError) as exc:
            raise MCPServerConfigError(
                f"Could not introspect {cls.__qualname__}: {exc}. Pass a "
                f"pre-built instance to mount_mcp_servers / "
                f"create_app(mcp_servers=[{cls.__name__}(...)])."
            ) from exc
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.default is inspect.Parameter.empty and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise MCPServerConfigError(
                    f"@MCPServer host class {cls.__qualname__} requires "
                    f"constructor argument {name!r}. Pass a pre-built "
                    f"instance: create_app(mcp_servers=[{cls.__name__}(...)])."
                )
        try:
            return cls()
        except Exception as exc:
            raise MCPServerRuntimeError(
                f"Failed to instantiate {cls.__qualname__}(): {exc}. Pass a "
                f"pre-built instance to mount_mcp_servers."
            ) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _binding_to_mcp_tool(binding: ToolBinding, *, types_module: Any) -> Any:
    """Convert a ``ToolBinding`` to the SDK's ``types.Tool`` object."""
    md = binding.metadata
    schema = md.json_schema()
    return types_module.Tool(
        name=md.name,
        description=md.description or None,
        inputSchema=schema,
    )


def _error_result(types_module: Any, message: str) -> Any:
    """Build a ``CallToolResult(isError=True)`` carrying a single text block."""
    return types_module.CallToolResult(
        content=[types_module.TextContent(type="text", text=message)],
        isError=True,
    )


def stringify_tool_result(value: Any) -> str:
    """Coerce a tool return value to a string suitable for ``TextContent``.

    Mirrors :func:`ajolopy.agent.runtime._stringify_tool_result` -- string
    returns pass through; dicts / lists / ``BaseModel`` instances /
    everything else round-trip through ``json.dumps`` with a permissive
    ``default=str`` so the LLM-facing payload is always serialisable.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except TypeError, ValueError:
        return str(value)


__all__ = [
    "MCPServerRuntime",
    "stringify_tool_result",
]
