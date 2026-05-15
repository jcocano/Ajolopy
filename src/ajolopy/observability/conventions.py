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


def mcp_server_call_tool_span_name(server_name: str, tool_name: str) -> str:
    """Span name for a publish-side ``@MCPServer`` tool dispatch.

    Format: ``mcp_server.call_tool {server_name}/{tool_name}``. Mirrors
    the agent runtime's ``execute_tool`` span shape so dashboards can
    distinguish publish-side dispatch (AJ-60) from consume-side calls
    (``mcp.call_tool``, AJ-7).
    """
    return f"mcp_server.call_tool {server_name}/{tool_name}"


def mcp_server_boot_span_name(server_name: str) -> str:
    """Span name for the one-time server boot (stdio CLI or HTTP/SSE mount)."""
    return f"mcp_server.boot {server_name}"


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

# ---------------------------------------------------------------------------
# MCP server attributes (AJ-60 -- publish side)
# ---------------------------------------------------------------------------

AJOLOPY_MCP_SERVER_NAME = "ajolopy.mcp_server.name"
"""User-visible name reported in the MCP ``initialize`` handshake
(kebab-cased class name by default)."""

AJOLOPY_MCP_SERVER_TRANSPORT = "ajolopy.mcp_server.transport"
"""Transport family for the published server: ``"stdio"``, ``"http"``,
or ``"sse"``."""

AJOLOPY_MCP_SERVER_TOOL_NAME = "ajolopy.mcp_server.tool.name"
"""The raw ``@Tool`` method name as exposed to MCP clients."""

AJOLOPY_MCP_SERVER_IS_ERROR = "ajolopy.mcp_server.is_error"
"""``True`` when the dispatch raised (validation, runtime exception,
unknown tool name). Set on every ``mcp_server.call_tool`` span."""

AJOLOPY_MCP_SERVER_DURATION_MS = "ajolopy.mcp_server.duration_ms"
"""Wall-clock duration (ms) of one tool dispatch, including the
host-class instantiation amortised on first call."""

# ---------------------------------------------------------------------------
# Eval span attributes (AJ-4)
# ---------------------------------------------------------------------------

AJOLOPY_EVAL_SUITE = "ajolopy.eval.suite"
"""The ``@Eval`` class's ``__name__``. Lives on the ``eval.run`` root span."""

AJOLOPY_EVAL_TARGET_KIND = "ajolopy.eval.target_kind"
"""``"agent"`` or ``"workflow"`` depending on which target was registered."""

AJOLOPY_EVAL_TARGET_NAME = "ajolopy.eval.target_name"
"""The ``@Agent`` or ``@Workflow`` class's ``__name__`` (the target's name)."""

AJOLOPY_EVAL_THRESHOLD = "ajolopy.eval.threshold"
"""Configured aggregate threshold; the run passes when ``aggregate_score``
clears this bar."""

AJOLOPY_EVAL_AGGREGATE_SCORE = "ajolopy.eval.aggregate_score"
"""Weighted aggregate score across every metric. Written at the end of
the run."""

AJOLOPY_EVAL_PASSED = "ajolopy.eval.passed"
"""``True`` when ``aggregate_score >= threshold``. Written at the end of
the run."""

AJOLOPY_EVAL_CONCURRENCY = "ajolopy.eval.concurrency"
"""Configured per-suite case concurrency cap."""

AJOLOPY_EVAL_CASE_INDEX = "ajolopy.eval.case_index"
"""0-based dataset index of one case. Lives on every ``eval.case`` span."""

AJOLOPY_EVAL_CASE_PASSED = "ajolopy.eval.case_passed"
"""Per-case boolean roll-up: ``error is None`` AND every metric cleared
its ``pass_threshold``."""

AJOLOPY_EVAL_CASE_ERROR = "ajolopy.eval.case_error"
"""Stringified exception when the target invocation or a metric raised.
Absent on successful cases."""

AJOLOPY_EVAL_SCORE_PREFIX = "ajolopy.eval.score."
"""Per-metric per-case score attributes use this prefix; e.g.
``ajolopy.eval.score.helpful``. No constant per metric — the name is
built at emission time from the metric's class-declared identifier."""

# ---------------------------------------------------------------------------
# Cross-provider fallback span event (AJ-23)
# ---------------------------------------------------------------------------

