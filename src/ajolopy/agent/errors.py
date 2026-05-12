"""Errors raised by the ``@Agent`` runtime.

All errors derive from ``AgentError`` so callers catch the framework with a
single ``except``. Subclasses signal distinct failure modes:

- ``AgentConfigError`` — bootstrap problem (missing env var, unknown model,
  un-registered fallback provider). Raised at decoration time so the process
  fails before serving traffic.
- ``AgentProviderError`` — every retriable / non-retriable provider failure
  bubbles up wrapped in this type so callers never see ``httpx`` /
  vendor-SDK exceptions.
- ``AgentToolUseUnsupportedError`` — the model produced a ``tool_use``
  response but the function-calling loop is not part of AJ-1; AJ-2 ships
  the loop. Raised with an actionable message pointing at AJ-2.
"""


class AgentError(RuntimeError):
    """Base class for any error raised by the ``@Agent`` runtime."""


class AgentConfigError(AgentError):
    """Misconfiguration detected at decoration time."""


class AgentProviderError(AgentError):
    """A provider call exhausted retries / fallbacks and still failed."""


class AgentToolUseUnsupportedError(AgentError):
    """Model returned a ``tool_use`` response but no tool loop is wired.

    AJ-2 delivers the loop. Until then ``@Agent(tools=[...])`` callers must
    handle this error themselves or wait for AJ-2 to land.
    """
