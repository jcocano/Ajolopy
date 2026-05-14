"""``@Workflow`` class decorator.

Validates the workflow configuration at decoration time (so misconfigured
workflows fail at import / boot, not at first request) and injects
``run`` / ``stream`` instance methods that delegate to a single shared
:class:`WorkflowRuntime` bound to the class.

The decorator's contract:

- ``agents=`` must be a non-empty list of ``@Agent``-decorated classes.
- Either ``coordinator=`` (a model string) or an overridden
  ``async def route(self, message, context)`` must be present; never
  neither.
- ``coordinator=`` is resolved through the provider registry the same
  way :class:`ajolopy.agent.decorator.Agent` resolves its own
  ``model=`` kwarg; an unknown model raises
  :class:`WorkflowConfigError`.
- ``integrations=`` is reserved for ``@MCP`` (AJ-7) and rejected with
  :class:`WorkflowConfigError` when non-``None``.
- ``max_steps`` must be ``>= 1``.
- When both ``coordinator=`` and ``route()`` are present, ``route()``
  wins and the decorator logs an ``INFO``-level shadow notice.

The decorated class's type is preserved (the decorator returns
``type[T]``) so pyright continues to see the original public surface.
"""

import inspect
import logging
from typing import TYPE_CHECKING, Any

from .errors import WorkflowConfigError
from .runtime import WorkflowRuntime, is_agent_class

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from ajolopy.observability import Catalog

    from .events import WorkflowEvent

_DEFAULT_MAX_STEPS = 10

_LOGGER = logging.getLogger("ajolopy.workflow")


def Workflow[T](  # noqa: N802 — public surface mirrors the Brief's primitive name.
    *,
    agents: list[type[Any]],
    coordinator: str | None = None,
    integrations: list[type[Any]] | None = None,
    max_steps: int = _DEFAULT_MAX_STEPS,
    catalog: Catalog | None = None,
) -> Callable[[type[T]], type[T]]:
    """Class decorator factory — see ``specs/workflow.md`` for the full surface.

    Observability is always-on (matching the AJ-28 precedent for
    ``@Agent``); the previously-considered ``trace=True`` kwarg has been
    dropped on purpose. Backend selection happens at the SDK layer via
    standard OpenTelemetry env vars
    (``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``).
    """
    _validate_max_steps(max_steps)
    _validate_integrations(integrations)
    _validate_agents(agents)

    def _decorate(cls: type[T]) -> type[T]:
        route_override = _extract_route_override(cls)
        if coordinator is None and route_override is None:
            raise WorkflowConfigError(
                f"@Workflow on {cls.__name__!r} requires either a "
                f"coordinator= model string or an overridden async route("
                f"self, message, context) method. Neither was provided."
            )
        if coordinator is not None and route_override is not None:
            _LOGGER.info(
                "@Workflow on %r defines both coordinator=%r and route(); "
                "route() takes precedence and the coordinator model will "
                "not be invoked.",
                cls.__name__,
                coordinator,
            )

        # When ``route()`` overrides, the coordinator model is not used,
        # so we deliberately skip its provider resolution to avoid raising
        # a config error on an unused model.
        effective_coordinator = None if route_override is not None else coordinator
        runtime = WorkflowRuntime(
            workflow_cls=cls,
            agents=agents,
            coordinator=effective_coordinator,
            max_steps=max_steps,
            route_override=route_override,
            catalog=catalog,
        )

        async def run(self: T, message: str, **context: Any) -> str:
            return await runtime.run(self, message, **context)

        def stream(self: T, message: str, **context: Any) -> AsyncIterator[WorkflowEvent]:
            return runtime.stream(self, message, **context)

        cls._workflow_runtime = runtime  # type: ignore[attr-defined]
        cls.run = run  # type: ignore[attr-defined]
        cls.stream = stream  # type: ignore[attr-defined]
        return cls

    return _decorate


# ---------------------------------------------------------------------------
# decoration-time validators
# ---------------------------------------------------------------------------


def _validate_max_steps(max_steps: int) -> None:
    if not isinstance(max_steps, int) or isinstance(max_steps, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise WorkflowConfigError(f"@Workflow max_steps must be an int >= 1, got {max_steps!r}.")
    if max_steps < 1:
        raise WorkflowConfigError(f"@Workflow max_steps must be >= 1, got {max_steps}.")


def _validate_integrations(integrations: list[type[Any]] | None) -> None:
    if integrations is None:
        return
    raise WorkflowConfigError(
        "@Workflow integrations= is reserved for AJ-7 (@MCP) and not "
        "supported in v0.1. Track AJ-7 for shared-tool surface support."
    )


def _validate_agents(agents: list[type[Any]]) -> None:
    if not isinstance(agents, list):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise WorkflowConfigError(
            f"@Workflow agents= must be a list of @Agent-decorated classes, "
            f"got {type(agents).__name__}."
        )
    if not agents:
        raise WorkflowConfigError(
            "@Workflow agents= must contain at least one @Agent-decorated "
            "class. An empty list does not declare any specialists for the "
            "coordinator to delegate to."
        )
    seen: set[type[Any]] = set()
    for entry in agents:
        if not is_agent_class(entry):
            name = getattr(entry, "__name__", repr(entry))
            raise WorkflowConfigError(
                f"@Workflow agents= entry {name!r} is not @Agent-decorated. "
                f"Wrap the class with @Agent(...) before listing it in a "
                f"workflow's agents= list."
            )
        if entry in seen:
            raise WorkflowConfigError(
                f"@Workflow agents= contains duplicate entry {entry.__name__!r}. "
                f"Each agent class must appear at most once."
            )
        seen.add(entry)


def _extract_route_override(cls: type[Any]) -> Any:
    """Return ``cls.route`` when overridden as an async function, else None.

    A class defines a ``route()`` override when its own dict carries a
    callable ``route`` attribute that is an ``async def``. We inspect
    ``cls.__dict__`` rather than ``getattr(cls, "route", None)`` so we
    do not pick up inherited or framework-injected ``route`` attributes.
    """
    attr = cls.__dict__.get("route")
    if attr is None:
        return None
    if not inspect.iscoroutinefunction(attr):
        # The user attached something named ``route`` but not an async
        # function — treat it as "no override" so the framework falls
        # back to coordinator-only behavior. The decorator would still
        # require coordinator= in that case, surfacing the misuse via
        # the coordinator/route mutual-requirement check.
        return None
    return attr


__all__ = [
    "Workflow",
]
