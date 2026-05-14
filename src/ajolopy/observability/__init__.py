"""Observability surface: structlog setup, OpenTelemetry tracing, GenAI conventions.

The framework keeps this module thin on purpose. Higher-level primitives
(``@Agent``, the provider runtime, tool dispatch) reach in for ``get_tracer``
and the ``gen_ai.*`` attribute constants; user code rarely touches this
module directly. The setup helpers are the one exception:
``AjolopyFactory.create()`` calls :func:`configure_logging` and
:func:`setup_tracing_from_env` once at bootstrap so every Ajolopy app —
plus every third-party library running in the same process — emits logs
and spans through a single configured pipeline. Logging is universal and
runs first; tracing is opt-in via the ``ajolopy[otel]`` extra.

AJ-30 added the pricing layer: :func:`compute_cost_usd` is the public
embeddings / vectorstore entry point for cost emission, and
:class:`Catalog` / :class:`ModelPrice` are the override surface used by
``AjolopyFactory.create(pricing_overrides=...)``.
"""

from .conventions import (
    AJOLOPY_AGENT_NAME,
    AJOLOPY_AGENT_OPERATION,
    AJOLOPY_COST_USD_TOTAL,
    AJOLOPY_STREAMING,
    AJOLOPY_WORKFLOW_COORDINATOR_MODEL,
    AJOLOPY_WORKFLOW_HANDOFF_COUNT,
    AJOLOPY_WORKFLOW_HANDOFF_FROM,
    AJOLOPY_WORKFLOW_HANDOFF_TO,
    AJOLOPY_WORKFLOW_MAX_STEPS,
    AJOLOPY_WORKFLOW_NAME,
    AJOLOPY_WORKFLOW_OPERATION,
    AJOLOPY_WORKFLOW_STEP_COUNT,
    GEN_AI_COMPLETION,
    GEN_AI_COST_USD,
    GEN_AI_COST_USD_CACHE_CREATION,
    GEN_AI_COST_USD_CACHE_READ,
    GEN_AI_COST_USD_INPUT,
    GEN_AI_COST_USD_OUTPUT,
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROMPT,
    GEN_AI_REQUEST_MAX_TOKENS,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_TEMPERATURE,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_NAME,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    MCP_DURATION_MS,
    MCP_IS_ERROR,
    MCP_SERVER_KEY,
    MCP_TOOL_NAME,
    MCP_TRANSPORT,
    OPERATION_CHAT,
    OPERATION_EMBEDDINGS,
    agent_invoke_span_name,
    chat_span_name,
    execute_tool_span_name,
    mcp_call_tool_span_name,
    mcp_discover_span_name,
    workflow_invoke_span_name,
)
from .logging import configure_logging, get_logger
from .pricing import Catalog, ModelPrice, compute_cost_usd
from .tracing import get_tracer, is_content_capture_enabled, setup_tracing_from_env

__all__ = [
    "AJOLOPY_AGENT_NAME",
    "AJOLOPY_AGENT_OPERATION",
    "AJOLOPY_COST_USD_TOTAL",
    "AJOLOPY_STREAMING",
    "AJOLOPY_WORKFLOW_COORDINATOR_MODEL",
    "AJOLOPY_WORKFLOW_HANDOFF_COUNT",
    "AJOLOPY_WORKFLOW_HANDOFF_FROM",
    "AJOLOPY_WORKFLOW_HANDOFF_TO",
    "AJOLOPY_WORKFLOW_MAX_STEPS",
    "AJOLOPY_WORKFLOW_NAME",
    "AJOLOPY_WORKFLOW_OPERATION",
    "AJOLOPY_WORKFLOW_STEP_COUNT",
    "GEN_AI_COMPLETION",
    "GEN_AI_COST_USD",
    "GEN_AI_COST_USD_CACHE_CREATION",
    "GEN_AI_COST_USD_CACHE_READ",
    "GEN_AI_COST_USD_INPUT",
    "GEN_AI_COST_USD_OUTPUT",
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_PROMPT",
    "GEN_AI_REQUEST_MAX_TOKENS",
    "GEN_AI_REQUEST_MODEL",
    "GEN_AI_REQUEST_TEMPERATURE",
    "GEN_AI_RESPONSE_FINISH_REASONS",
    "GEN_AI_RESPONSE_MODEL",
    "GEN_AI_SYSTEM",
    "GEN_AI_TOOL_CALL_ID",
    "GEN_AI_TOOL_NAME",
    "GEN_AI_USAGE_INPUT_TOKENS",
    "GEN_AI_USAGE_OUTPUT_TOKENS",
    "MCP_DURATION_MS",
    "MCP_IS_ERROR",
    "MCP_SERVER_KEY",
    "MCP_TOOL_NAME",
    "MCP_TRANSPORT",
    "OPERATION_CHAT",
    "OPERATION_EMBEDDINGS",
    "Catalog",
    "ModelPrice",
    "agent_invoke_span_name",
    "chat_span_name",
    "compute_cost_usd",
    "configure_logging",
    "execute_tool_span_name",
    "get_logger",
    "get_tracer",
    "is_content_capture_enabled",
    "mcp_call_tool_span_name",
    "mcp_discover_span_name",
    "setup_tracing_from_env",
    "workflow_invoke_span_name",
]
