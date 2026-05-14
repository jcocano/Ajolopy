"""Errors raised by the ``@Workflow`` runtime.

All errors derive from :class:`WorkflowError` so callers can catch the
framework with a single ``except``. Subclasses signal distinct failure
modes:

- :class:`WorkflowConfigError` — misconfiguration detected at decoration
  time (empty ``agents=`` list, missing coordinator + ``route()`` pair,
  unknown coordinator model, ``integrations=`` reserved for AJ-7,
  ``max_steps < 1``).
- :class:`WorkflowMaxStepsError` — the coordinator tool-calling loop
  exceeded ``max_steps`` without producing a tool-free response.
- :class:`WorkflowRouteError` — the user-supplied ``route()`` override
  returned an invalid value, raised an exception, or pointed at a class
  not declared in ``agents=``.
"""


class WorkflowError(RuntimeError):
    """Base class for any error raised by the ``@Workflow`` runtime."""


class WorkflowConfigError(WorkflowError):
    """Misconfiguration detected at decoration time."""


class WorkflowMaxStepsError(WorkflowError):
    """The coordinator tool-calling loop exceeded ``max_steps``.

    Carries the configured cap and the number of coordinator turns that
    actually executed so telemetry pipelines can correlate the failure
    with the offending invocation.
    """

    def __init__(self, message: str, *, max_steps: int, step_count: int) -> None:
        super().__init__(message)
        self.max_steps = max_steps
        self.step_count = step_count


class WorkflowRouteError(WorkflowError):
    """The user-supplied ``route()`` returned an invalid value or raised."""


__all__ = [
    "WorkflowConfigError",
    "WorkflowError",
    "WorkflowMaxStepsError",
    "WorkflowRouteError",
]
