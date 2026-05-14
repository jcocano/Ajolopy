"""Framework-side errors raised by :class:`AjolopyFactory`.

Every failure during bootstrap is funneled through
:class:`FactoryStartupError`, which carries the *step name* that failed
so deploy logs and ``ajolopy doctor`` (future) can point at the
offending phase without parsing a stack trace.
"""


class FactoryError(RuntimeError):
    """Base class for any error raised by :class:`AjolopyFactory`."""


class FactoryConfigError(FactoryError):
    """The argument passed to :meth:`AjolopyFactory.create` is invalid.

    Raised before any bootstrap step runs — typically because
    ``root_module`` is not a class decorated with ``@Module``.
    """


class FactoryStartupError(FactoryError):
    """A bootstrap step failed.

    Always raised via ``raise FactoryStartupError(...) from exc`` so the
    original exception is preserved on ``__cause__``. The :attr:`step`
    attribute names the phase that failed; legal values are:

    - ``"validate_env"`` — early env validation (``BaseConfig`` instantiation).
    - ``"compile_module"`` — :func:`ajolopy.modules.compile_module` raised.
    - ``"fire_on_app_bootstrap"`` — :class:`LifecycleManager` raised.
    - ``"mount_routes"`` — route mounting raised.
    - ``"mount_streams"`` — stream mounting raised.
    """

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"[{step}] {message}")
        self.step = step
