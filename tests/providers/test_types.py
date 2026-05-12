"""Tests for the wire-format types.

Covers the "Types" acceptance group: exports + Literal enforcement.
Literal compile-time enforcement is verified at type-check time by pyright;
this file pins the runtime annotation so that property cannot silently
regress.

The whole module is accessed via a single ``providers`` alias so CodeQL does
not flag mixed ``import`` / ``from … import`` styles on the same package.
"""

import typing
from typing import get_args, get_type_hints

import ajolopy.providers as providers


def test_wire_types_are_publicly_exported() -> None:
    exported = set(providers.__all__)
    expected = {
        "Chunk",
        "FinishReason",
        "Message",
        "Response",
        "Role",
        "Tool",
        "ToolCall",
        "ToolCallDelta",
    }
    assert expected <= exported


def test_role_literal_values() -> None:
    assert set(get_args(providers.Role)) == {"system", "user", "assistant", "tool"}


def test_finish_reason_literal_values() -> None:
    assert set(get_args(providers.FinishReason)) == {"stop", "length", "tool_calls", "error"}


def test_response_finish_reason_annotation_is_literal() -> None:
    hints = get_type_hints(providers.Response)
    assert hints["finish_reason"] is providers.FinishReason or set(
        get_args(hints["finish_reason"])
    ) == {
        "stop",
        "length",
        "tool_calls",
        "error",
    }


def test_chunk_finish_reason_annotation_is_optional_literal() -> None:
    hints = get_type_hints(providers.Chunk)
    chunk_fr = hints["finish_reason"]
    # Optional[FinishReason] resolves to Union[FinishReason, None]; assert both arms.
    args = get_args(chunk_fr)
    assert type(None) in args
    literal_arm = next(arg for arg in args if arg is not type(None))
    assert set(get_args(literal_arm)) == {"stop", "length", "tool_calls", "error"}


def test_message_construction_round_trip() -> None:
    msg = providers.Message(role="user", content="hi")
    assert msg.role == "user"
    assert msg.content == "hi"
    assert msg.name is None
    assert msg.tool_call_id is None


def test_tool_call_carries_structured_arguments() -> None:
    tc = providers.ToolCall(id="call_1", name="lookup", arguments={"order_id": "X-1"})
    assert tc.arguments["order_id"] == "X-1"


def test_tool_call_delta_supports_partial_arguments() -> None:
    delta = providers.ToolCallDelta(id="call_1", name="lookup", arguments_delta='{"order_id": "X')
    assert delta.arguments_delta == '{"order_id": "X'


def test_tool_default_construction() -> None:
    tool = providers.Tool(name="lookup", description="Look up an order", parameters={})
    assert tool.name == "lookup"


def test_typing_module_resolves_module_aliases() -> None:
    # Defensive: keep this assertion so any future re-export accident surfaces.
    assert typing.get_origin(providers.Response.__annotations__["tool_calls"]) is list
