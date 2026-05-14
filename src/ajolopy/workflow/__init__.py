"""``@Workflow`` primitive — multi-agent orchestration decorator.

Public surface mirrors :mod:`ajolopy.agent`: the decorator factory plus the
error hierarchy and the discriminated event payloads ``stream()`` yields.
Lower-level types (the runtime, the synthetic-tool wire shape) stay
package-private so the v0.1 contract can evolve without breaking users.
"""

from .decorator import Workflow
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
from .runtime import WorkflowRuntime

__all__ = [
    "AgentResultEvent",
    "DoneEvent",
    "HandoffEvent",
    "TokenEvent",
    "Workflow",
    "WorkflowConfigError",
    "WorkflowError",
    "WorkflowEvent",
    "WorkflowMaxStepsError",
    "WorkflowRouteError",
    "WorkflowRuntime",
    "make_agent_result",
    "make_done",
    "make_handoff",
    "make_token",
]
