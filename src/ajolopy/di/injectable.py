"""``@Injectable`` — declarative scope marker for DI providers.

Thin decorator: stamps ``__ajolopy_scope__`` on the target class so the
:func:`ajolopy.modules.compile_module` walk registers the class with
the right :class:`Container` scope. Both bare (``@Injectable``) and
parameterised (``@Injectable(scope="...")``) forms are supported via an
overloaded signature.

There is no runtime container interaction here; the decorator is a
single-attribute stamp. Validation of scope values happens at
decoration time so typos surface before the first compile.
"""

from typing import TYPE_CHECKING, cast, overload

from .errors import InjectableConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .container import Scope

_LEGAL_SCOPES: frozenset[str] = frozenset({"singleton", "request", "transient"})


def _stamp(cls: type, scope: Scope) -> type:
    """Apply the ``__ajolopy_scope__`` stamp to ``cls`` and return it.

    ``__ajolopy_scope__`` is intentionally *not* inherited: a subclass
    of a decorated class must be re-decorated to count. We detect
    re-decoration by checking the class's own ``__dict__`` (not
    ``getattr``, which would walk the MRO and reject a legitimate
    ``class Child(Parent): ...`` where ``Parent`` is already decorated).
    """
    if "__ajolopy_scope__" in cls.__dict__:
        raise InjectableConfigError(
            f"@Injectable re-applied to {cls.__qualname__}; the class is "
            f"already decorated as injectable."
        )
    cls.__ajolopy_scope__ = scope
    return cls


def _validate_scope(scope: object) -> Scope:
    """Reject scope values outside the three legal literals.

    The :class:`Scope` literal narrows the type for static checkers,
    but at runtime users can pass anything — bare strings, ``None``,
    integers. We reject everything that isn't one of the three legal
    strings and name the offender in the message.
    """
    if not isinstance(scope, str) or scope not in _LEGAL_SCOPES:
        raise InjectableConfigError(
            f"@Injectable(scope={scope!r}) is not a legal scope. "
            f"Legal scopes: {sorted(_LEGAL_SCOPES)}."
        )
    # The membership check above guarantees ``scope`` is one of the
    # three literal strings; narrow it for static checkers.
    return cast("Scope", scope)


@overload
def Injectable(cls: type, /) -> type: ...  # bare: ``@Injectable``


@overload
def Injectable(
    *, scope: Scope = "singleton"
) -> Callable[[type], type]: ...  # parameterised: ``@Injectable(scope=...)``


def Injectable(  # noqa: N802 — Brief locks the decorator name as ``Injectable``
    cls: type | None = None,
    *,
    scope: Scope = "singleton",
) -> type | Callable[[type], type]:
    """Mark a class as a DI provider with the given scope.

    Both forms are supported and produce the same result — a single
    ``__ajolopy_scope__`` attribute stamped on the class:

    .. code-block:: python

        @Injectable
        class Logger: ...


        @Injectable(scope="request")
        class RequestContext: ...

    The bare form defaults to ``"singleton"`` scope, matching the
    container's default. ``@Injectable()`` (parens with no kwargs)
    is equivalent to the bare form.

    The class itself is returned unchanged — ``@Injectable`` does not
    wrap, copy, or instrument the class beyond stamping the scope.
    Registration with a :class:`Container` happens when the class is
    listed in some ``@Module(providers=[...])``; ``@Injectable`` alone
    does not register anything.

    Raises
    ------
    InjectableConfigError
        ``scope`` is not one of ``"singleton"`` / ``"request"`` /
        ``"transient"``, or the same class has already been decorated
        with ``@Injectable``.
    """
    validated_scope = _validate_scope(scope)
    if cls is None:
        # Parameterised form: ``@Injectable(scope=...)`` returned a
        # decorator that the caller will apply to the class next.
        def decorator(inner_cls: type) -> type:
            return _stamp(inner_cls, validated_scope)

        return decorator
    # Bare form: ``@Injectable`` was applied directly to the class.
    return _stamp(cls, validated_scope)
