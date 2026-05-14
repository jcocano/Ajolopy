"""HTTP layer over Starlette.

Public surface — ``create_app``, ``add_route``, param markers
(``Body``/``Query``/``Param``/``Header``), exception filters
(``ExceptionFilter`` + ``@Catch``), and the ``HttpException`` family —
land in subsequent commits as the AJ-15 acceptance items are implemented.
This module's import is currently side-effect-free.
"""

from .app import FilterSpec, Handler, add_route, create_app, set_global_pipe
from .errors import (
    ExceptionFilterConfigError,
    HttpHandlerConfigError,
    HttpLayerError,
)
from .exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    HttpException,
    InternalServerErrorException,
    NotFoundException,
    UnauthorizedException,
    UnprocessableEntityException,
)
from .filters import Catch, ExceptionFilter
from .introspect import ParamSource, ResolvedParam
from .params import (
    Body,
    BodyMarker,
    Header,
    HeaderMarker,
    Param,
    ParamMarker,
    PathMarker,
    Query,
    QueryMarker,
)
from .pipes import Pipe, ValidationPipe

__all__ = [
    "BadRequestException",
    "Body",
    "BodyMarker",
    "Catch",
    "ConflictException",
    "ExceptionFilter",
    "ExceptionFilterConfigError",
    "FilterSpec",
    "ForbiddenException",
    "Handler",
    "Header",
    "HeaderMarker",
    "HttpException",
    "HttpHandlerConfigError",
    "HttpLayerError",
    "InternalServerErrorException",
    "NotFoundException",
    "Param",
    "ParamMarker",
    "ParamSource",
    "PathMarker",
    "Pipe",
    "Query",
    "QueryMarker",
    "ResolvedParam",
    "UnauthorizedException",
    "UnprocessableEntityException",
    "ValidationPipe",
    "add_route",
    "create_app",
    "set_global_pipe",
]
