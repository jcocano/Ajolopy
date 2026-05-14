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
from .logging import configure_logging, get_logger
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
    "configure_logging",
    "execute_tool_span_name",
    "get_logger",
    "get_tracer",
    "is_content_capture_enabled",
    "setup_tracing_from_env",
]
