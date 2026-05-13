"""Handler signature introspection and per-request value extraction.

At ``add_route`` time, :func:`introspect_handler` walks the handler's
signature, pairs each parameter with its source (Body / Query / Path /
Header / RawRequest), and validates the combination eagerly. At request
time, :func:`extract_raw` pulls each parameter's raw value from the
request; the configured ``Pipe`` then coerces/validates the raw value
against the parameter's annotation.

Errors here are :class:`HttpHandlerConfigError` at decoration time;
runtime missing-required errors land as ``HttpException`` subclasses so
the default filter pipeline turns them into the framework's envelope.
"""

import inspect
import json
import re
import types
import typing
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from starlette.requests import Request

from .errors import HttpHandlerConfigError
from .exceptions import BadRequestException
from .params import BodyMarker, HeaderMarker, ParamMarker, PathMarker, QueryMarker

if TYPE_CHECKING:
    from collections.abc import Callable

_BODY_SCALAR_TYPES: frozenset[type] = frozenset({bytes, str})
_PATH_PLACEHOLDER_RE = re.compile(r"\{([^:}]+)(:[^}]+)?\}")


class ParamSource(StrEnum):
    """Where a handler parameter's value is read from."""

    BODY = "body"
    QUERY = "query"
    PATH = "path"
    HEADER = "header"
    RAW_REQUEST = "raw_request"


@dataclass(slots=True)
class ResolvedParam:
    """One handler parameter after introspection.

    The configured ``Pipe`` receives this record for every parameter at
    request time. Custom pipes can inspect ``source`` / ``annotation`` to
    decide how to coerce ``value``.
    """

    name: str
    """Python parameter name on the handler."""

    annotation: Any
    """Target type. The pipe coerces the extracted raw value against this."""

    source: ParamSource
    """Where the raw value is read from on the request."""

    source_key: str | None
    """Lookup key for the source (query key, path placeholder, header name).

    ``None`` for ``BODY`` (there is exactly one body) and ``RAW_REQUEST``.
    """

    has_default: bool
    default: Any


def introspect_handler(
    handler: Callable[..., Any],
    path: str,
) -> list[ResolvedParam]:
    """Walk ``handler``'s signature and produce per-parameter resolution info.

    Raises :class:`HttpHandlerConfigError` for any signature the framework
    cannot meaningfully bind: missing annotations, unresolvable forward
    references, two markers on one parameter, duplicate ``Body()``,
    unsupported body type, ``Param()`` with no matching placeholder in
    ``path``.
    """
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError) as exc:
        raise HttpHandlerConfigError(
            f"Could not introspect handler {_qualname(handler)}: {exc}"
        ) from exc

    try:
        hints = typing.get_type_hints(handler, include_extras=True)
    except (NameError, AttributeError, TypeError) as exc:
        raise HttpHandlerConfigError(
            f"Handler {_qualname(handler)} has an unresolvable type annotation: {exc}"
        ) from exc

    path_placeholders = {m.group(1) for m in _PATH_PLACEHOLDER_RE.finditer(path)}

    resolved: list[ResolvedParam] = []
    body_count = 0

    for name, sig_param in sig.parameters.items():
        if name == "self":
            continue
        if sig_param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise HttpHandlerConfigError(
                f"Handler {_qualname(handler)} declares *args / **kwargs at "
                f"parameter '{name}'; not supported."
            )

        annotation = hints.get(name, inspect.Parameter.empty)
        if annotation is inspect.Parameter.empty:
            raise HttpHandlerConfigError(
                f"Handler {_qualname(handler)} parameter '{name}' has no type annotation."
            )

        inner_type, markers = _unwrap_annotated(annotation)
        param_markers = [m for m in markers if isinstance(m, ParamMarker)]

        if len(param_markers) > 1:
            raise HttpHandlerConfigError(
                f"Handler {_qualname(handler)} parameter '{name}' has "
                f"multiple param markers: {param_markers}; at most one is allowed."
            )

        marker: ParamMarker | None = param_markers[0] if param_markers else None
        target_type: Any = inner_type if marker is not None else annotation

        # No marker → must be a raw Request injection.
        if marker is None:
            if not _is_request_type(target_type):
                raise HttpHandlerConfigError(
                    f"Handler {_qualname(handler)} parameter '{name}' has no "
                    f"param marker and is not typed as starlette Request. Use "
                    f"Annotated[T, Body()/Query()/Param()/Header()] or "
                    f"`request: Request` for raw access."
                )
            source = ParamSource.RAW_REQUEST
            source_key: str | None = None
        elif isinstance(marker, BodyMarker):
            body_count += 1
            if body_count > 1:
                raise HttpHandlerConfigError(
                    f"Handler {_qualname(handler)} declares more than one "
                    f"Body() parameter; at most one is allowed."
                )
            _validate_body_type(handler, name, target_type)
            source = ParamSource.BODY
            source_key = None
        elif isinstance(marker, QueryMarker):
            source = ParamSource.QUERY
            source_key = marker.name or name
        elif isinstance(marker, PathMarker):
            source_key = marker.name or name
            if source_key not in path_placeholders:
                raise HttpHandlerConfigError(
                    f"Handler {_qualname(handler)} parameter '{name}' uses "
                    f"Param({marker.name!r}) but path {path!r} has no matching "
                    f"placeholder. Found placeholders: {sorted(path_placeholders)}"
                )
            source = ParamSource.PATH
        elif isinstance(marker, HeaderMarker):
            source = ParamSource.HEADER
            source_key = marker.name or name
        else:  # pragma: no cover — exhausted above; defensive.
            raise HttpHandlerConfigError(f"Unknown marker on '{name}': {marker!r}")

        resolved.append(
            ResolvedParam(
                name=name,
                annotation=target_type,
                source=source,
                source_key=source_key,
                has_default=sig_param.default is not inspect.Parameter.empty,
                default=(
                    sig_param.default if sig_param.default is not inspect.Parameter.empty else None
                ),
            )
        )

    return resolved


