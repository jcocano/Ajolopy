"""Reusable fakes for the @MCP test suite.

The MCP SDK is an optional dependency; tests deliberately never import
``mcp.*`` so the suite runs identically with or without the extra
installed. :class:`FakeMCPClient` is the seam — every test that
exercises connect / list_tools / call_tool / aclose plugs one of these
in via :func:`patch_registry_builder` (which monkey-patches the
``build_builtin_client`` factory).
"""

import asyncio
from typing import Any, override

from ajolopy.mcp.client import MCPClient, ToolSchema


class FakeMCPClient(MCPClient):
    """In-memory :class:`MCPClient` for tests.

    Configurable surface:

    - ``tools`` — the list of :class:`ToolSchema` returned from
      :meth:`list_tools`.
    - ``call_results`` — keyed by tool name; each value is either a
      plain string (success) or an :class:`Exception` (raised verbatim).
      The default value when a key is absent is ``"ok"``.
    - ``call_delay`` — optional ``asyncio.sleep`` before each
      :meth:`call_tool` return; used by timeout / concurrency tests.
    - ``raise_on_connect`` / ``raise_on_list_tools`` — inject failures
      at boot.

    The class also records its lifecycle in ``connect_called`` /
    ``aclose_called`` so tests can assert ordering.
    """

    def __init__(
        self,
        canonical: str = "fake://default",
        *,
        tools: list[ToolSchema] | None = None,
        call_results: dict[str, str | Exception] | None = None,
        call_delay: float = 0.0,
        raise_on_connect: Exception | None = None,
        raise_on_list_tools: Exception | None = None,
    ) -> None:
        self._canonical = canonical
        self.tools = list(tools) if tools else []
        self.call_results = dict(call_results) if call_results else {}
        self.call_delay = call_delay
        self.raise_on_connect = raise_on_connect
        self.raise_on_list_tools = raise_on_list_tools
        self.connect_called = 0
        self.aclose_called = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    @override
    def canonical_spec(self) -> str:
        return self._canonical

    @override
    async def connect(self) -> None:
        self.connect_called += 1
        if self.raise_on_connect is not None:
            raise self.raise_on_connect

    @override
    async def list_tools(self) -> list[ToolSchema]:
        if self.raise_on_list_tools is not None:
            raise self.raise_on_list_tools
        return list(self.tools)

    @override
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, dict(arguments)))
        if self.call_delay:
            await asyncio.sleep(self.call_delay)
        result = self.call_results.get(name, "ok")
        if isinstance(result, Exception):
            raise result
        return result

    @override
    async def aclose(self) -> None:
        self.aclose_called += 1


__all__ = ["FakeMCPClient"]
