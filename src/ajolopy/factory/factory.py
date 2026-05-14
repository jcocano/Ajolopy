"""``AjolopyFactory.create()`` — the single bootstrap entry point.

Wires the foundation pieces in a fixed order, with typed failure
modes:

1. **Early env validation** — every :class:`BaseConfig` subclass in the
   module graph is instantiated against ``os.environ`` before any
   container work runs. Pydantic raises early, surfaces as
   :class:`FactoryStartupError(step="validate_env")`.
2. ``compile_module`` from AJ-8 — populated container.
3. :class:`LifecycleManager.bootstrap` — fires ``on_module_init`` then
   ``on_app_bootstrap`` on every singleton.
4. ``create_app`` from AJ-15 — Starlette app.
5. ``mount_routes`` from AJ-16 — controllers (with AJ-10 prefixes).
6. ``mount_streams`` from AJ-3 — SSE streams.

Each step's failure is captured as :class:`FactoryStartupError` with
the step name; the original exception chains via ``__cause__`` so
deploy logs and ``ajolopy doctor`` (future) can introspect both.
"""

from typing import TYPE_CHECKING, cast

from ajolopy.config import BaseConfig
from ajolopy.http import create_app
from ajolopy.lifecycle import LifecycleManager
from ajolopy.modules import (
    CircularModuleImportError,
    DuplicateProviderError,
    ForwardRef,
    ModuleMetadata,
    ModuleVisibilityError,
    NotAModuleError,
    UnresolvedForwardRefError,
    compile_module,
)
from ajolopy.routes import mount_routes
from ajolopy.stream import iter_stream_methods, mount_streams

from .app import AjolopyApp
from .errors import FactoryConfigError, FactoryStartupError

if TYPE_CHECKING:
    from starlette.applications import Starlette

    from ajolopy.di import Container
    from ajolopy.modules import CompiledModule


class AjolopyFactory:
    """Async classmethod entry point that produces a ready :class:`AjolopyApp`."""

    @classmethod
    async def create(
        cls,
        root_module: type,
        *,
        container: Container | None = None,
        http: Starlette | None = None,
    ) -> AjolopyApp:
        """Build and return an :class:`AjolopyApp` for ``root_module``.

        Parameters
        ----------
        root_module:
            The application's root ``@Module``-decorated class.
        container:
            Optional pre-built :class:`Container` for tests that pre-
            seed mocks. Forwarded to :func:`compile_module`.
        http:
            Optional pre-built Starlette app for tests that exercise
            the framework without rebuilding the HTTP layer. Routes
            and streams from the module graph are mounted onto it.

        Raises
        ------
        FactoryConfigError
            ``root_module`` is not a class decorated with ``@Module``.
        FactoryStartupError
            Any bootstrap step failed. The ``step`` attribute names
            the phase; the original exception chains via ``__cause__``.
        """
        if (
            not isinstance(root_module, type)  # pyright: ignore[reportUnnecessaryIsInstance]
            or "_ajolopy_module" not in root_module.__dict__
        ):
            # Runtime guard — users can pass anything at the boundary.
            qualname = getattr(root_module, "__qualname__", repr(root_module))
            raise FactoryConfigError(
                f"AjolopyFactory.create expects a @Module-decorated class; got {qualname}."
            )

        # 1. Early env validation — instantiate every BaseConfig subclass
        #    directly against os.environ so missing required env vars fail
        #    before any container work runs.
        _validate_env_early(root_module)

        # 2. Compile the module graph.
        try:
            compiled = compile_module(root_module, container=container)
        except (
            NotAModuleError,
            CircularModuleImportError,
            UnresolvedForwardRefError,
            DuplicateProviderError,
            ModuleVisibilityError,
        ) as exc:
            raise FactoryStartupError("compile_module", f"{type(exc).__name__}: {exc}") from exc

        # 3. Eager-resolve every singleton so on_module_init /
        #    on_app_bootstrap fire over the full graph. AJ-13's lifecycle
        #    walks ``Container.iter_singletons()``, which only yields
        #    already-cached instances, so this step is mandatory.
        _eager_resolve_singletons(compiled)

        # 4. Fire on_module_init + on_app_bootstrap.
        lifecycle = LifecycleManager(compiled.container)
        try:
            await lifecycle.bootstrap()
        except BaseException as exc:
            raise FactoryStartupError(
                "fire_on_app_bootstrap", f"{type(exc).__name__}: {exc}"
            ) from exc

        # 5. Build (or reuse) the Starlette app.
        http_app = http if http is not None else create_app()

        # 6. Mount routes (controllers + AJ-10 prefixes).
        if compiled.controllers:
            try:
                mount_routes(http_app, list(compiled.controllers))
            except Exception as exc:
                raise FactoryStartupError("mount_routes", f"{type(exc).__name__}: {exc}") from exc

        # 7. Mount streams — controllers may declare @Stream methods
        #    alongside their @Get/@Post handlers. mount_streams refuses
        #    classes with no @Stream methods (would shadow a real bug),
        #    so the factory filters to controllers that *do* have at
        #    least one before forwarding the list.
        stream_carriers = [cls for cls in compiled.controllers if any(iter_stream_methods(cls))]
        if stream_carriers:
            try:
                mount_streams(http_app, stream_carriers)
            except Exception as exc:
                raise FactoryStartupError("mount_streams", f"{type(exc).__name__}: {exc}") from exc

        return AjolopyApp(
            compiled_module=compiled,
            http=http_app,
            lifecycle=lifecycle,
        )


