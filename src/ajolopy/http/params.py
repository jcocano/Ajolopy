"""Param-injection marker types and constructors.

Markers live inside ``typing.Annotated`` on handler parameters; the
introspection layer picks them up at ``add_route`` time and uses them to
decide where each parameter's value comes from at request time.

Public surface::

    Annotated[Dto,            Body()]                 # request body
    Annotated[int,            Query()]                # ?<param-name>=...
    Annotated[int,            Query("p")]             # ?p=...
    Annotated[str,            Param()]                # /{param-name}
    Annotated[str,            Param("uid")]           # /{uid}
    Annotated[str,            Header("authorization") # Authorization: ...
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParamMarker:
    """Base class for all param markers (subclasses live below)."""


@dataclass(frozen=True, slots=True)
class BodyMarker(ParamMarker):
    """Marker: read from the request body."""


@dataclass(frozen=True, slots=True)
class QueryMarker(ParamMarker):
    """Marker: read from the query string."""

    name: str | None = None


@dataclass(frozen=True, slots=True)
class PathMarker(ParamMarker):
    """Marker: read from a URL path placeholder."""

    name: str | None = None


@dataclass(frozen=True, slots=True)
class HeaderMarker(ParamMarker):
    """Marker: read from a request header (case-insensitive lookup)."""

    name: str | None = None


def Body() -> BodyMarker:  # noqa: N802
    """Inject the request body parsed/validated per the parameter's type.

    Supported parameter types (see :mod:`ajolopy.http.introspect`):

    - ``BaseModel`` subclass → ``request.json()`` + ``Model.model_validate``
    - ``dict[str, Any]``     → ``request.json()`` (no extra validation)
    - ``bytes``              → ``request.body()`` (raw)
    - ``str``                → ``request.body()`` decoded as UTF-8
    """
    return BodyMarker()


def Query(name: str | None = None) -> QueryMarker:  # noqa: N802
    """Inject a query-string value.

    ``name`` overrides the parameter name when the query key differs.
    """
    return QueryMarker(name=name)


def Param(name: str | None = None) -> PathMarker:  # noqa: N802
    """Inject a URL path placeholder.

    ``name`` overrides the parameter name when the path placeholder differs.
    """
    return PathMarker(name=name)


def Header(name: str | None = None) -> HeaderMarker:  # noqa: N802
    """Inject a request header value (case-insensitive lookup).

    ``name`` overrides the parameter name when the header name differs.
    """
    return HeaderMarker(name=name)
