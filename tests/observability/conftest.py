"""Observability tests reuse the agent suite's fakes and share a TracerProvider.

The provider-registry isolation fixture comes from the repo-wide
``tests/conftest.py`` (autouse). The agent-runtime tests live in
``tests/agent/`` and define a flexible ``FakeProvider`` plus a registration
fixture for the ``anthropic`` provider key. Re-import the fixture here so
``pytest`` discovers it when the agent module is collected separately.

OTel's API treats ``trace.set_tracer_provider`` as set-once — the second
call is a silent no-op with a warning. The AJ-28 tracing tests need an
SDK ``TracerProvider`` with an ``InMemorySpanExporter`` attached; the
AJ-29 logging-trace tests need any valid SDK ``TracerProvider`` (their
correlation processor only consults the current span's context). We
collapse both needs into one shared provider configured here at conftest
import time so test ordering inside ``tests/observability/`` is
irrelevant.

The autouse ``reset_logging_state`` fixture undoes
:func:`configure_logging` between tests. The framework helper mutates
global stdlib handler state, so without this each test would inherit the
handlers attached by the previous one. The fixture runs before every test
in this directory; tests that never call ``configure_logging`` simply pay
the cost of resetting an already-clean state.
"""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ajolopy.observability.logging import _reset_for_tests
from tests.agent.conftest import (
    fake_provider_factory,
    register_fake_anthropic,
)

# Module-level singleton so test files can import the exporter and clear
# it per-test. Initialised lazily through ``_ensure_session_provider``.
SESSION_EXPORTER: InMemorySpanExporter = InMemorySpanExporter()
_session_state: dict[str, bool] = {"installed": False}


def ensure_session_provider() -> InMemorySpanExporter:
    """Install the shared SDK ``TracerProvider`` once per process."""
    if not _session_state["installed"]:
        # If something else (e.g. a stale process state) already installed a
        # TracerProvider, fall back to using whatever is there — the api
        # blocks overrides anyway. Only install when the current provider
        # is *not* an SDK ``TracerProvider``.
        current = trace.get_tracer_provider()
        if not isinstance(current, TracerProvider):
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(SESSION_EXPORTER))
            trace.set_tracer_provider(provider)
        _session_state["installed"] = True
    return SESSION_EXPORTER


# Install eagerly at conftest import time so every test in
# ``tests/observability/`` sees the same provider regardless of collection
# order. The AJ-28 tracing tests reuse the exporter via their local
# ``tracer_provider`` fixture; the AJ-29 logging-trace tests only need the
# provider to exist.
ensure_session_provider()


@pytest.fixture(autouse=True)
def reset_logging_state() -> Iterator[None]:
    """Reset the framework's logging pipeline around each test.

    ``configure_logging`` mutates global stdlib handler state; without this
    fixture each test would inherit the previous test's handlers, threshold
    and renderer. Calling ``_reset_for_tests`` is a no-op when no pipeline
    is installed, so applying this autouse across the directory is safe
    for tests that do not touch logging.
    """
    _reset_for_tests()
    try:
        yield
    finally:
        _reset_for_tests()


__all__ = [
    "SESSION_EXPORTER",
    "ensure_session_provider",
    "fake_provider_factory",
    "register_fake_anthropic",
    "reset_logging_state",
]
