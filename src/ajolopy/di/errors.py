"""Framework-side errors raised by the DI container.

Every error names the offending token (and, for circular cases, the
full resolution path) so the user can act on the message without
opening the framework source.
"""


class ContainerError(RuntimeError):
    """Base class for any error raised by :class:`Container`."""


class ContainerConfigError(ContainerError):
    """A ``register()`` call cannot be honoured.

    Raised when scope is unknown, ``instance=`` and ``factory=`` are
    both supplied, ``instance=`` is paired with a non-singleton scope,
    or a token is re-registered without ``overwrite=True``.
    """


class ProviderNotRegisteredError(ContainerError):
    """``resolve()`` asked for a token the container does not know.

    The message includes the offending token's qualified name; when
    the unknown token surfaces as a transitive dependency, it also
    names the dependent class so the fix is obvious.
    """


class CircularDependencyError(ContainerError):
    """A resolution would re-enter a token already being resolved.

    The message includes the full cycle path
    (``A → B → C → A``) so the user can break it.
    """


class MissingAnnotationError(ContainerError):
    """A constructor parameter has no usable type annotation.

    The container only injects by **type hint** — bare ``__init__(self, db)``
    parameters and parameters whose annotation cannot be resolved
    (unreachable forward references, ``Annotated`` without a marker the
    container understands) raise this. Always names the parameter and
    the class.
    """


class OutOfScopeError(ContainerError):
    """A request-scoped resolution happened outside ``request_scope()``.

    Also raised when a singleton being built depends on a
    request-scoped token, even if the build happens inside a request
    scope — singletons must not capture per-request state. The message
    names both services so the fix is straightforward.
    """
