"""SSE wire-format helpers — ``format_data_event``, ``format_keepalive``,
``format_error_event``."""

import pytest
from pydantic import BaseModel

from ajolopy.stream import (
    StreamRuntimeError,
    format_data_event,
    format_error_event,
    format_keepalive,
)


class TestDataEvent:
    def test_str_single_line(self) -> None:
        assert format_data_event("hello") == b"data: hello\n\n"

    def test_str_multiline_splits(self) -> None:
        assert format_data_event("line1\nline2") == b"data: line1\ndata: line2\n\n"

    def test_str_with_trailing_newline_yields_empty_trailing_data(self) -> None:
        # Per spec, "hi\n" splits into ["hi", ""] → two data: lines.
        assert format_data_event("hi\n") == b"data: hi\ndata: \n\n"

    def test_dict_serialises_to_compact_json(self) -> None:
        event = format_data_event({"event": "token", "value": "ok"})
        assert event == b'data: {"event":"token","value":"ok"}\n\n'

    def test_basemodel_uses_model_dump_json(self) -> None:
        class Payload(BaseModel):
            event: str
            value: int

        event = format_data_event(Payload(event="x", value=7))
        assert event == b'data: {"event":"x","value":7}\n\n'

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(StreamRuntimeError, match="must yield str, dict, or BaseModel"):
            format_data_event(42)

    def test_bytes_rejected(self) -> None:
        with pytest.raises(StreamRuntimeError):
            format_data_event(b"binary")


class TestKeepalive:
    def test_format(self) -> None:
        assert format_keepalive() == b": keepalive\n\n"


class TestErrorEvent:
    def test_format(self) -> None:
        assert format_error_event("boom") == b'data: {"error":"boom"}\n\n'

    def test_non_ascii_preserved(self) -> None:
        # Spanish text must round-trip without escaping.
        encoded = format_error_event("falló")
        assert encoded == b'data: {"error":"fall\xc3\xb3"}\n\n'
