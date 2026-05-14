"""Structlog pipeline setup: JSON in prod, ConsoleRenderer in dev/test.

The framework wires :func:`configure_logging` from
``AjolopyFactory.create()`` so every Ajolopy app — and every third-party
library running in the same process — emits through a single configured
pipeline. The pipeline:

* picks the renderer from ``env`` (``development`` / ``test`` get
  :class:`structlog.dev.ConsoleRenderer`; ``production`` gets
  :class:`structlog.processors.JSONRenderer`),
* stamps every event with an ISO-8601 UTC timestamp, the level name, the
  logger name, and the contextvars merged via
  :func:`structlog.contextvars.merge_contextvars`,
* injects ``trace_id`` / ``span_id`` from the current OpenTelemetry span
  (via ``opentelemetry-api`` only — never the SDK, so the import is free
  when ``ajolopy[otel]`` is not installed),
* captures the stdlib :mod:`logging` root logger so third-party emitters
  (anthropic, openai, httpx, uvicorn, starlette, google-genai) inherit
  the same renderer + trace fields + threshold without any user setup.

The threshold resolution is: explicit ``log_level`` argument > ``LOG_LEVEL``
env var > env-derived default (``development`` → ``DEBUG``,
``production`` → ``INFO``, ``test`` → ``WARNING``). Invalid ``LOG_LEVEL``
values raise :class:`ValueError` before any handler is installed.

The function is idempotent — a module-level flag short-circuits second
calls. Tests reset the flag via :func:`_reset_for_tests`, which also
removes the installed stdlib handler so each test starts clean.

The pipeline can be extended without re-config via the ``add_processors``
hook; processors run before the renderer and can mutate the event dict
(e.g. to inject a ``request_id`` from contextvars). v0.2 middleware items
build on this seam without forcing a structlog re-config.
"""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from opentelemetry import trace
from structlog.contextvars import merge_contextvars
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer, format_exc_info
from structlog.stdlib import BoundLogger, LoggerFactory, ProcessorFormatter

# ``Processor`` is referenced from the public signature of
# :func:`configure_logging` (via ``list[Processor]``). The annotation must
# resolve at runtime for tools that introspect signatures — notably
# :func:`inspect.signature` (and therefore ``unittest.mock.patch`` with
# ``autospec=True``) — so we import the alias eagerly rather than under
# ``TYPE_CHECKING``. ``EventDict`` is private to this module.
from structlog.typing import EventDict, Processor  # noqa: TC002 — see comment above

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_LOGGER_ROOT_NAME = "ajolopy"

_LEVEL_BY_ENV: dict[str, int] = {
    "development": logging.DEBUG,
    "production": logging.INFO,
    "test": logging.WARNING,
}


# Module-level state is held on a single mutable instance so static analysers
# (CodeQL specifically) can see the cross-function read/write pattern. Bare
# module-level globals trigger CodeQL's "unused global variable" rule because
# its intra-procedural pass cannot trace name rebindings across functions.
@dataclass(slots=True)
class _State:
    """Mutable module state for the structlog pipeline install.

    ``configured`` — short-circuits a second :func:`configure_logging` call so
    a second invocation does not stack handlers.

    ``installed_handler`` — the :class:`logging.Handler` we attach to the
    stdlib root logger. Kept here so :func:`_reset_for_tests` can find and
    detach it without nuking handlers the user (or pytest's ``caplog``) put
    on their own.
    """

    configured: bool = False
    installed_handler: logging.Handler | None = None