GEN_AI_CHAT_FALLBACK_EVENT = "gen_ai.chat.fallback"
"""Name of the span event recorded on the *next* ``chat`` span whenever the
preceding provider call raised :class:`LLMProviderError` and the runtime
advanced to the next model in the fallback chain. The event documents the
transition so trace viewers can show "model X failed → model Y handled it"
without scraping span statuses."""

AJOLOPY_FALLBACK_FROM = "ajolopy.fallback.from"
"""The failing model string that triggered the fallback (``"claude-sonnet-4-7"``)."""

AJOLOPY_FALLBACK_FROM_PROVIDER = "ajolopy.fallback.from_provider"
"""Provider key of the failing model (``"anthropic"``)."""

AJOLOPY_FALLBACK_TO = "ajolopy.fallback.to"
"""The next model string the runtime advanced to (``"gpt-4o-mini"``)."""

AJOLOPY_FALLBACK_TO_PROVIDER = "ajolopy.fallback.to_provider"
"""Provider key of the next model (``"openai"``)."""

AJOLOPY_FALLBACK_REASON = "ajolopy.fallback.reason"
"""``str(exception)`` from the failing call, truncated to 200 characters so
trace backends never reject the attribute as oversized."""

FALLBACK_REASON_MAX_CHARS = 200
"""Hard cap applied to :data:`AJOLOPY_FALLBACK_REASON`. Spec-locked."""


def eval_run_span_name(suite_name: str) -> str:
    """Span name for the root of one :meth:`EvalRunner.run`.

    Format: ``eval.run {SuiteName}`` to match the ``agent.invoke`` /
    ``workflow.invoke`` convention.
    """
    return f"eval.run {suite_name}"


def eval_case_span_name(case_index: int) -> str:
    """Span name for one case under an ``eval.run`` root.

    Format: ``eval.case {i}`` where ``i`` is the 0-based dataset index.
    """
    return f"eval.case {case_index}"


__all__ = [
    "AJOLOPY_AGENT_NAME",
    "AJOLOPY_AGENT_OPERATION",
    "AJOLOPY_COST_USD_TOTAL",
    "AJOLOPY_EVAL_AGGREGATE_SCORE",
    "AJOLOPY_EVAL_CASE_ERROR",
    "AJOLOPY_EVAL_CASE_INDEX",
    "AJOLOPY_EVAL_CASE_PASSED",
    "AJOLOPY_EVAL_CONCURRENCY",
    "AJOLOPY_EVAL_PASSED",
    "AJOLOPY_EVAL_SCORE_PREFIX",
    "AJOLOPY_EVAL_SUITE",
    "AJOLOPY_EVAL_TARGET_KIND",
    "AJOLOPY_EVAL_TARGET_NAME",
    "AJOLOPY_EVAL_THRESHOLD",
    "AJOLOPY_FALLBACK_FROM",
    "AJOLOPY_FALLBACK_FROM_PROVIDER",
    "AJOLOPY_FALLBACK_REASON",
    "AJOLOPY_FALLBACK_TO",
    "AJOLOPY_FALLBACK_TO_PROVIDER",
    "AJOLOPY_MCP_SERVER_DURATION_MS",
    "AJOLOPY_MCP_SERVER_IS_ERROR",
    "AJOLOPY_MCP_SERVER_NAME",
    "AJOLOPY_MCP_SERVER_TOOL_NAME",
    "AJOLOPY_MCP_SERVER_TRANSPORT",
    "AJOLOPY_STREAMING",
    "AJOLOPY_WORKFLOW_COORDINATOR_MODEL",
    "AJOLOPY_WORKFLOW_HANDOFF_COUNT",
    "AJOLOPY_WORKFLOW_HANDOFF_FROM",
    "AJOLOPY_WORKFLOW_HANDOFF_TO",
    "AJOLOPY_WORKFLOW_MAX_STEPS",
    "AJOLOPY_WORKFLOW_NAME",
    "AJOLOPY_WORKFLOW_OPERATION",
    "AJOLOPY_WORKFLOW_STEP_COUNT",
    "FALLBACK_REASON_MAX_CHARS",
    "GEN_AI_CHAT_FALLBACK_EVENT",
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
    "eval_case_span_name",
    "eval_run_span_name",
    "execute_tool_span_name",
    "mcp_call_tool_span_name",
    "mcp_discover_span_name",
    "mcp_server_boot_span_name",
    "mcp_server_call_tool_span_name",
    "workflow_invoke_span_name",
]
