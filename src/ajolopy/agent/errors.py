"""Errors raised by the ``@Agent`` runtime.

All errors derive from ``AgentError`` so callers catch the framework with a
single ``except``. Subclasses signal distinct failure modes:

- ``AgentConfigError`` — bootstrap problem (missing env var, unknown model,
  un-registered fallback provider, malformed tool definition). Raised at
  decoration time so the process fails before serving traffic.
- ``AgentProviderError`` — every retriable / non-retriable provider failure
  bubbles up wrapped in this type so callers never see ``httpx`` /
  vendor-SDK exceptions.
- ``ToolDefinitionError`` — a ``@Tool`` could not be analysed at decoration
  time (missing annotation, unserialisable parameter type, collision with
  another tool's name).
- ``AgentToolLoopError`` — the function-calling loop exceeded
  ``max_tool_iterations`` without the model producing a tool-free response.
"""


class AgentError(RuntimeError):
    """Base class for any error raised by the ``@Agent`` runtime."""


class AgentConfigError(AgentError):
    """Misconfiguration detected at decoration time."""


class AgentProviderError(AgentError):
    """A provider call exhausted retries / fallbacks and still failed."""


class ToolDefinitionError(AgentConfigError):
    """A ``@Tool``-decorated callable could not be analysed at decoration time."""


class AgentToolLoopError(AgentError):
    """The function-calling loop exceeded ``max_tool_iterations``."""
