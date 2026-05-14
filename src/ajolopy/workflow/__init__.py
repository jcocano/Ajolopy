"""``@Workflow`` primitive — multi-agent orchestration decorator.

Public surface mirrors :mod:`ajolopy.agent`: the decorator factory plus the
error hierarchy and the discriminated event payloads ``stream()`` yields.
Lower-level types (the runtime, the synthetic-tool wire shape) stay
package-private so the v0.1 contract can evolve without breaking users.
"""

from .errors import (
    WorkflowConfigError,
    WorkflowError,
    WorkflowMaxStepsError,
    WorkflowRouteError,
)
from .events import (
    AgentResultEvent,
    DoneEvent,
    HandoffEvent,
    TokenEvent,
    WorkflowEvent,
    make_agent_result,
    make_done,
    make_handoff,
    make_token,
)

__all__ = [
    "AgentResultEvent",
    "DoneEvent",
    "HandoffEvent",
    "TokenEvent",
    "WorkflowConfigError",
    "WorkflowError",
    "WorkflowEvent",
    "WorkflowMaxStepsError",
    "WorkflowRouteError",
    "make_agent_result",
    "make_done",
    "make_handoff",
    "make_token",
]
