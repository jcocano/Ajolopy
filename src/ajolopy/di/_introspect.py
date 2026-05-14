"""Read constructor dependencies via ``typing.get_type_hints``.

Kept in a private module so the public :class:`Container` surface
stays uncluttered. Failures here are translated into the framework's
typed error hierarchy so the messages stay actionable.
"""

import inspect
import typing
from typing import Any

from .errors import MissingAnnotationError


def introspect_dependencies(cls: type) -> dict[str, Any]:
    """Return ``{param_name: target_type}`` for every ``__init__`` parameter.

    Skips ``self`` and pydantic-settings' ``__pydantic_self__`` rename.
    Skips ``_``-prefixed parameters (pydantic-settings' private init
    kwargs like ``_case_sensitive``). Ignores ``*args`` / ``**kwargs``.
    Raises :class:`MissingAnnotationError` when any keyword parameter
    lacks a resolvable annotation, naming the parameter and the class
    so the error message points at the exact ``__init__`` to fix.
    """
    init = cls.__init__
    # ``object.__init__`` takes no explicit parameters; classes that
    # never define their own ``__init__`` simply have no deps.
    if init is object.__init__:
        return {}

    try:
        sig = inspect.signature(init)
    except (TypeError, ValueError) as exc:
        raise MissingAnnotationError(f"Cannot introspect {_qualname(cls)}.__init__: {exc}") from exc

    try:
        hints = typing.get_type_hints(init, include_extras=True)
    except (NameError, AttributeError, TypeError) as exc:
        raise MissingAnnotationError(
            f"{_qualname(cls)}.__init__ has an unresolvable type annotation: {exc}"
        ) from exc

    deps: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name in {"self", "__pydantic_self__"}:
            # ``self`` for normal methods; ``__pydantic_self__`` is
            # pydantic-settings' convention for the implicit first
            # parameter (lets users declare a field named "self").
            continue
        if name.startswith("_"):
            # Pydantic-settings's BaseSettings.__init__ declares private
            # configuration kwargs (``_case_sensitive``, ``_env_prefix``,
            # ...) all prefixed with a single underscore, every one
            # carrying a default. They are not DI dependencies; skip them
            # uniformly so any ``BaseConfig`` subclass resolves cleanly.
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            # *args / **kwargs are not injected — they stay unset.
            continue
        annotation = hints.get(name)
        if annotation is None:
            raise MissingAnnotationError(
                f"{_qualname(cls)}.__init__ parameter '{name}' has no type "
                f"annotation. The DI container injects by type hint only."
            )
        if getattr(annotation, "__metadata__", None) is not None:
            raise MissingAnnotationError(
                f"{_qualname(cls)}.__init__ parameter '{name}' uses "
                f"Annotated[{_qualname(_annotated_origin(annotation))}, ...]. "
                f"The DI container injects plain class annotations only; "
                f"markers like Annotated[..., Body()] belong to the HTTP "
                f"layer (AJ-15), not DI."
            )
        if not isinstance(annotation, type):
            raise MissingAnnotationError(
                f"{_qualname(cls)}.__init__ parameter '{name}' annotation "
                f"{annotation!r} does not resolve to a concrete class. The "
                f"DI container injects by class type only."
            )
        deps[name] = annotation
    return deps


def _qualname(obj: object) -> str:
    return getattr(obj, "__qualname__", repr(obj))


def _annotated_origin(annotation: Any) -> Any:
    """Return the inner type ``T`` of ``Annotated[T, ...]`` for error messages."""
    return getattr(annotation, "__origin__", annotation)
