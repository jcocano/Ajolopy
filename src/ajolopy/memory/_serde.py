"""Internal helpers to serialise :class:`Message` objects to / from JSON.

The framework's :class:`Message` is a plain ``@dataclass`` (so the
provider layer takes no pydantic dependency), which means we cannot
call ``model_dump_json`` on it. The serde helpers in this module pin
the wire shape consumed by every persistent backend (Redis,
PostgreSQL, MongoDB, SQLite).

The format is intentionally minimal: a single JSON object with the
fields of :class:`Message` and a nested ``tool_calls`` array of
:class:`ToolCall` objects. New optional fields can be added without
breaking older payloads — :func:`message_from_json` ignores unknown
keys and falls back to dataclass defaults for missing keys.
"""

import json
from typing import Any, cast

from ajolopy.providers import Message, ToolCall


def message_to_json(message: Message) -> str:
    """Serialise a :class:`Message` to a JSON string."""
    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls
        ],
        "is_error": message.is_error,
    }
    return json.dumps(payload, ensure_ascii=False)


def message_from_json(payload: str) -> Message:
    """Deserialise a :class:`Message` from a JSON string."""
    raw_any: Any = json.loads(payload)
    if not isinstance(raw_any, dict):
        raise ValueError(f"Expected JSON object for Message payload, got {type(raw_any).__name__}.")
    raw = cast("dict[str, Any]", raw_any)
    tool_calls_raw_any: Any = raw.get("tool_calls") or []
    tool_calls: list[ToolCall] = []
    if isinstance(tool_calls_raw_any, list):
        for entry_any in cast("list[Any]", tool_calls_raw_any):
            if not isinstance(entry_any, dict):
                continue
            entry = cast("dict[str, Any]", entry_any)
            args_any: Any = entry.get("arguments") or {}
            arguments: dict[str, Any] = (
                cast("dict[str, Any]", args_any) if isinstance(args_any, dict) else {}
            )
            tool_calls.append(
                ToolCall(
                    id=str(entry.get("id", "")),
                    name=str(entry.get("name", "")),
                    arguments=arguments,
                )
            )
    role_any: Any = raw.get("role", "user")
    name_any: Any = raw.get("name")
    tool_call_id_any: Any = raw.get("tool_call_id")
    return Message(
        role=role_any,
        content=str(raw.get("content", "")),
        name=str(name_any) if isinstance(name_any, str) else None,
        tool_call_id=str(tool_call_id_any) if isinstance(tool_call_id_any, str) else None,
        tool_calls=tool_calls,
        is_error=bool(raw.get("is_error", False)),
    )


__all__ = ["message_from_json", "message_to_json"]
