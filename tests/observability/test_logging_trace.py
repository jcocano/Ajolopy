"""Trace correlation: trace_id / span_id injected when a span is active."""

import json

import pytest
from opentelemetry import trace

from ajolopy import get_logger
from ajolopy.observability.logging import configure_logging

# The shared SDK ``TracerProvider`` is installed by
# ``tests/observability/conftest.py`` at import time. A real provider is
# required for ``get_current_span()`` inside ``start_as_current_span`` to
# return a valid ``SpanContext`` — the api's proxy returns ``INVALID_SPAN``
# even inside a ``with`` block when no SDK is installed.
from tests.observability.conftest import ensure_session_provider

ensure_session_provider()


def _last_json_line(out: str) -> dict[str, object]:
    line = out.strip().splitlines()[-1]
    return json.loads(line)


def test_trace_id_and_span_id_injected_inside_active_span(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")
    tracer = trace.get_tracer("test")
    log = get_logger("ajolopy.trace")

    with tracer.start_as_current_span("op") as span:
        log.info("in-span")
        ctx = span.get_span_context()
        expected_trace = trace.format_trace_id(ctx.trace_id)
        expected_span = trace.format_span_id(ctx.span_id)

    captured = capsys.readouterr()
    obj = _last_json_line(captured.err or captured.out)
    assert obj["trace_id"] == expected_trace
    assert obj["span_id"] == expected_span
    assert len(obj["trace_id"]) == 32  # type: ignore[arg-type]
    assert len(obj["span_id"]) == 16  # type: ignore[arg-type]


def test_no_span_means_trace_id_and_span_id_keys_are_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")
    log = get_logger("ajolopy.trace")
    log.info("no-span")

    captured = capsys.readouterr()
    obj = _last_json_line(captured.err or captured.out)
    assert "trace_id" not in obj
    assert "span_id" not in obj


def test_invalid_noop_span_is_treated_like_no_span(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`opentelemetry.trace.INVALID_SPAN` has an invalid context.

    The processor must take the same branch it takes when no span is
    started — keys are omitted, not emitted as empty strings.
    """
    configure_logging("production")
    log = get_logger("ajolopy.trace")

    # Use the global INVALID_SPAN explicitly. `use_span` makes it the
    # "current" span for the block; its SpanContext is INVALID by design.
    with trace.use_span(trace.INVALID_SPAN, end_on_exit=False):
        log.info("with-invalid-span")

    captured = capsys.readouterr()
    obj = _last_json_line(captured.err or captured.out)
    assert "trace_id" not in obj
    assert "span_id" not in obj


def test_trace_id_appears_in_console_renderer_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dev-mode console output also contains trace_id when a span is active."""
    configure_logging("development")
    tracer = trace.get_tracer("test")
    log = get_logger("ajolopy.trace")

    with tracer.start_as_current_span("op"):
        log.info("in-span-dev")

    captured = capsys.readouterr()
    out = captured.err or captured.out
    assert "trace_id" in out
    assert "span_id" in out
