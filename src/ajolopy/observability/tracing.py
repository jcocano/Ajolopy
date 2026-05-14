"""OpenTelemetry tracer accessor and optional SDK auto-installation.

The framework never imports ``opentelemetry.sdk`` at module load time. The api
(``opentelemetry-api``) is enough to create spans — without an SDK installed,
those spans are cheap no-ops emitted by the api's ``ProxyTracerProvider``.

When the user installs the ``ajolopy[otel]`` extra, the SDK becomes available
and :func:`setup_tracing_from_env` swaps the proxy out for a real
``TracerProvider`` configured from standard OTel environment variables
(``OTEL_SERVICE_NAME``, ``OTEL_EXPORTER_OTLP_ENDPOINT``,
``OTEL_RESOURCE_ATTRIBUTES``, …). Any provider the user installed manually
before bootstrap wins — we never overwrite a real provider.

Content capture (recording the prompt and completion text as span attributes)
is **off by default**. Users opt in via the official OTel GenAI environment
variable ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true``. The
default exists because LLM prompts and completions routinely contain PII,
secrets, and customer data; exporting that to an external observability
backend without the user's explicit consent would be a footgun.
"""

import os
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

_TRACER_NAME = "ajolopy"
_CONTENT_CAPTURE_ENV = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"


def get_tracer(name: str = _TRACER_NAME) -> Tracer:
    """Return the framework's shared tracer.

    Always succeeds — without an SDK installed, this returns the api's proxy
    tracer whose spans are no-ops. Concrete provider classes do not call this
    function; spans are opened by ``AgentRuntime`` and other framework
    primitives, so the tracer namespace stays under Ajolopy's control.
    """
    return trace.get_tracer(name)


def is_content_capture_enabled() -> bool:
    """Whether to record prompt and completion text on ``chat`` spans.

    Reads the official OTel GenAI env var
    ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT``. Truthy values:
    ``true``, ``1``, ``yes``, ``on`` (case-insensitive). Anything else — and
    especially absence — disables content capture.
    """
    raw = os.environ.get(_CONTENT_CAPTURE_ENV, "")
    return raw.strip().lower() in {"true", "1", "yes", "on"}


_INTENT_ENV_VARS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)


def setup_tracing_from_env() -> bool:
    """Install a real ``TracerProvider`` if the SDK extra is available.

    Returns ``True`` when a new provider was installed by this call, ``False``
    otherwise. The function is idempotent — a second call is a no-op once a
    real provider is in place.

    The function never raises. If the SDK extra is not installed (``ImportError``
    on ``opentelemetry.sdk.*``) the function returns ``False`` and leaves the
    proxy provider in place; spans emitted by the framework stay no-ops.

    Behaviour:

    1. If neither ``OTEL_EXPORTER_OTLP_ENDPOINT`` nor
       ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` is set → return ``False``. Auto-
       configuring an exporter without a destination would send spans into a
       black hole and fill the logs with retry timeouts. Users who want
       tracing set one of these vars; users who do not stay on the cheap api
       no-ops.
    2. If ``opentelemetry.sdk.trace.TracerProvider`` cannot be imported →
       return ``False`` (the ``ajolopy[otel]`` extra is not installed).
    3. If ``trace.get_tracer_provider()`` already returns a real
       ``TracerProvider`` (anything other than the api's proxy) → return
       ``False``. The user wired their own pipeline; we do not stomp it.
    4. Otherwise install a fresh ``TracerProvider`` with a
       ``BatchSpanProcessor`` + OTLP HTTP exporter. ``Resource`` is built from
       ``OTEL_SERVICE_NAME`` (default ``"ajolopy"``) and any extra resource
       attributes from ``OTEL_RESOURCE_ATTRIBUTES`` / ``OTEL_RESOURCE_*``.
    5. Call ``trace.set_tracer_provider(...)`` and return ``True``.
    """
    if not any(os.environ.get(name) for name in _INTENT_ENV_VARS):
        return False

    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        # The ajolopy[otel] extra is not installed — keep spans as no-ops.
        return False

    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        # A real provider is already installed (user-configured or a prior
        # setup_tracing_from_env() call). Do not overwrite.
        return False

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:
        # SDK present but exporter missing — install a TracerProvider without
        # an exporter so user-attached processors still receive spans, but do
        # not block bootstrap.
        provider = TracerProvider(resource=_build_resource())
        trace.set_tracer_provider(provider)
        return True

    provider = TracerProvider(resource=_build_resource())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return True


def _build_resource() -> Any:
    """Build an OTel ``Resource`` from standard env vars.

    Reads ``OTEL_SERVICE_NAME`` (default ``"ajolopy"``) and merges anything
    the SDK auto-detects from ``OTEL_RESOURCE_ATTRIBUTES``. The return type
    is left as ``Any`` because ``Resource`` only exists when the SDK extra
    is installed — typing it precisely would force callers (and pyright) to
    import an optional dependency.
    """
    from opentelemetry.sdk.resources import (  # local import for the same reason
        SERVICE_NAME,
        Resource,
    )

    service_name = os.environ.get("OTEL_SERVICE_NAME") or "ajolopy"
    # ``Resource.create`` already merges OTEL_RESOURCE_ATTRIBUTES from env,
    # so this single dict + create is enough.
    return Resource.create({SERVICE_NAME: service_name})


__all__ = [
    "get_tracer",
    "is_content_capture_enabled",
    "setup_tracing_from_env",
]
