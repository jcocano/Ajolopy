"""Framework-side errors raised by ``@Module`` composition.

Every error names the offending module class (and, for cycle / visibility
cases, the full module path) so the user can act on the message without
opening the framework source.
"""


class ModuleError(RuntimeError):
    """Base class for any error raised by ``@Module`` or ``compile_module``."""


class ModuleConfigError(ModuleError):
    """A ``@Module(...)`` declaration cannot be honoured.

    Raised when the decorator is misused at definition time — exporting a
    token that is not in ``providers=``, listing a non-type entry inside
    any of the list kwargs, re-decorating an already-`@Module` class, or
    other declarative mistakes the compiler detects without walking the
    import graph.
    """


class NotAModuleError(ModuleError):
    """``compile_module(...)`` or ``imports=[...]`` references a class that
    is not decorated with ``@Module``.

    The message names the offending class and its module so the fix is
    obvious.
    """


class ModuleVisibilityError(ModuleError):
    """A provider depends on a token outside its visibility set.

    The visibility set for a module is the union of its own providers,
    the exports of its direct imports, and the exports of every global
    module in the graph. Raised at compile time, before the container is
    used, with both the dependent provider and the missing token in the
    message.
    """


class CircularModuleImportError(ModuleError):
    """A non-``forwardRef`` cycle exists in the module import graph.

    The message includes the full cycle path
    (``A → B → C → A``) so the user knows which import to wrap in
    ``forwardRef(lambda: ...)``.
    """


class UnresolvedForwardRefError(ModuleError):
    """A ``forwardRef`` thunk did not return an importable module class.

    Raised when the thunk raises, returns a non-class object, returns a
    class without ``_ajolopy_module``, or returns another ``forwardRef``
    (chained forward references are not supported — declare the module
    directly).
    """


class DuplicateProviderError(ModuleError):
    """The same provider token is owned by two modules in the same graph.

    Raised at compile time with both modules and the offending token in
    the message. There is no "global wins" shortcut: a provider in a
    global module that is also listed in a non-global module's
    ``providers=`` raises the same error.
    """
