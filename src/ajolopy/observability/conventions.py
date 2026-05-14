"""Span attribute constants used across the Ajolopy observability layer.

The framework follows the **OpenTelemetry GenAI semantic conventions** for every
LLM-call and tool-dispatch span. These constants are duplicated here (rather
than pulled from ``opentelemetry.semconv``) for two reasons:

1. The GenAI conventions are still maturing in the upstream registry; pinning
   them here freezes the wire format Ajolopy emits even if upstream renames an
   attribute.
2. The runtime only needs the api-level ``Tracer``; making ``conventions``
   import-clean from ``opentelemetry.semconv`` would leak an SDK dependency.

Two namespaces:

- ``gen_ai.*`` — cross-vendor GenAI attributes (system, model, usage, tool).
- ``ajolopy.*`` — framework-specific span attributes (agent name, operation,
  streaming flag).
"""

# ---------------------------------------------------------------------------
# OpenTelemetry GenAI semantic conventions
# ---------------------------------------------------------------------------

GEN_AI_SYSTEM = "gen_ai.system"
"""Identifies the LLM vendor: ``anthropic``, ``openai``, ``gcp.gemini``, or
``openai_compatible[.<flavor>]`` for the universal OpenAI-compatible adapter."""

GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
"""The kind of LLM operation: ``chat``, ``text_completion``, ``embeddings``."""

GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
"""Model string sent to the provider (the canonical agent ``model=`` value)."""

GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
"""Model string echoed by the provider in its response, when available."""

GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
"""Sampling temperature used for the request; only set when not ``None``."""

GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
"""Max tokens cap supplied in the request; only set when not ``None``."""

GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
"""Array of normalised finish reasons (``stop``, ``length``, ``tool_calls``,
``error``). Always a list, even for a single reason — the upstream
specification mandates an array for forward compatibility."""

GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
"""Prompt + system + tool-schema tokens billed by the provider."""

GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
"""Completion tokens billed by the provider."""

GEN_AI_COST_USD = "gen_ai.cost_usd"
"""Total cost (USD) of a single ``chat`` span — sum of every tier.

Emitted by the pricing layer (AJ-30) when the model name resolves against
the embedded LiteLLM snapshot or a user-registered override. Unknown models
omit this attribute entirely (a one-time warning is logged per model name
so silently-zero costs never leak into dashboards)."""

GEN_AI_COST_USD_INPUT = "gen_ai.cost_usd.input"
"""Per-tier breakdown: USD billed for non-cached prompt tokens."""

GEN_AI_COST_USD_OUTPUT = "gen_ai.cost_usd.output"
"""Per-tier breakdown: USD billed for completion tokens."""

GEN_AI_COST_USD_CACHE_CREATION = "gen_ai.cost_usd.cache_creation"
"""Per-tier breakdown: USD billed for prompt-cache **writes** (Anthropic-only)."""

GEN_AI_COST_USD_CACHE_READ = "gen_ai.cost_usd.cache_read"
"""Per-tier breakdown: USD billed for prompt-cache **reads** (cheaper hit price)."""

GEN_AI_TOOL_NAME = "gen_ai.tool.name"
"""The tool's wire name (the value the model emitted in its ``tool_use``)."""

GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
"""Provider-supplied tool-call id used to thread the ``tool_result`` back."""

GEN_AI_PROMPT = "gen_ai.prompt"
"""Optional: full prompt content. Only set when content capture is enabled."""

GEN_AI_COMPLETION = "gen_ai.completion"
"""Optional: full assistant completion text. Only set when content capture is
enabled."""

# ---------------------------------------------------------------------------
# Operation name values (GEN_AI_OPERATION_NAME)
# ---------------------------------------------------------------------------

OPERATION_CHAT = "chat"
OPERATION_EMBEDDINGS = "embeddings"

# ---------------------------------------------------------------------------
# Span name templates
# ---------------------------------------------------------------------------


def chat_span_name(model: str) -> str:
    """Span name for an LLM call. Format: ``chat {model}`` (GenAI conv)."""
    return f"chat {model}"


def execute_tool_span_name(tool_name: str) -> str:
    """Span name for a tool dispatch. Format: ``execute_tool {name}`` (GenAI conv)."""
    return f"execute_tool {tool_name}"


def agent_invoke_span_name(agent_name: str) -> str:
    """Span name for the Ajolopy agent root. Format: ``agent.invoke {AgentName}``."""
    return f"agent.invoke {agent_name}"


def workflow_invoke_span_name(name: str) -> str:
    """Span name for the Ajolopy workflow root. Format: ``workflow.invoke {Name}``."""
    return f"workflow.invoke {name}"


