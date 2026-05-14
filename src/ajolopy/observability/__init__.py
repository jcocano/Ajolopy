"""Observability surface: OpenTelemetry tracing helpers and GenAI conventions.

The framework keeps this module thin on purpose. Higher-level primitives
(``@Agent``, the provider runtime, tool dispatch) reach in for ``get_tracer``
and the ``gen_ai.*`` attribute constants; user code rarely touches this
module directly. The setup helper :func:`setup_tracing_from_env` is the one
exception — ``AjolopyFactory.create()`` calls it once at bootstrap to
auto-install an SDK + OTLP exporter when ``ajolopy[otel]`` is available.
"""

from .conventions import (
    AJOLOPY_AGENT_NAME,
    AJOLOPY_AGENT_OPERATION,
    AJOLOPY_STREAMING,
    GEN_AI_COMPLETION,
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
    OPERATION_CHAT,
    OPERATION_EMBEDDINGS,
    agent_invoke_span_name,
    chat_span_name,
    execute_tool_span_name,
)
from .tracing import get_tracer, is_content_capture_enabled, setup_tracing_from_env

__all__ = [
    "AJOLOPY_AGENT_NAME",
    "AJOLOPY_AGENT_OPERATION",
    "AJOLOPY_STREAMING",
    "GEN_AI_COMPLETION",
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
    "OPERATION_CHAT",
    "OPERATION_EMBEDDINGS",
    "agent_invoke_span_name",
    "chat_span_name",
    "execute_tool_span_name",
    "get_tracer",
    "is_content_capture_enabled",
    "setup_tracing_from_env",
]
