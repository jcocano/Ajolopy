"""Discriminated event payloads yielded by ``Workflow.stream()``.

The ``stream()`` method yields plain dictionaries (no Pydantic models, no
dataclasses) so they serialise via :func:`json.dumps` without an extra
converter and so :mod:`ajolopy.stream` can frame them as SSE ``data:``
records without special-casing the host primitive.

Each event variant is described by a ``TypedDict`` with a constant
``type`` discriminator. The :data:`WorkflowEvent` union covers every
variant; consumers should switch on the ``type`` key and treat unknown
discriminator values as forward-compatible no-ops.

Factory helpers (:func:`make_handoff`, :func:`make_agent_result`,
:func:`make_token`, :func:`make_done`) build well-typed instances so the
runtime never builds raw dicts.
"""

from typing import Literal, TypedDict


class HandoffEvent(TypedDict):
    """Emitted before delegating to an agent. ``agent`` is its class name."""

    type: Literal["handoff"]
    agent: str
    message: str


class AgentResultEvent(TypedDict):
    """Emitted after a delegated agent returns. ``output`` is its text."""

    type: Literal["agent_result"]
    agent: str
    output: str


class TokenEvent(TypedDict):
    """A coordinator token emitted on its final, tool-free turn."""

    type: Literal["token"]
    text: str


class DoneEvent(TypedDict):
    """Terminal event carrying the full final text. Always last on success."""

    type: Literal["done"]
    text: str


WorkflowEvent = HandoffEvent | AgentResultEvent | TokenEvent | DoneEvent
"""Union of every event variant ``stream()`` may yield in v0.1."""


def make_handoff(*, agent: str, message: str) -> HandoffEvent:
    """Build a :class:`HandoffEvent` for the named agent and message."""
    return {"type": "handoff", "agent": agent, "message": message}


def make_agent_result(*, agent: str, output: str) -> AgentResultEvent:
    """Build an :class:`AgentResultEvent` for the named agent's output."""
    return {"type": "agent_result", "agent": agent, "output": output}


def make_token(*, text: str) -> TokenEvent:
    """Build a :class:`TokenEvent` for the given coordinator token."""
    return {"type": "token", "text": text}


def make_done(*, text: str) -> DoneEvent:
    """Build the terminal :class:`DoneEvent` carrying the final text."""
    return {"type": "done", "text": text}


__all__ = [
    "AgentResultEvent",
    "DoneEvent",
    "HandoffEvent",
    "TokenEvent",
    "WorkflowEvent",
    "make_agent_result",
    "make_done",
    "make_handoff",
    "make_token",
]
