"""``MCPClient`` ABC + built-in stdio / HTTP / SSE clients.

The framework exposes a transport-agnostic ABC so users can plug a
custom MCP client without touching the registry. The three concrete
subclasses wrap the official ``mcp`` Python SDK; their imports happen
lazily so importing :mod:`ajolopy.mcp` works without the
``ajolopy[mcp]`` extra installed.

The SDK is contacted exactly once per :class:`MCPClient` lifetime:
:meth:`connect` opens a session, :meth:`list_tools` performs the
handshake, :meth:`call_tool` dispatches a single call, and
:meth:`aclose` releases every resource. ``MCPRegistry`` owns lifecycle
and pooling.
"""

import abc
import importlib
import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, cast, override

from .errors import MCPDependencyError, MCPRuntimeError
from .spec import (
    Transport,
    canonicalize_spec,
    normalise_url,
    stdio_command,
)

_LOGGER = logging.getLogger("ajolopy.mcp")

_DEPENDENCY_HINT = (
    "The optional `mcp` SDK is not installed. Install it with "
    "`pip install ajolopy[mcp]` (or `uv add 'ajolopy[mcp]'`) to use "
    "the @MCP decorator at runtime."
)


@dataclass(slots=True, frozen=True)
class ToolSchema:
    """Wire-shape rewrap of an MCP-discovered tool.

    Mirrors the relevant fields of :class:`mcp.types.Tool` while staying
    independent of the SDK: callers can build a :class:`ToolSchema`
    without importing ``mcp`` (handy in tests and for custom clients).
    """

    name: str
    description: str
    input_schema: dict[str, Any]


class MCPClient(abc.ABC):
    """Transport-agnostic client interface used by the registry.

    Subclass and pass an instance to ``@MCP(servers=[...])`` to plug a
    custom transport. The framework calls ``connect`` exactly once per
    instance, ``list_tools`` after a successful connect, ``call_tool``
    zero-or-more times per tool dispatch, and ``aclose`` once at app
    shutdown.
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open the underlying transport / spawn the child process."""

    @abc.abstractmethod
    async def list_tools(self) -> list[ToolSchema]:
        """Discover tools after :meth:`connect` succeeds."""

    @abc.abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a single tool call and return its text result.

        The framework converts the return into a ``tool_result`` message
        for the LLM. Implementations should raise to signal a transport
        failure; tool-level errors (``isError=true`` from the server)
        should be reported via a subclass-specific mechanism — see
        :meth:`_BaseSDKMCPClient.call_tool` for the built-in shape.
        """

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Release every resource (sockets, child processes, sessions)."""

    @property
    @abc.abstractmethod
    def canonical_spec(self) -> str:
        """Unique identifier the registry uses to dedupe connections.

        For instance-provided clients the framework does NOT consult
        this value when deduping — every instance hashes to its
        ``id()``. The property is still required so observability spans
        can name the underlying server consistently.
        """


# ---------------------------------------------------------------------------
# Shared SDK wrapper
# ---------------------------------------------------------------------------


def _load_mcp() -> Any:
    """Import the optional ``mcp`` SDK or raise :class:`MCPDependencyError`.

    Centralising the import here keeps every concrete client's connect
    path identical. The function returns the module so callers can
    pick the specific transport helper they need without paying for a
    second import. ``importlib.import_module`` is used instead of a
    bare ``import mcp`` so the optional dependency stays invisible to
    static analysers under both the full-extras CI footprint and the
    minimal-install dev footprint — neither needs a ``# pyright: ignore``
    or ``# type: ignore`` directive that would itself become a warning
    in one of the two configurations.
    """
    try:
        return importlib.import_module("mcp")
    except ImportError as exc:
        raise MCPDependencyError(_DEPENDENCY_HINT) from exc


