"""Stdlib `logging` capture: third-party loggers inherit the same pipeline."""

import json
import logging

import pytest
from opentelemetry import trace

from ajolopy import get_logger
from ajolopy.observability.logging import configure_logging
from tests.observability.conftest import ensure_session_provider

ensure_session_provider()


def _last_json(out: str) -> dict[str, object]:
    return json.loads(out.strip().splitlines()[-1])


def test_stdlib_logger_in_ajolopy_namespace_renders_through_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")

    logging.getLogger("ajolopy.test_module").info("via stdlib")
    captured_stdlib = capsys.readouterr()
    obj_stdlib = _last_json(captured_stdlib.err or captured_stdlib.out)

    get_logger("ajolopy.test_module").info("via structlog")
    captured_structlog = capsys.readouterr()
    obj_structlog = _last_json(captured_structlog.err or captured_structlog.out)

    # Both lines share the same canonical structure: same renderer, same
    # set of stamped keys.
    assert obj_stdlib["event"] == "via stdlib"
    assert obj_structlog["event"] == "via structlog"
    assert obj_stdlib.keys() >= {"event", "level", "logger", "timestamp"}
    assert obj_structlog.keys() >= {"event", "level", "logger", "timestamp"}


def test_third_party_logger_outside_ajolopy_namespace_is_captured(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")
    logging.getLogger("acme").warning("third party warning")
    captured = capsys.readouterr()
    obj = _last_json(captured.err or captured.out)
    assert obj["event"] == "third party warning"
    assert obj["level"] == "warning"
    assert obj["logger"] == "acme"


def test_third_party_logger_inherits_trace_correlation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("op") as span:
        logging.getLogger("acme.client").warning("with trace")
        ctx = span.get_span_context()
        expected_trace = trace.format_trace_id(ctx.trace_id)

    captured = capsys.readouterr()
    obj = _last_json(captured.err or captured.out)
    assert obj["trace_id"] == expected_trace


def test_capture_stdlib_false_does_not_install_root_handler() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    configure_logging("development", capture_stdlib=False)
    after = list(root.handlers)
    # No new handler attached when stdlib capture is disabled.
    assert after == before
