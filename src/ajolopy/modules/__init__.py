"""``@Module`` composition layer.

Public surface:

- :class:`ModuleMetadata` — the frozen dataclass attached to every
  ``@Module``-decorated class as ``_ajolopy_module``.
- :func:`Module` — the class decorator.
- :func:`forwardRef` — helper for circular module imports.
- :class:`ForwardRef` — the sentinel type ``forwardRef`` returns.
- :func:`compile_module` — walk a module graph into a populated
  :class:`Container`.
- :class:`CompiledModule` — the frozen result of ``compile_module``.
- Error hierarchy: :class:`ModuleError` and its specialisations.
"""

from .compiler import CompiledModule, compile_module
from .decorator import Module, ModuleMetadata
from .errors import (
    CircularModuleImportError,
    DuplicateProviderError,
    ModuleConfigError,
    ModuleError,
    ModuleVisibilityError,
    NotAModuleError,
    UnresolvedForwardRefError,
)
from .forward_ref import ForwardRef, forwardRef

__all__ = [
    "CircularModuleImportError",
    "CompiledModule",
    "DuplicateProviderError",
    "ForwardRef",
    "Module",
    "ModuleConfigError",
    "ModuleError",
    "ModuleMetadata",
    "ModuleVisibilityError",
    "NotAModuleError",
    "UnresolvedForwardRefError",
    "compile_module",
    "forwardRef",
]
