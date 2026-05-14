"""Public API surface and ``__all__`` membership for ``@Workflow``.

Covers the "Public re-exports" acceptance group: ``from ajolopy import
Workflow`` works, the workflow error / event types are reachable via
``ajolopy.workflow``, and ``Workflow`` lives in
``ajolopy.__all__``.
"""

import ajolopy


def test_workflow_re_exported_from_top_level_package() -> None:
    assert hasattr(ajolopy, "Workflow")
    assert ajolopy.Workflow is ajolopy.workflow.Workflow


def test_workflow_in_top_level_dunder_all() -> None:
    assert "Workflow" in ajolopy.__all__


def test_workflow_error_subclasses_reexported() -> None:
    from ajolopy.workflow import (
        WorkflowConfigError,
        WorkflowError,
        WorkflowMaxStepsError,
        WorkflowRouteError,
    )

    assert issubclass(WorkflowConfigError, WorkflowError)
    assert issubclass(WorkflowMaxStepsError, WorkflowError)
    assert issubclass(WorkflowRouteError, WorkflowError)


def test_event_typeddicts_reexported() -> None:
    from ajolopy.workflow import (
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

    assert make_handoff(agent="A", message="m") == {
        "type": "handoff",
        "agent": "A",
        "message": "m",
    }
    assert make_agent_result(agent="A", output="o") == {
        "type": "agent_result",
        "agent": "A",
        "output": "o",
    }
    assert make_token(text="t") == {"type": "token", "text": "t"}
    assert make_done(text="d") == {"type": "done", "text": "d"}
    # The TypedDicts/aliases are importable - merely referencing them
    # locks the public surface for forward-compat tests.
    _ = (HandoffEvent, AgentResultEvent, TokenEvent, DoneEvent, WorkflowEvent)
