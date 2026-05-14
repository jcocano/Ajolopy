"""``Guard`` ABC, callable adapter, and ``GuardLike`` normalisation.

Three forms are accepted by ``@UseGuards``:

1. A :class:`Guard` subclass — instantiated with no arguments at
   decoration time. ``__init__`` requiring arguments raises
   :class:`UseGuardsConfigError` with a hint to pass a pre-built
   instance.
2. A :class:`Guard` instance — stored verbatim.
3. A plain callable ``(request) -> bool | Awaitable[bool]`` — wrapped
   in :class:`_CallableGuard` so the request-time interface stays a
   single :meth:`Guard.can_activate` method.

The normalisation is centralised in :func:`_normalize_guard`. The
decorator and the cross-cut mount layers never construct
:class:`Guard` instances directly — they always route through this
helper so error messages, validation, and adapter wrapping stay
consistent.
"""

import abc
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, cast, override

from starlette.requests import Request

from .errors import UseGuardsConfigError


class Guard(abc.ABC):
    """Base class for request-level gates.

    Subclasses MUST implement :meth:`can_activate` as ``async def``.
    A synchronous override is rejected at decoration time so a slow
    sync guard cannot accidentally block the event loop.

    Returning ``True`` lets the request continue to the next guard
    (or the handler if this was the last guard). Returning ``False``
    or raising :class:`GuardUnauthorizedError` /
    :class:`GuardForbiddenError` short-circuits the request and the
    handler body never runs.
    """

    @abc.abstractmethod
    async def can_activate(self, request: Request) -> bool:
        """Decide whether ``request`` may continue to the handler."""


# NOTE: classic alias rather than PEP 695 ``type GuardLike = ...``.
# CodeQL's ``Explicit export is not defined`` check does not recognise
# the new ``type`` statement, so re-exporting ``GuardLike`` from
# ``__all__`` triggers a false-positive alert. Behaviour is identical;
# pyright accepts both shapes.
GuardLike = Guard | type[Guard] | Callable[[Request], Awaitable[bool] | bool]
"""Acceptable forms for each argument to ``@UseGuards``.

Normalised into a :class:`Guard` instance by :func:`_normalize_guard`.
"""


class _CallableGuard(Guard):
    """Adapter that exposes a plain callable as a :class:`Guard`.

    The wrapped callable may be ``async def`` or a regular ``def``. The
    adapter awaits the result when it is awaitable. Synchronous
    callables run directly on the event loop — the adapter does NOT
    dispatch them to ``asyncio.to_thread``, so they must NOT perform
    blocking I/O. The decorator-time check verifies the callable is
    callable; runtime errors raised by the callable bubble through the
    normal :class:`GuardError` mapping.
    """

    __slots__ = ("_fn", "_qualname")

    def __init__(self, fn: Callable[[Request], Awaitable[bool] | bool]) -> None:
        self._fn = fn
        self._qualname = getattr(fn, "__qualname__", repr(fn))

    @override
    async def can_activate(self, request: Request) -> bool:
        result = self._fn(request)
        if inspect.isawaitable(result):
            awaited: Any = await result
            return bool(awaited)
        return bool(result)

    @override
    def __repr__(self) -> str:
        return f"_CallableGuard({self._qualname})"


_ACCEPTED_FORMS = (
    "Accepted forms: a Guard subclass (zero-arg __init__), a Guard "
    "instance, or a callable (request) -> bool | Awaitable[bool]."
)


def _normalize_guard(arg: object) -> Guard:
    """Coerce ``arg`` into a :class:`Guard` instance.

    Raises :class:`UseGuardsConfigError` for any form that does not
    match one of the three accepted shapes. The error message always
    lists the accepted forms so users can recover without reading the
    spec.
    """
    if isinstance(arg, Guard):
        return arg
    if isinstance(arg, type):
        if not issubclass(arg, Guard):
            raise UseGuardsConfigError(
                f"@UseGuards received class {arg.__qualname__!r} that is "
                f"not a Guard subclass. {_ACCEPTED_FORMS}"
            )
        _require_async_can_activate(arg)
        try:
            return arg()
        except TypeError as exc:
            raise UseGuardsConfigError(
                f"@UseGuards could not instantiate {arg.__qualname__}() with "
                f"zero arguments ({exc}). Pass a pre-built instance — "
                f"@UseGuards({arg.__name__}(...))."
            ) from exc
    if callable(arg):
        # ``arg`` was narrowed to ``object & Callable[..., object]``. The
        # adapter awaits / coerces the return value at request time, so
        # any signature shape that ``callable()`` accepts is safe; the
        # cast satisfies pyright's strict argument-type check.
        return _CallableGuard(cast("Callable[[Request], Awaitable[bool] | bool]", arg))
    raise UseGuardsConfigError(
        f"@UseGuards received {arg!r} ({type(arg).__name__}). {_ACCEPTED_FORMS}"
    )


def _require_async_can_activate(cls: type[Guard]) -> None:
    """Reject a :class:`Guard` subclass whose ``can_activate`` is sync.

    A synchronous ``can_activate`` on the framework's request-level gate
    would block the event loop — by contract every guard runs on the
    request hot path. The check inspects the resolved method (so MRO
    works as expected) and raises a configuration error pointing the
    user at ``async def`` rather than silently degrading behaviour.
    """
    method = cls.can_activate
    if not inspect.iscoroutinefunction(method):
        raise UseGuardsConfigError(
            f"@UseGuards: Guard subclass {cls.__qualname__} defines "
            f"can_activate as a synchronous method. Declare it as "
            f"'async def can_activate(self, request): ...' so the "
            f"event loop is not blocked."
        )


__all__ = [
    "Guard",
    "GuardLike",
    "_CallableGuard",
    "_normalize_guard",
]
