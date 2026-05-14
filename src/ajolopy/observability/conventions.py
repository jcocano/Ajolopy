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

__all__ = [
    "AJOLOPY_AGENT_NAME",
    "AJOLOPY_AGENT_OPERATION",
    "AJOLOPY_COST_USD_TOTAL",
    "AJOLOPY_STREAMING",
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
    "OPERATION_CHAT",
    "OPERATION_EMBEDDINGS",
    "agent_invoke_span_name",
    "chat_span_name",
    "execute_tool_span_name",
]
