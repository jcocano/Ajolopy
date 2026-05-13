"""Framework-side errors raised by the HTTP layer at configuration time.

These errors fire **before** the app serves traffic — they signal that a
handler signature, marker combination, or filter declaration cannot be
turned into a working route. Runtime errors that surface as HTTP responses
live in :mod:`ajolopy.http.exceptions` (the ``HttpException`` family).
"""


class HttpLayerError(RuntimeError):
    """Base class for any framework-side error raised by the HTTP layer."""


class HttpHandlerConfigError(HttpLayerError):
    """A handler could not be registered.

    Raised at ``add_route`` time when the handler's signature, parameter
    annotations, or marker combination is invalid (untyped parameter with a
    marker, two markers on one parameter, duplicate ``Body()``, unsupported
    body type, ``Param()`` name with no matching path placeholder, unknown
    HTTP verb, etc.).
    """


class ExceptionFilterConfigError(HttpLayerError):
    """An exception filter could not be registered.

    Raised at decoration time when ``@Catch(...)`` is misused — no
    arguments, the decorated class does not subclass ``ExceptionFilter``,
    or both.
    """