def mcp_call_tool_span_name(server_key: str, tool_name: str) -> str:
    """Span name for an MCP tool call.

    Format: ``mcp.call_tool {server_key}/{tool_name}``. The span lands
    as a child of the agent runtime's ``execute_tool`` span so the trace
    shows the namespaced tool dispatch alongside the underlying MCP
    invocation.
    """
    return f"mcp.call_tool {server_key}/{tool_name}"


def mcp_discover_span_name(server_key: str) -> str:
    """Span name for the boot-time discovery roundtrip on one MCP server."""
    return f"mcp.discover {server_key}"


# ---------------------------------------------------------------------------
# Ajolopy-specific attributes (root span only)
# ---------------------------------------------------------------------------

AJOLOPY_AGENT_NAME = "ajolopy.agent.name"
"""The decorated class's ``__name__``."""

AJOLOPY_AGENT_OPERATION = "ajolopy.agent.operation"
"""``run`` for one-shot completion, ``stream`` for streaming."""

AJOLOPY_STREAMING = "ajolopy.streaming"
"""``True`` when the call yields token deltas; ``False`` for one-shot."""

AJOLOPY_COST_USD_TOTAL = "ajolopy.cost_usd.total"
"""Root-level cost roll-up (USD) on the ``agent.invoke`` span.

Equal to the sum of every child ``chat`` span's ``gen_ai.cost_usd``. When
*every* child chat span has an unknown model (no cost computed), this attr
is omitted; otherwise it is the partial sum of children with known cost."""

# ---------------------------------------------------------------------------
# Workflow span attributes (root + handoff breadcrumbs)
# ---------------------------------------------------------------------------

AJOLOPY_WORKFLOW_NAME = "ajolopy.workflow.name"
"""The decorated workflow class's ``__name__``. Lives on the
``workflow.invoke`` root span."""

AJOLOPY_WORKFLOW_OPERATION = "ajolopy.workflow.operation"
"""``run`` for the awaited path, ``stream`` for the async-iterator path."""

AJOLOPY_WORKFLOW_COORDINATOR_MODEL = "ajolopy.workflow.coordinator.model"
"""The ``coordinator=`` model string. Absent when ``route()`` overrides."""

AJOLOPY_WORKFLOW_MAX_STEPS = "ajolopy.workflow.max_steps"
"""The configured cap on coordinator turns. Absent on the ``route()`` path."""

AJOLOPY_WORKFLOW_STEP_COUNT = "ajolopy.workflow.step_count"
"""How many coordinator turns actually executed during this invocation."""

AJOLOPY_WORKFLOW_HANDOFF_COUNT = "ajolopy.workflow.handoff.count"
"""How many delegations the workflow performed during this invocation."""

AJOLOPY_WORKFLOW_HANDOFF_FROM = "ajolopy.workflow.handoff.from"
"""Set on each ``agent.invoke`` child of a workflow span. Either
``coordinator`` (default path) or ``route`` (override path)."""

AJOLOPY_WORKFLOW_HANDOFF_TO = "ajolopy.workflow.handoff.to"
"""The delegated agent's class name. Set on the same ``agent.invoke`` child
as :data:`AJOLOPY_WORKFLOW_HANDOFF_FROM`."""

# ---------------------------------------------------------------------------
# MCP span attributes (AJ-7)
# ---------------------------------------------------------------------------

MCP_SERVER_KEY = "mcp.server.key"
"""User-chosen key from ``@MCP(servers={...})`` (e.g. ``"github"``)."""

MCP_TOOL_NAME = "mcp.tool.name"
"""Raw tool name as exposed by the MCP server (no namespace prefix)."""

MCP_TRANSPORT = "mcp.transport"
"""Transport family: ``"stdio"``, ``"http"``, ``"sse"``, or ``"custom"``."""

MCP_DURATION_MS = "mcp.duration_ms"
"""Wall-clock duration (ms) of the tool call. Set on every
``mcp.call_tool`` span, including failures, so dashboards can correlate
latency with the ``mcp.is_error`` flag."""

MCP_IS_ERROR = "mcp.is_error"
"""``True`` when the MCP server reported ``isError=true`` for a tool
call, or when the call timed out / raised before reaching the server.
Set on both ``mcp.call_tool`` and ``mcp.discover`` spans."""

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
    "agent_invoke_span_name",
    "chat_span_name",
    "execute_tool_span_name",
    "mcp_call_tool_span_name",
    "mcp_discover_span_name",
    "workflow_invoke_span_name",
]
