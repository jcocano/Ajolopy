"""Server-Sent Events wire format helpers.

The SSE spec (https://html.spec.whatwg.org/multipage/server-sent-events.html)
frames each event as one or more ``field: value`` lines terminated by an
empty line. Multi-line values are split into multiple ``data:`` lines;
keep-alive uses a comment line (``: text``); structured payloads are
emitted as single-line JSON.

All formatters return ``bytes`` ready to be yielded by a Starlette
``StreamingResponse`` body iterator.
"""

import json
from typing import Any

from pydantic import BaseModel

from .errors import StreamRuntimeError

_JSON_SEPARATORS: tuple[str, str] = (",", ":")


def format_data_event(value: object) -> bytes:
    """Encode ``value`` as one SSE ``data:`` event.

    ``str`` → ``data: <line>\\n`` per newline-separated chunk, terminated
    by the SSE empty line. ``dict`` and Pydantic ``BaseModel`` → compact
    UTF-8 JSON on a single ``data:`` line. Anything else raises
    :class:`StreamRuntimeError`; the SSE wrapper catches it and emits the
    error envelope.
    """
    text = _to_text(value)
    # Per the SSE spec, embedded newlines split into multiple ``data:`` lines.
    lines = text.split("\n")
    framed = "".join(f"data: {line}\n" for line in lines)
    return (framed + "\n").encode("utf-8")


def format_keepalive() -> bytes:
    """Encode a comment-only SSE record so intermediaries see traffic."""
    return b": keepalive\n\n"


def format_error_event(message: str) -> bytes:
    """Encode the terminal error event sent before the stream closes."""
    payload = json.dumps({"error": message}, ensure_ascii=False, separators=_JSON_SEPARATORS)
    return f"data: {payload}\n\n".encode()


def _to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    if isinstance(value, dict):
        # narrow Any-keyed dict to str-keyed JSON via dumps' default.
        return json.dumps(value, ensure_ascii=False, separators=_JSON_SEPARATORS, default=_jsonable)
    raise StreamRuntimeError(
        f"@Stream handlers must yield str, dict, or BaseModel; got {type(value).__name__}."
    )


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON-serialisable")
