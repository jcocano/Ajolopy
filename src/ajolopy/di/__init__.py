"""Dependency-injection container — the foundation under ``@Injectable`` (AJ-9),
``@Module`` (AJ-8), lifecycle hooks (AJ-13), and ``AjolopyFactory`` (AJ-14).

The public surface is intentionally small: one ``Container`` class plus the
``Scope`` literal and the error hierarchy. Declarative wrappers compile
down to ``Container.register`` / ``Container.resolve`` calls.
"""

from .container import Container, Scope
from .errors import (
    CircularDependencyError,
    ContainerConfigError,
    ContainerError,
    MissingAnnotationError,
    OutOfScopeError,
    ProviderNotRegisteredError,
)

__all__ = [
    "CircularDependencyError",
    "Container",
    "ContainerConfigError",
    "ContainerError",
    "MissingAnnotationError",
    "OutOfScopeError",
    "ProviderNotRegisteredError",
    "Scope",
]