async def extract_raw(request: Request, param: ResolvedParam) -> object:
    """Pull the raw value for ``param`` from ``request``.

    The returned value is what the configured pipe will receive in its
    ``transform(value, *, param=...)`` call. ``None`` indicates "missing"
    for query / path / header sources; the pipe decides whether that is
    acceptable based on the parameter's annotation and default.
    """
    if param.source is ParamSource.RAW_REQUEST:
        return request

    if param.source is ParamSource.BODY:
        inner = _strip_optional(param.annotation)
        if inner is bytes:
            return await request.body()
        if inner is str:
            body_bytes = await request.body()
            return body_bytes.decode("utf-8")
        # BaseModel | dict | list — parse JSON.
        try:
            return await request.json()
        except json.JSONDecodeError as exc:
            raise BadRequestException(f"Invalid JSON body: {exc.msg}") from exc

    # source_key is guaranteed non-None for QUERY / PATH / HEADER by
    # introspect_handler; fall back to "" to keep pyright happy without
    # using ``assert`` (which ruff S101 forbids in src code).
    key = param.source_key or ""

    if param.source is ParamSource.QUERY:
        inner = _strip_optional(param.annotation)
        if _is_basemodel(inner):
            # Whole query string as a dict; Pydantic coerces individual fields.
            return dict(request.query_params)
        if _is_list_type(inner):
            # Repeated keys collected into a list.
            return request.query_params.getlist(key)
        return request.query_params.get(key)

    if param.source is ParamSource.PATH:
        return request.path_params.get(key)

    if param.source is ParamSource.HEADER:
        return request.headers.get(key)

    raise RuntimeError(f"Unknown ParamSource: {param.source}")  # pragma: no cover


# ----------------------------------------------------------------------- helpers


def _qualname(obj: object) -> str:
    return getattr(obj, "__qualname__", repr(obj))


def _unwrap_annotated(annotation: Any) -> tuple[Any, tuple[object, ...]]:
    """Return ``(inner_type, metadata)`` for ``Annotated[T, *meta]``; else ``(T, ())``."""
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is None:
        return annotation, ()
    origin = annotation.__origin__
    return origin, tuple(metadata)


def _is_request_type(annotation: Any) -> bool:
    """True iff the annotation resolves to Starlette ``Request`` or a subclass."""
    return isinstance(annotation, type) and issubclass(annotation, Request)


def _is_basemodel(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _is_list_type(annotation: Any) -> bool:
    """True for ``list[T]`` / ``List[T]`` annotations."""
    origin = typing.get_origin(annotation)
    return origin is list


def _strip_optional(annotation: Any) -> Any:
    """``T | None`` → ``T``; otherwise return ``annotation`` unchanged."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _validate_body_type(handler: Callable[..., Any], name: str, annotation: Any) -> None:
    inner = _strip_optional(annotation)
    if inner in _BODY_SCALAR_TYPES:
        return
    if _is_basemodel(inner):
        return
    # dict / list (with or without type args) are accepted — Pydantic handles them.
    origin = typing.get_origin(inner)
    if origin in (dict, list) or inner in (dict, list):
        return
    raise HttpHandlerConfigError(
        f"Handler {_qualname(handler)} parameter '{name}' has unsupported "
        f"Body() type {annotation!r}. Use BaseModel, dict, list, bytes, or str."
    )
