"""Dependency-injection container — the foundation under ``@Injectable`` (AJ-9),
``@Module`` (AJ-8), lifecycle hooks (AJ-13), and ``AjolopyFactory`` (AJ-14).

The public surface is intentionally small: one ``Container`` class plus the
``Scope`` literal, the ``Injectable`` decorator, and the error hierarchy.
Declarative wrappers compile down to ``Container.register`` / ``Container.resolve``
calls.
"""

from .container import Container, Scope
from .errors import (
    CircularDependencyError,
    ContainerConfigError,
    ContainerError,
    InjectableConfigError,
    InjectableError,
    MissingAnnotationError,
    OutOfScopeError,
    ProviderNotRegisteredError,
)
from .injectable import Injectable

__all__ = [
    "CircularDependencyError",
    "Container",
    "ContainerConfigError",
    "ContainerError",
    "Injectable",
    "InjectableConfigError",
    "InjectableError",
    "MissingAnnotationError",
    "OutOfScopeError",
    "ProviderNotRegisteredError",
    "Scope",
]
