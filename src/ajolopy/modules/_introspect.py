"""Read constructor dependencies for the module visibility check.

The module compiler validates, **before** any container resolve runs,
that every provider's ``__init__`` only depends on tokens its module can
see. The check should be permissive about non-DI parameters: HTTP marker
annotations (``Annotated[T, Body|Query|Param|Header]``) belong to the
HTTP layer (AJ-15), and unannotated parameters are the DI container's
problem at resolve time — not the module compiler's.

This module therefore returns *only* the params that look like plain
class-typed DI deps; anything else is silently skipped.
"""

import inspect
import typing
from typing import Any


def collect_di_deps(cls: type) -> list[type]:
    """Return the list of class-typed ``__init__`` dependencies for ``cls``.

    Skips ``self``, ``*args`` / ``**kwargs``, parameters without a
    resolvable annotation, parameters annotated as ``Annotated[T, ...]``
    (HTTP markers), and parameters whose annotation does not resolve to
    a concrete class. The returned tokens are exactly what the DI
    container would try to ``resolve()`` for this class.

    The function is intentionally permissive — it does not raise on
    weird annotations. The container's own introspection (which *does*
    raise) runs at resolve time and produces the actionable error for
    the user.
    """
    init = cls.__init__
    if init is object.__init__:
        return []

    try:
        sig = inspect.signature(init)
    except TypeError, ValueError:
        # Cannot introspect — let the container handle at resolve time.
        return []

    try:
        hints = typing.get_type_hints(init, include_extras=True)
    except NameError, AttributeError, TypeError:
        # Unresolvable annotation — defer the error to runtime resolve,
        # the container surfaces it with a precise message.
        return []

    deps: list[type] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation: Any = hints.get(name)
        if annotation is None:
            continue
        # ``Annotated[T, marker]`` carries ``__metadata__``; HTTP markers
        # belong to AJ-15. Skip — the compiler should not gate visibility
        # on a non-DI parameter.
        if getattr(annotation, "__metadata__", None) is not None:
            continue
        if not isinstance(annotation, type):
            continue
        deps.append(annotation)
    return deps