_state = _State()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    env: str,
    log_level: str | None = None,
    *,
    capture_stdlib: bool = True,
    add_processors: list[Processor] | None = None,
) -> None:
    """Install the framework-wide structlog + stdlib logging pipeline.

    Parameters
    ----------
    env:
        Application environment. ``"development"`` and ``"test"`` produce
        a :class:`structlog.dev.ConsoleRenderer` with colors; ``"production"``
        produces a :class:`structlog.processors.JSONRenderer`. Any unknown
        value falls back to the development default — logging must never
        block startup.
    log_level:
        Optional explicit threshold (case-insensitive name: ``"DEBUG"``,
        ``"info"``, ...). Overrides both the ``LOG_LEVEL`` env var and the
        env-derived default.
    capture_stdlib:
        When ``True`` (default) attach a :class:`logging.StreamHandler` to
        the stdlib root logger whose formatter is
        :class:`structlog.stdlib.ProcessorFormatter`. This routes every
        ``logging.getLogger(...)`` call through the same renderer + trace
        fields. Set to ``False`` if the host application already manages
        the stdlib root logger and only wants ``structlog``-native logs to
        flow through the framework pipeline.
    add_processors:
        Optional list of additional :class:`structlog.typing.Processor`
        callables. They run **before** the renderer (and after the
        framework's built-in processors), in the order given. The hook is
        the documented seam for per-event enrichment such as
        ``request_id`` / ``tenant_id`` / ``user_id`` middleware. Passing
        ``None`` (the default) leaves the pipeline unchanged.

    Raises
    ------
    ValueError
        ``log_level`` or the ``LOG_LEVEL`` env var is not a recognised
        Python logging level name. Raised before any handler is installed.

    Notes
    -----
    The call is idempotent: a private module-level flag short-circuits the
    second invocation. Tests can opt back into a clean state via
    :func:`_reset_for_tests`.
    """
    if _state.configured:
        return

    # Resolve the threshold *first*, before mutating any global state. A
    # bad LOG_LEVEL must surface as ValueError rather than half-install the
    # pipeline.
    level = _resolve_level(env, log_level)

    renderer = _renderer_for_env(env)

    # Processor pipeline applied to both structlog-native events and stdlib
    # records foreign-routed through ProcessorFormatter. The order is
    # load-bearing: timestamp/level/logger/contextvars stamp the event,
    # trace correlation reads the *current* span (so it must run after the
    # event is bound to its emission context), then any user-supplied
    # extension processors. The renderer itself runs at the
    # ProcessorFormatter stage so structlog-native events and stdlib
    # records share the same final rendering pass.
    pre_chain: list[Processor] = [
        _add_iso_timestamp,
        structlog.stdlib.add_log_level,
        _add_logger_name,
        merge_contextvars,
        _trace_correlation_processor,
    ]
    if add_processors:
        pre_chain.extend(add_processors)

    if capture_stdlib:
        # Hand the event off to the stdlib logger; ProcessorFormatter
        # finishes the job (renderer + exception formatting) so structlog-
        # native logs and stdlib records share one output stream and one
        # renderer instance — no double-printing.
        structlog_processors: list[Processor] = [
            structlog.stdlib.filter_by_level,
            *pre_chain,
            ProcessorFormatter.wrap_for_formatter,
        ]
    else:
        # No stdlib bridge: structlog renders directly to its own stream.
        # `filter_by_level` still consults `logging.getLogger(name)` so the
        # configured threshold applies via the named ajolopy logger.
        structlog_processors = [
            structlog.stdlib.filter_by_level,
            *pre_chain,
            format_exc_info,
            renderer,
        ]

    structlog.configure(
        processors=structlog_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if capture_stdlib:
        _state.installed_handler = _install_stdlib_handler(
            level=level,
            foreign_pre_chain=pre_chain,
            renderer=renderer,
        )
    else:
        # Even without stdlib capture, ensure the named structlog logger
        # respects the resolved threshold — `filter_by_level` consults
        # `logging.getLogger(...).getEffectiveLevel()`.
        logging.getLogger(_LOGGER_ROOT_NAME).setLevel(level)

    _state.configured = True


def get_logger(name: str | None = None) -> BoundLogger:
    """Return a :class:`structlog.stdlib.BoundLogger` bound to ``name``.

    Convention for module-level usage::

        _LOGGER = get_logger(__name__)

    Calling ``get_logger()`` with no argument returns the root ``ajolopy``
    logger — convenient for REPL sessions where importing ``__name__`` is
    noise. Production code should always pass ``__name__``.

    The function does not configure the pipeline; the caller (typically
    :class:`AjolopyFactory`) is responsible for invoking
    :func:`configure_logging` first. Calling ``get_logger`` before
    ``configure_logging`` still returns a working logger that emits via
    structlog's default pipeline.
    """
    effective_name = name if name else _LOGGER_ROOT_NAME
    return cast("BoundLogger", structlog.get_logger(effective_name))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_level(env: str, log_level: str | None) -> int:
    """Resolve the effective stdlib level int from inputs.

    Order:

    1. Explicit ``log_level`` argument (case-insensitive name).
    2. ``LOG_LEVEL`` env var (case-insensitive name).
    3. Env-derived default (``development`` → DEBUG, ``production`` → INFO,
       ``test`` → WARNING).

    Raises :class:`ValueError` for unrecognised level names. The error
    surfaces before any handler is installed so callers can recover.
    """
    if log_level is not None:
        return _parse_level_name(log_level, source="log_level")

    env_var = os.environ.get("LOG_LEVEL")
    if env_var:
        return _parse_level_name(env_var, source="LOG_LEVEL")

    return _LEVEL_BY_ENV.get(env, logging.DEBUG)


def _parse_level_name(raw: str, *, source: str) -> int:
    """Convert a case-insensitive Python level name to its int value."""
    normalised = raw.strip().upper()
    # logging.getLevelNamesMapping is the canonical inverse of
    # logging.getLevelName; it returns {"DEBUG": 10, "INFO": 20, ...}.
    mapping = logging.getLevelNamesMapping()
    if normalised not in mapping:
        raise ValueError(
            f"Unrecognised log level for {source}={raw!r}. "
            f"Accepted (case-insensitive): {sorted(mapping)}."
        )
    return mapping[normalised]


def _renderer_for_env(env: str) -> Processor:
    """Pick the final renderer based on the environment.

    ``production`` uses :class:`structlog.processors.JSONRenderer`. Every
    other value (``development``, ``test``, anything unrecognised) gets
    :class:`structlog.dev.ConsoleRenderer` with colors enabled. Unknown
    envs default to console because a developer running the framework with
    a typo'd env should still see readable output, not a wall of JSON.
    """
    if env == "production":
        return JSONRenderer()
    return ConsoleRenderer(colors=True)


def _add_iso_timestamp(_logger: object, _name: str, event_dict: EventDict) -> EventDict:
    """Stamp the event with an ISO-8601 UTC ``timestamp`` field.

    Manually formatted (rather than ``TimeStamper(fmt="iso")``) so the
    output is deterministic across structlog versions and easy to parse
    with :func:`datetime.fromisoformat`.
    """
    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict


def _add_logger_name(logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """Stamp the event with the bound logger's name.

    structlog ships ``add_logger_name``, but it only triggers when the
    logger has a ``name`` attribute. For stdlib records routed via
    ``ProcessorFormatter`` the name arrives under the ``_record`` key
    instead, so we fall back to that path here.
    """
    name = getattr(logger, "name", None)
    if not name:
        record = event_dict.get("_record")
        if isinstance(record, logging.LogRecord):
            name = record.name
    if name:
        event_dict["logger"] = name
    return event_dict


def _trace_correlation_processor(
    _logger: object, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Inject ``trace_id`` / ``span_id`` from the current OTel span.

    Uses :func:`opentelemetry.trace.get_current_span` from
    ``opentelemetry-api`` only. When the span context is invalid (the
    no-op span returned without an SDK / outside any started span) the
    keys are omitted — log aggregators key off field presence, not on
    empty strings.
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return event_dict
    # OTel hex helpers zero-pad to the canonical 32/16 char widths.
    event_dict["trace_id"] = trace.format_trace_id(ctx.trace_id)
    event_dict["span_id"] = trace.format_span_id(ctx.span_id)
    return event_dict


def _install_stdlib_handler(
    *,
    level: int,
    foreign_pre_chain: list[Processor],
    renderer: Processor,
) -> logging.Handler:
    """Attach a single :class:`StreamHandler` to the stdlib root logger.

    The handler's formatter is :class:`structlog.stdlib.ProcessorFormatter`
    configured with the same ``foreign_pre_chain`` we use for structlog-
    native events, so every ``logging.getLogger(...)`` call (including
    third-party libraries like ``anthropic._client`` or ``httpx``) flows
    through the same renderer + trace fields + threshold.

    Sets the level on:

    * the attached handler,
    * the stdlib root logger,
    * the named ``ajolopy`` logger — so ``filter_by_level`` checks against
      the configured threshold rather than the default WARNING.

    Returns the handler so :func:`_reset_for_tests` can detach exactly the
    one we added (without nuking handlers installed by other code).
    """
    formatter = ProcessorFormatter(
        foreign_pre_chain=foreign_pre_chain,
        processors=[
            # remove_processors_meta strips structlog's internal book-keeping
            # keys (`_record`, `_from_structlog`) before the renderer sees
            # the event dict.
            ProcessorFormatter.remove_processors_meta,
            format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(level)

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)

    # Named logger threshold — structlog's filter_by_level looks this up.
    logging.getLogger(_LOGGER_ROOT_NAME).setLevel(level)

    return handler


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _reset_for_tests() -> None:  # pyright: ignore[reportUnusedFunction]  # consumed only by tests/observability fixtures; intentional private API per spec
    """Undo :func:`configure_logging` so the next call re-installs cleanly.

    Detaches the stdlib handler we installed, resets structlog to its
    library defaults, and clears the module-level configured flag.
    Intended for use from test fixtures only — never call from production
    code.
    """
    if _state.installed_handler is not None:
        logging.getLogger().removeHandler(_state.installed_handler)
        _state.installed_handler = None

    # structlog has no public "reset" helper, so call the same primitive
    # `structlog.configure_once` uses internally and rebuild the default
    # processor chain. `reset_defaults` is part of the public test API.
    structlog.reset_defaults()

    _state.configured = False


__all__ = [
    "configure_logging",
    "get_logger",
]
