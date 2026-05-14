"""Renderer selection + shape: ConsoleRenderer in dev/test, JSONRenderer in prod."""

import json
import logging
import re
from datetime import datetime

import pytest

from ajolopy import get_logger
from ajolopy.observability.logging import configure_logging

# Matches ANSI escape sequences emitted by structlog's ConsoleRenderer when
# colors are enabled. ConsoleRenderer's exact byte output is not stable
# across structlog versions, but the presence of an escape sequence is.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _emit(name: str, message: str, **kw: object) -> None:
    """Emit a single log line at INFO via the public structlog API."""
    log = get_logger(name)
    log.info(message, **kw)


def test_development_uses_console_renderer_with_ansi(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("development")
    _emit("ajolopy.dev", "hello", k="v")
    captured = capsys.readouterr()
    out = captured.err or captured.out
    assert "hello" in out
    assert "k" in out
    assert "v" in out
    assert _ANSI_RE.search(out) is not None, f"Expected ANSI escapes, got: {out!r}"


def test_test_env_uses_console_renderer(capsys: pytest.CaptureFixture[str]) -> None:
    # `test` is just `development`'s renderer with a higher default level;
    # set the level to DEBUG explicitly so the emit makes it through.
    configure_logging("test", log_level="DEBUG")
    _emit("ajolopy.test", "hello")
    captured = capsys.readouterr()
    out = captured.err or captured.out
    assert "hello" in out
    assert _ANSI_RE.search(out) is not None


def test_production_emits_one_valid_json_object_per_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")
    _emit("ajolopy.prod", "hello", k="v")
    captured = capsys.readouterr()
    out = captured.err or captured.out
    line = out.strip().splitlines()[-1]
    obj = json.loads(line)
    # Required keys per the spec.
    assert obj["event"] == "hello"
    assert obj["level"] == "info"
    assert obj["logger"] == "ajolopy.prod"
    assert obj["k"] == "v"
    # ISO-8601 UTC timestamp — datetime.fromisoformat handles offsets in 3.11+.
    parsed = datetime.fromisoformat(obj["timestamp"])
    assert parsed.tzinfo is not None


def test_production_exception_emits_traceback_string(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("production")
    log = get_logger("ajolopy.boom")
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        log.exception("boom")
    captured = capsys.readouterr()
    out = captured.err or captured.out
    line = out.strip().splitlines()[-1]
    obj = json.loads(line)
    assert obj["event"] == "boom"
    assert "exception" in obj
    assert "RuntimeError: kaboom" in obj["exception"]


def test_development_exception_pretty_prints_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("development")
    log = get_logger("ajolopy.boom")
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        log.exception("boom")
    captured = capsys.readouterr()
    out = captured.err or captured.out
    # ConsoleRenderer pretty-prints a Python traceback below the event line.
    assert "boom" in out
    assert "RuntimeError" in out
    assert "kaboom" in out


def test_stdlib_root_records_render_through_same_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stdlib `logging` records flow through the same ProcessorFormatter."""
    configure_logging("production")
    logging.getLogger("acme.thirdpkg").warning("from stdlib")
    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    obj = json.loads(line)
    assert obj["event"] == "from stdlib"
    assert obj["level"] == "warning"
    assert obj["logger"] == "acme.thirdpkg"
