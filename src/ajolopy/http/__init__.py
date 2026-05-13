"""HTTP layer over Starlette.

Public surface — ``create_app``, ``add_route``, param markers
(``Body``/``Query``/``Param``/``Header``), exception filters
(``ExceptionFilter`` + ``@Catch``), and the ``HttpException`` family —
land in subsequent commits as the AJ-15 acceptance items are implemented.
This module's import is currently side-effect-free.
"""

from .app import Handler, add_route, create_app
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

__all__ = [
    "BadRequestException",
    "ConflictException",
    "ExceptionFilterConfigError",
    "ForbiddenException",
    "Handler",
    "HttpException",
    "HttpHandlerConfigError",
    "HttpLayerError",
    "InternalServerErrorException",
    "NotFoundException",
    "UnauthorizedException",
    "UnprocessableEntityException",
    "add_route",
    "create_app",
]
