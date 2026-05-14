"""Bootstrap entry point for an Ajolopy application.

Public surface:

- :class:`AjolopyFactory` — the single async entry point
  ``await AjolopyFactory.create(AppModule)``.
- :class:`AjolopyApp` — the runtime artifact the factory returns,
  with ``listen``, ``aclose``, and ``async with`` lifecycle.
- :func:`run` — the killer-demo convenience that wraps
  ``AjolopyFactory.create`` + ``listen`` + SIGINT/SIGTERM handling.
- Error hierarchy: :class:`FactoryError`, :class:`FactoryConfigError`,
  :class:`FactoryStartupError` (carries a ``step`` field).
"""

from .app import AjolopyApp
from .errors import FactoryConfigError, FactoryError, FactoryStartupError
from .factory import AjolopyFactory
from .run import run

__all__ = [
    "AjolopyApp",
    "AjolopyFactory",
    "FactoryConfigError",
    "FactoryError",
    "FactoryStartupError",
    "run",
]