def _eager_resolve_singletons(compiled: CompiledModule) -> None:
    """Force every singleton-scoped provider to be resolved once.

    AJ-13's :class:`LifecycleManager` walks
    :meth:`Container.iter_singletons`, which only yields already-cached
    instances. Without this step, ``on_app_bootstrap`` hooks would
    silently fail to fire on providers that nothing else has resolved
    yet (which is the normal case at the moment ``create()`` runs).
    """
    seen: set[type] = set()
    for mod in compiled.module_order:
        meta = cast(ModuleMetadata, mod.__dict__["_ajolopy_module"])  # noqa: TC006 — runtime import so CodeQL sees usage
        for token in (
            *meta.providers,
            *meta.controllers,
            *meta.agents,
            *meta.workflows,
            *meta.evals,
        ):
            if token in seen:
                continue
            seen.add(token)
            scope = getattr(token, "__ajolopy_scope__", "singleton")
            if scope == "singleton":
                compiled.container.resolve(token)


def _validate_env_early(root_module: type) -> None:
    """Walk the module graph and validate every ``BaseConfig`` subclass.

    Instantiates each one (zero-arg) so the pydantic-settings machinery
    reads ``os.environ`` for the *declared* fields only and rejects
    missing required ones. The instance is discarded — the container
    will re-instantiate them properly during ``compile_module``.

    This early pass surfaces missing env vars before any other
    bootstrap step touches the container. Surfaces
    ``pydantic.ValidationError`` as :class:`FactoryStartupError(step="validate_env")`.
    """
    seen_modules: set[type] = set()
    seen_configs: set[type] = set()

    def walk(mod: type) -> None:
        if (
            not isinstance(mod, type)  # pyright: ignore[reportUnnecessaryIsInstance]
            or mod in seen_modules
        ):
            return
        raw_meta = getattr(mod, "_ajolopy_module", None)
        if raw_meta is None:
            return
        meta = cast(ModuleMetadata, raw_meta)  # noqa: TC006 — runtime import so CodeQL sees usage
        seen_modules.add(mod)

        # Every owned token (providers + controllers + agents + workflows + evals)
        # is a candidate for BaseConfig subclassing.
        for token in (
            *meta.providers,
            *meta.controllers,
            *meta.agents,
            *meta.workflows,
            *meta.evals,
        ):
            if (
                isinstance(token, type)  # pyright: ignore[reportUnnecessaryIsInstance]
                and issubclass(token, BaseConfig)
                and token is not BaseConfig
                and token not in seen_configs
            ):
                seen_configs.add(token)
                try:
                    token()  # BaseSettings reads os.environ + .env automatically.
                except Exception as exc:
                    raise FactoryStartupError(
                        "validate_env",
                        f"{token.__qualname__} failed: {type(exc).__name__}: {exc}",
                    ) from exc

        # Recurse into imports — forwardRef sentinels are resolved lazily.
        for entry in meta.imports:
            target: type = entry.resolve() if isinstance(entry, ForwardRef) else entry
            walk(target)

    walk(root_module)
