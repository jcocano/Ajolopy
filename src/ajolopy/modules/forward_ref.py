"""``forwardRef(lambda: OtherModule)`` for circular module imports.

Python evaluates decorator arguments at class-definition time, so two
modules that import each other cannot both reference each other by name.
``forwardRef`` wraps the lookup in a thunk that the compiler invokes once
the full graph is being walked.

Naming is deliberately camelCase (mirroring NestJS) rather than the
Pythonic ``forward_ref`` — Python's own ``typing.ForwardRef`` would
otherwise collide with this symbol and confuse readers coming from the
TypeScript/NestJS world that the framework's wedge user lives in.
"""

from typing import TYPE_CHECKING

from .errors import UnresolvedForwardRefError

if TYPE_CHECKING:
    from collections.abc import Callable


class ForwardRef:
    """Sentinel wrapping a deferred module-class lookup.

    The compiler calls :meth:`resolve` once, when it reaches the import
    position in the graph walk. The returned class must be ``@Module``-
    decorated; otherwise the compiler raises
    :class:`UnresolvedForwardRefError`.
    """

    __slots__ = ("_thunk",)

    def __init__(self, thunk: Callable[[], type]) -> None:
        self._thunk = thunk

    def resolve(self) -> type:
        """Invoke the thunk and return the referenced module class.

        Raises
        ------
        UnresolvedForwardRefError
            If the thunk raises, returns a non-class object, returns a
            class without ``_ajolopy_module``, or returns another
            ``ForwardRef`` (chained forward references are rejected).
        """
        try:
            result = self._thunk()
        except Exception as exc:
            raise UnresolvedForwardRefError(
                f"forwardRef thunk raised {type(exc).__name__}: {exc}"
            ) from exc

        if isinstance(result, ForwardRef):
            raise UnresolvedForwardRefError(
                "forwardRef thunk returned another forwardRef; "
                "chained forward references are not supported"
            )

        if not isinstance(result, type):  # pyright: ignore[reportUnnecessaryIsInstance]
            # Defence-in-depth: callers can pass any thunk; we cannot
            # statically guarantee it returns a class.
            raise UnresolvedForwardRefError(
                f"forwardRef thunk returned {result!r}, expected a class"
            )

        if not hasattr(result, "_ajolopy_module"):
            raise UnresolvedForwardRefError(
                f"forwardRef thunk returned {result.__qualname__}, "
                f"which is not decorated with @Module"
            )

        return result


def forwardRef(thunk: Callable[[], type]) -> ForwardRef:  # noqa: N802 — Brief locks the helper name as ``forwardRef``
    """Wrap a deferred module-class lookup for use inside ``imports=``."""
    return ForwardRef(thunk)
