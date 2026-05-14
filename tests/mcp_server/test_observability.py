"""Observability spans emitted by ``@MCPServer`` boot + dispatch.

Reuses the AJ-28 ``InMemorySpanExporter`` session helper so the
TracerProvider is shared with the rest of the suite. The OTel API
treats ``set_tracer_provider`` as set-once -- if our test installed a
second provider after the observability conftest ran, our exporter
would never see the spans.
"""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy import MCPServer, Tool
from ajolopy.mcp_server import MCPServerRuntime
from ajolopy.mcp_server.decorator import MCP_SERVER_META_ATTR

# Module-level singleton exporter, attached to the active provider.
_EXPORTER = InMemorySpanExporter()
_INSTALLED = {"value": False}


def _attach_exporter() -> InMemorySpanExporter:
    """Attach our exporter to whatever ``TracerProvider`` is active.

    The OTel SDK lets us add additional span processors at any time;
    this means we ride along with the observability conftest's
    provider when both suites collect, and we spin up a fresh one
    when the mcp_server tests run in isolation.
    """
    if _INSTALLED["value"]:
        return _EXPORTER
    current = trace.get_tracer_provider()
    if not isinstance(current, TracerProvider):
        current = TracerProvider()
        trace.set_tracer_provider(current)
    current.add_span_processor(SimpleSpanProcessor(_EXPORTER))
    _INSTALLED["value"] = True
    return _EXPORTER


_attach_exporter()


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    _EXPORTER.clear()
    try:
        yield _EXPORTER
    finally:
        _EXPORTER.clear()


@MCPServer(transport="stdio", name="obs-server")
class _ObservedTools:
    @Tool
    def echo(self, value: str) -> str:
        return value

    @Tool
    def boom(self) -> str:
        raise RuntimeError("boom")


def _runtime() -> MCPServerRuntime:
    meta = getattr(_ObservedTools, MCP_SERVER_META_ATTR)
    return MCPServerRuntime(meta)


def _spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    return list(exporter.get_finished_spans())


class TestBootSpan:
    def test_emit_boot_span_records_name_and_transport(
        self,
        exporter: InMemorySpanExporter,
    ) -> None:
        runtime = _runtime()
        runtime.emit_boot_span()
        spans = _spans(exporter)
        boot = [s for s in spans if s.name == "mcp_server.boot obs-server"]
        assert len(boot) == 1
        attrs = dict(boot[0].attributes or {})
        assert attrs["ajolopy.mcp_server.name"] == "obs-server"
        assert attrs["ajolopy.mcp_server.transport"] == "stdio"


class TestCallToolSpan:
    async def test_success_dispatch_span(self, exporter: InMemorySpanExporter) -> None:
        runtime = _runtime()
        await runtime.dispatch_tool("echo", {"value": "hi"})
        spans = _spans(exporter)
        call = [s for s in spans if s.name == "mcp_server.call_tool obs-server/echo"]
        assert len(call) == 1
        attrs = dict(call[0].attributes or {})
        assert attrs["ajolopy.mcp_server.name"] == "obs-server"
        assert attrs["ajolopy.mcp_server.transport"] == "stdio"
        assert attrs["ajolopy.mcp_server.tool.name"] == "echo"
        assert attrs["ajolopy.mcp_server.is_error"] is False
        assert isinstance(attrs["ajolopy.mcp_server.duration_ms"], float)

    async def test_failure_dispatch_marks_error(
        self,
        exporter: InMemorySpanExporter,
    ) -> None:
        runtime = _runtime()
        await runtime.dispatch_tool("boom", {})
        spans = _spans(exporter)
        call = [s for s in spans if s.name == "mcp_server.call_tool obs-server/boom"]
        assert len(call) == 1
        attrs = dict(call[0].attributes or {})
        assert attrs["ajolopy.mcp_server.is_error"] is True

    async def test_unknown_tool_marks_error(self, exporter: InMemorySpanExporter) -> None:
        runtime = _runtime()
        await runtime.dispatch_tool("does_not_exist", {})
        spans = _spans(exporter)
        call = [s for s in spans if s.name.startswith("mcp_server.call_tool")]
        assert len(call) == 1
        attrs = dict(call[0].attributes or {})
        assert attrs["ajolopy.mcp_server.is_error"] is True

    async def test_spans_do_not_emit_cost_total(self, exporter: InMemorySpanExporter) -> None:
        runtime = _runtime()
        runtime.emit_boot_span()
        await runtime.dispatch_tool("echo", {"value": "x"})
        for span in _spans(exporter):
            attrs = dict(span.attributes or {})
            assert "ajolopy.cost_usd.total" not in attrs
            assert "gen_ai.cost_usd" not in attrs
