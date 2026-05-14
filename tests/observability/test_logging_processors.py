"""The `add_processors` extension hook runs before the renderer."""

import json
from collections.abc import MutableMapping
from typing import Any

import pytest

from ajolopy import get_logger
from ajolopy.observability.logging import configure_logging

# `structlog.typing.EventDict` is itself ``MutableMapping[str, Any]``; using
# that alias here keeps the test processor signature pyright-strict-clean
# without importing from the private ``structlog.typing`` namespace.
EventDict = MutableMapping[str, Any]


def _last_json(out: str) -> dict[str, object]:
    return json.loads(out.strip().splitlines()[-1])


def test_add_processors_runs_before_renderer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A custom processor must see + mutate the event dict before rendering."""

    def stamp_request_id(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
        event_dict["request_id"] = "rid-abc-123"
        return event_dict

    configure_logging("production", add_processors=[stamp_request_id])
    get_logger("ajolopy.proc").info("hello")

    captured = capsys.readouterr()
    obj = _last_json(captured.err or captured.out)
    assert obj["request_id"] == "rid-abc-123"
    assert obj["event"] == "hello"


def test_add_processors_default_none_leaves_pipeline_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")  # add_processors omitted
    get_logger("ajolopy.proc").info("plain")
    captured = capsys.readouterr()
    obj = _last_json(captured.err or captured.out)
    # No surprise fields beyond the documented contract.
    assert obj.keys() >= {"event", "level", "logger", "timestamp"}
    assert "request_id" not in obj


def test_add_processors_run_in_order_after_builtins(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two custom processors compose; later ones see earlier mutations."""

    def first(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
        event_dict["step1"] = "ok"
        return event_dict

    def second(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
        # Reads `step1` set by `first`; proves ordering.
        event_dict["step2"] = event_dict.get("step1") == "ok"
        return event_dict

    configure_logging("production", add_processors=[first, second])
    get_logger("ajolopy.proc").info("ordered")
    captured = capsys.readouterr()
    obj = _last_json(captured.err or captured.out)
    assert obj["step1"] == "ok"
    assert obj["step2"] is True


def test_add_processors_with_empty_list_is_equivalent_to_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production", add_processors=[])
    get_logger("ajolopy.proc").info("plain")
    captured = capsys.readouterr()
    obj = _last_json(captured.err or captured.out)
    assert "request_id" not in obj
    assert obj.keys() >= {"event", "level", "logger", "timestamp"}
