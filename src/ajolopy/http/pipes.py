"""Per-parameter value coercion / validation.

A :class:`Pipe` receives the raw value extracted from the request (via
:func:`ajolopy.http.introspect.extract_raw`) and returns the value the
handler will actually see. The shipped default — :class:`ValidationPipe`
— uses Pydantic v2 ``TypeAdapter`` to coerce strings into typed scalars,
validate ``BaseModel`` payloads, and respect optional / default semantics.

Custom pipes can swap in via ``create_app(pipe=MyPipe())``.
"""

import types
import typing
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, override

from pydantic import TypeAdapter

from .exceptions import BadRequestException
from .introspect import ParamSource

if TYPE_CHECKING:
    from .introspect import ResolvedParam


class Pipe(ABC):
    """Async per-parameter value coercer.

    Subclass and pass to ``create_app(pipe=...)`` to override the default
    Pydantic-based validation. Each handler parameter is routed through
    ``transform`` once before the handler runs.
    """

    @abstractmethod
    async def transform(self, value: object, *, param: ResolvedParam) -> object:
        """Coerce ``value`` (raw from the request) into the type ``param`` expects."""


class ValidationPipe(Pipe):
    """Default pipe: Pydantic ``TypeAdapter`` for everything.

    Edge cases honoured:

    - Raw ``request: Request`` parameters bypass validation entirely.
    - ``Body()`` of ``bytes`` / ``str`` is passed through unchanged.
    - Missing optional values (``T | None`` or with a Python default) resolve
      to ``None`` / the default.
    - Missing required values raise :class:`BadRequestException` (→ 400).
    - Pydantic ``ValidationError`` propagates and lands at the default
      ``ValidationError`` filter (→ 422 with ``details``).
    """

    @override
    async def transform(self, value: object, *, param: ResolvedParam) -> object:
        if param.source is ParamSource.RAW_REQUEST:
            return value

        target = param.annotation
        inner, is_optional = _split_optional(target)

        if _is_missing(value, inner):
            if is_optional or param.has_default:
                return param.default
            raise BadRequestException(_missing_message(param))

        # ``Body(bytes|str)`` passes through without Pydantic coercion.
        if param.source is ParamSource.BODY and inner in (bytes, str):
            return value

        validation_type: Any = inner if is_optional else target
        return TypeAdapter(validation_type).validate_python(value)


# --------------------------------------------------------------------- helpers


def _split_optional(annotation: Any) -> tuple[Any, bool]:
    """``T | None`` → ``(T, True)``; otherwise ``(annotation, False)``."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _is_missing(value: object, inner_type: Any) -> bool:
    """Tell whether ``value`` should be treated as 'not provided' for ``inner_type``.

    ``None`` is always missing. An empty list is missing iff the target
    type is not list-shaped (e.g. ``getlist`` returned ``[]`` for an
    absent scalar query key).
    """
    if value is None:
        return True
    if isinstance(value, list) and not value:
        return typing.get_origin(inner_type) is not list
    return False


def _missing_message(param: ResolvedParam) -> str:
    if param.source is ParamSource.HEADER:
        return f"Missing required header: {param.source_key or param.name}"
    if param.source is ParamSource.QUERY:
        return f"Missing required query parameter: {param.source_key or param.name}"
    return f"Missing required parameter: {param.name}"