class _BaseSDKMCPClient(MCPClient):
    """Shared scaffolding for the three SDK-backed transports.

    Concrete subclasses implement :meth:`_open_streams` which returns
    the ``(read, write)`` stream pair used to construct a
    :class:`mcp.client.session.ClientSession`. The base class handles
    session lifecycle, tool discovery, and call dispatch.
    """

    transport: Transport = "custom"

    def __init__(self, spec_str: str) -> None:
        self._spec_str = spec_str
        self._canonical = canonicalize_spec(spec_str)
        self._stack: AsyncExitStack | None = None
        # ``_session`` is an opaque ``mcp.ClientSession``. The MCP SDK
        # ships without type stubs so we hold it as :class:`Any` to keep
        # pyright strict happy without sprinkling per-call ignores.
        self._session: Any = None

    @property
    @override
    def canonical_spec(self) -> str:
        return self._canonical

    @abc.abstractmethod
    async def _open_streams(self, stack: AsyncExitStack) -> tuple[Any, Any]:
        """Open the underlying transport and return ``(read, write)``."""

    @override
    async def connect(self) -> None:
        if self._session is not None:
            return
        mcp_module: Any = _load_mcp()
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            read_stream, write_stream = await self._open_streams(stack)
            session_cls = mcp_module.ClientSession
            session: Any = await stack.enter_async_context(session_cls(read_stream, write_stream))
            await session.initialize()
        except BaseException:
            await stack.__aexit__(None, None, None)
            raise
        self._stack = stack
        self._session = session

    @override
    async def list_tools(self) -> list[ToolSchema]:
        if self._session is None:
            raise MCPRuntimeError(f"list_tools() called before connect() on {self._spec_str!r}.")
        result: Any = await self._session.list_tools()
        tools_attr: Any = getattr(result, "tools", None) or []
        out: list[ToolSchema] = []
        for tool in tools_attr:
            name_attr: Any = getattr(tool, "name", None)
            if not isinstance(name_attr, str) or not name_attr:
                continue
            description_attr: Any = getattr(tool, "description", None) or ""
            schema_attr: Any = getattr(tool, "inputSchema", None) or {}
            if isinstance(schema_attr, dict):
                typed_schema = cast("dict[Any, Any]", schema_attr)
                schema_dict: dict[str, Any] = {str(k): v for k, v in typed_schema.items()}
            else:
                schema_dict = {}
            out.append(
                ToolSchema(
                    name=name_attr,
                    description=str(description_attr),
                    input_schema=schema_dict,
                )
            )
        return out

    @override
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            raise MCPRuntimeError(f"call_tool({name!r}) before connect() on {self._spec_str!r}.")
        result: Any = await self._session.call_tool(name, arguments)
        text = _extract_text(result)
        if getattr(result, "isError", False):
            raise MCPRuntimeError(text or f"MCP tool {name!r} reported an error.")
        return text

    @override
    async def aclose(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is None:
            return
        try:
            await stack.__aexit__(None, None, None)
        except Exception as exc:
            # Best-effort: the registry calls aclose during app shutdown;
            # we never want a stuck transport to break the rest of the
            # shutdown sequence.
            _LOGGER.warning("MCP client aclose() raised: %s", exc)


def _extract_text(result: Any) -> str:
    """Concatenate the text content blocks of an MCP ``CallToolResult``.

    The SDK exposes a list of content blocks (text, image, resource).
    The v0.1 wedge consumes only text content; non-text blocks are
    ignored. Empty results return an empty string so the LLM sees a
    well-formed (if uninformative) ``tool_result``.
    """
    content: Any = getattr(result, "content", None) or []
    parts: list[str] = []
    for block in content:
        text_attr: Any = getattr(block, "text", None)
        if isinstance(text_attr, str):
            parts.append(text_attr)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Concrete transports
# ---------------------------------------------------------------------------


class StdioMCPClient(_BaseSDKMCPClient):
    """Spawn an MCP server as a child process over stdio."""

    transport: Transport = "stdio"

    def __init__(
        self,
        spec_str: str,
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(spec_str)
        self._env = dict(env) if env else {}

    @override
    async def _open_streams(self, stack: AsyncExitStack) -> tuple[Any, Any]:
        mcp_module: Any = _load_mcp()
        # Resolved here so missing extras blow up loudly the moment we
        # actually try to spawn.
        stdio_client = mcp_module.client.stdio.stdio_client
        params_cls = mcp_module.client.stdio.StdioServerParameters
        argv = stdio_command(self._spec_str)
        params = params_cls(
            command=argv[0],
            args=argv[1:],
            env={**os.environ, **self._env},
        )
        opened: Any = await stack.enter_async_context(stdio_client(params))
        return opened[0], opened[1]


class HTTPMCPClient(_BaseSDKMCPClient):
    """Stream-able HTTP transport for MCP servers exposed at a URL."""

    transport: Transport = "http"

    def __init__(
        self,
        spec_str: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(spec_str)
        self._headers = dict(headers) if headers else {}

    @override
    async def _open_streams(self, stack: AsyncExitStack) -> tuple[Any, Any]:
        mcp_module: Any = _load_mcp()
        client = mcp_module.client.streamable_http.streamablehttp_client
        url = normalise_url(self._spec_str)
        # streamable-http yields a 3-tuple (read, write, _session_id_callable)
        # — keep the first two and ignore the third.
        cm = client(url, headers=self._headers)
        opened: Any = await stack.enter_async_context(cm)
        opened_tuple = cast("tuple[Any, ...]", opened) if isinstance(opened, tuple) else None
        if opened_tuple is not None and len(opened_tuple) >= 2:
            return opened_tuple[0], opened_tuple[1]
        raise MCPRuntimeError(
            f"streamable_http client returned an unexpected tuple shape for {url!r}."
        )


class SSEMCPClient(_BaseSDKMCPClient):
    """SSE transport for MCP servers exposed at an ``sse://`` URL."""

    transport: Transport = "sse"

    def __init__(
        self,
        spec_str: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(spec_str)
        self._headers = dict(headers) if headers else {}

    @override
    async def _open_streams(self, stack: AsyncExitStack) -> tuple[Any, Any]:
        mcp_module: Any = _load_mcp()
        sse_client = mcp_module.client.sse.sse_client
        url = normalise_url(self._spec_str)
        cm = sse_client(url, headers=self._headers)
        opened: Any = await stack.enter_async_context(cm)
        opened_tuple = cast("tuple[Any, ...]", opened) if isinstance(opened, tuple) else None
        if opened_tuple is not None and len(opened_tuple) >= 2:
            return opened_tuple[0], opened_tuple[1]
        raise MCPRuntimeError(f"sse_client returned an unexpected tuple shape for {url!r}.")


# ---------------------------------------------------------------------------
# Factory used by the registry
# ---------------------------------------------------------------------------


def build_builtin_client(
    spec_str: str,
    *,
    transport: Transport,
    auth: dict[str, Any] | None,
) -> MCPClient:
    """Instantiate the built-in client for ``(spec_str, transport)``.

    Auth handling depends on the transport:

    - stdio: ``auth["env"]`` is the env override for the child process.
    - http / sse: ``auth["token"]`` is wrapped as ``Authorization: Bearer ...``;
      ``auth["headers"]`` is merged on top (overrides the token-derived
      header on collision).
    """
    auth = auth or {}
    if transport == "stdio":
        env_attr: Any = auth.get("env") or {}
        if isinstance(env_attr, dict):
            typed_env = cast("dict[Any, Any]", env_attr)
            env: dict[str, str] = {str(k): str(v) for k, v in typed_env.items()}
        else:
            env = {}
        return StdioMCPClient(spec_str, env=env)
    if transport == "http":
        headers = _materialise_url_headers(auth)
        return HTTPMCPClient(spec_str, headers=headers)
    if transport == "sse":
        headers = _materialise_url_headers(auth)
        return SSEMCPClient(spec_str, headers=headers)
    raise MCPRuntimeError(f"No built-in client for transport {transport!r}.")


def _materialise_url_headers(auth: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    token: Any = auth.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    extra: Any = auth.get("headers") or {}
    if isinstance(extra, dict):
        typed_extra = cast("dict[Any, Any]", extra)
        for key, value in typed_extra.items():
            headers[str(key)] = str(value)
    return headers


__all__ = [
    "HTTPMCPClient",
    "MCPClient",
    "SSEMCPClient",
    "StdioMCPClient",
    "ToolSchema",
    "build_builtin_client",
]
