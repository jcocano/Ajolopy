"""``@UseGuards`` class- and method-level decorator.

Stamps ``_ajolopy_guards`` — a tuple of normalised :class:`Guard`
instances — on the decorated target. The decorator does no request
processing; the mount layers (``ajolopy.routes.mount_routes`` and
``ajolopy.stream.mount_streams``) read the metadata at mount time and
wrap the route endpoint via :func:`apply_guard_chain`.

Two ``@UseGuards`` decorators on the same target concatenate. In
Python's decorator semantics, the decorator closest to the target runs
FIRST — so::

    @UseGuards(A)
    @UseGuards(B)
    class Foo: ...

stamps ``[B]`` first (inner decorator), then the outer decorator
extends to ``[B, A]``. The framework normalises to the declaration
order the user sees top-to-bottom: ``[A, B]`` — outer decorator wins
the leading slot.
"""

from typing import TYPE_CHECKING, TypeVar

from .base import Guard, GuardLike, _normalize_guard
from .errors import UseGuardsConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

# ``_ajolopy_guards`` is the public attribute consumed by the mount
# layers. Exposed at module level so ``mount_routes`` / ``mount_streams``
# can reference the constant instead of repeating the literal.
GUARDS_META_ATTR: str = "_ajolopy_guards"

# ``T`` is module-level (not PEP 695) because the decorator body runs
# eager validation that may raise BEFORE the inner ``_decorate``. CodeQL
# false-positives PEP 695 type parameters in that shape (see
# ``ajolopy/mcp/decorator.py`` for the same workaround).
T = TypeVar("T")


def UseGuards(*guards: GuardLike) -> Callable[[T], T]:  # noqa: N802 — public decorator name
    """Stamp the decorated class or method with a guard chain.

    Every positional argument is normalised into a :class:`Guard`
    instance at decoration time (zero-arg subclasses are instantiated,
    instances are stored verbatim, callables are wrapped in
    ``_CallableGuard``). Anything else raises
    :class:`UseGuardsConfigError` immediately so misuse never reaches
    the request hot path.

    The decorator returns the target unchanged beyond the
    ``_ajolopy_guards`` attribute stamp.
    """
    if not guards:
        raise UseGuardsConfigError(
            "@UseGuards requires at least one guard argument. Pass a "
            "Guard subclass, a Guard instance, or a (request) -> bool "
            "callable."
        )

    new_guards: tuple[Guard, ...] = tuple(_normalize_guard(g) for g in guards)

    def _decorate(target: T) -> T:
        if not _is_decoration_target(target):
            raise UseGuardsConfigError(
                f"@UseGuards must decorate a class or a function, got "
                f"{type(target).__name__}: {target!r}."
            )
        existing = _read_existing_guards(target)
        combined = existing + new_guards
        # ``setattr`` on a function or class is unconditional; on a
        # method object Python would refuse, but ``_is_decoration_target``
        # already filtered those out.
        setattr(target, GUARDS_META_ATTR, combined)  # pyright: ignore[reportAttributeAccessIssue]
        return target

    return _decorate


def _is_decoration_target(target: object) -> bool:
    """Return ``True`` if ``target`` is a class or a (sync/async) function.

    Bound methods, lambdas, builtins, and arbitrary callables are
    rejected — the decorator is only meaningful on declaration-time
    surfaces. Lambdas are not rejected outright (they pass the function
    check); a lambda is a legitimate target if the user really wants it.
    """
    if isinstance(target, type):
        return True
    # Function-typed objects: regular ``def`` and ``async def`` both
    # satisfy ``inspect.isfunction``. Bound methods do NOT.
    import inspect as _inspect

    return _inspect.isfunction(target)


def _read_existing_guards(target: object) -> tuple[Guard, ...]:
    """Return the guards already stamped on ``target``, if any.

    A previous ``@UseGuards`` on the same target extends rather than
    replaces; this matches the hierarchical-concatenation contract in
    the spec. ``target.__dict__`` is consulted directly for classes so
    inherited stamps do not bleed through (subclasses must redeclare).
    """
    if isinstance(target, type):
        own = target.__dict__.get(GUARDS_META_ATTR, ())
    else:
        own = getattr(target, GUARDS_META_ATTR, ())
    if isinstance(own, tuple):
        return own
    return ()


def get_guard_chain(obj: object) -> tuple[Guard, ...]:
    """Return the guard chain stamped on ``obj``, or ``()``.

    Mirrors :func:`ajolopy.routes.decorator.get_route_metadata`: works
    for unbound functions, classes, and bound methods (whose underlying
    function carries the metadata via ``__func__``).
    """
    chain = getattr(obj, GUARDS_META_ATTR, None)
    if chain is None:
        func = getattr(obj, "__func__", None)
        if func is not None:
            chain = getattr(func, GUARDS_META_ATTR, None)
    if isinstance(chain, tuple):
        return chain
    return ()


__all__ = [
    "GUARDS_META_ATTR",
    "UseGuards",
    "get_guard_chain",
]
