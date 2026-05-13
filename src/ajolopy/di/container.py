"""``Container`` — the runtime engine behind Ajolopy's DI story.

Three scopes — singleton (default), request, transient — driven by a
single ``register()`` / ``resolve()`` programmatic API. The
declarative wrappers (`@Injectable` in AJ-9, `@Module` in AJ-8,
lifecycle hooks in AJ-13, `AjolopyFactory.create` in AJ-14) all
compile down to calls on this class.

State is intentionally per-instance: tests build fresh containers
without leaking singletons across the test suite. The request scope
piggy-backs on ``contextvars`` so concurrent ``asyncio.Task``s each
get their own per-request cache without locks.
"""

import contextlib
import threading

# Runtime imports: PEP 649 evaluates annotations on first
# ``__annotations__`` access, so dataclass + context-manager machinery
# needs these names available at runtime. Hence the TC003 suppression.
from collections.abc import (  # noqa: TC003
    AsyncGenerator,
    Callable,
    Generator,
    Iterator,
)
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from ._introspect import introspect_dependencies
from .errors import (
    CircularDependencyError,
    ContainerConfigError,
    OutOfScopeError,
    ProviderNotRegisteredError,
)

Scope = Literal["singleton", "request", "transient"]

_ALLOWED_SCOPES: frozenset[str] = frozenset({"singleton", "request", "transient"})

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class _Registration:
    """A single ``register()`` call, snapshotted."""

    token: type
    scope: Scope
    instance: Any = None
    factory: Callable[[Container], Any] | None = None


@dataclass(slots=True)
class _ContainerState:
    """Per-container mutable state.

    Kept in its own dataclass so the ``Container`` class stays
    readable: ``self._state.singletons`` reads more clearly than a
    grab-bag of ``self._foo`` attributes.
    """

    singletons: dict[type, Any] = field(default_factory=dict[type, Any])
    singleton_order: list[type] = field(default_factory=list[type])
    singleton_lock: threading.Lock = field(default_factory=threading.Lock)
    per_token_build_locks: dict[type, threading.Lock] = field(
        default_factory=dict[type, threading.Lock],
    )


class Container:
    """In-process DI container.

    Construct one per application root (the framework's bootstrap
    layer will build it; tests build it directly). Singletons are
    cached on this instance only — two containers in the same test
    produce two independent singletons.
    """

    def __init__(self) -> None:
        self._registrations: dict[type, _Registration] = {}
        self._state = _ContainerState()
        # Per-instance ``contextvars`` so request scopes from
        # different containers do not collide. Default ``None``
        # signals "no active scope"; entering a scope swaps the
        # value to a fresh dict, exiting resets it.
        self._request_cache: ContextVar[dict[type, Any] | None] = ContextVar(
            f"ajolopy_di_request_cache_{id(self):x}", default=None
        )
        self._resolution_stack: ContextVar[tuple[type, ...]] = ContextVar(
            f"ajolopy_di_stack_{id(self):x}", default=()
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        provider: type[T],
        *,
        scope: Scope = "singleton",
        instance: T | None = None,
        factory: Callable[[Container], T] | None = None,
        overwrite: bool = False,
    ) -> None:
        """Register ``provider`` so the container can resolve it later.

        One of three modes is in effect:

        - **class only** — the container will build ``provider`` by
          recursively resolving its ``__init__`` dependencies.
        - ``instance=`` — store ``instance`` verbatim. Always
          singleton scope; passing any other scope raises
          :class:`ContainerConfigError`.
        - ``factory=`` — call ``factory(container)`` to build the
          instance lazily; the result is cached per the chosen scope.

        ``overwrite=True`` lets a caller replace a previous
        registration (tests use this; production code should not).
        """
        if scope not in _ALLOWED_SCOPES:
            raise ContainerConfigError(
                f"Unknown scope {scope!r} for {_qualname(provider)}. "
                f"Legal scopes: {sorted(_ALLOWED_SCOPES)}."
            )
        if instance is not None and factory is not None:
            raise ContainerConfigError(
                f"register({_qualname(provider)}) cannot accept both instance= "
                f"and factory= — they are mutually exclusive."
            )
        if instance is not None and scope != "singleton":
            raise ContainerConfigError(
                f"register({_qualname(provider)}, instance=...) implies "
                f"singleton scope; got scope={scope!r}."
            )
        if provider in self._registrations and not overwrite:
            raise ContainerConfigError(
                f"{_qualname(provider)} is already registered. Pass overwrite=True to replace."
            )
        self._registrations[provider] = _Registration(
            token=provider,
            scope=scope,
            instance=instance,
            factory=factory,
        )

    def is_registered(self, token: type) -> bool:
        """Return whether ``token`` has a registration on this container."""
        return token in self._registrations

    def __contains__(self, token: object) -> bool:
        return isinstance(token, type) and token in self._registrations

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, token: type[T]) -> T:
        """Return the instance bound to ``token``, building it if needed.

        Singletons are cached on the container; request-scoped
        instances are cached in the active ``request_scope()`` block;
        transient registrations always produce a new instance.
        """
        stack = self._resolution_stack.get()
        if token in stack:
            cycle = " → ".join(_qualname(t) for t in (*stack, token))
            raise CircularDependencyError(f"Circular dependency detected: {cycle}")
        reset_token = self._resolution_stack.set((*stack, token))
        try:
            return self._resolve_inner(token)
        finally:
            self._resolution_stack.reset(reset_token)

    def _resolve_inner(self, token: type[T]) -> T:
        registration = self._registrations.get(token)
        if registration is None:
            raise ProviderNotRegisteredError(
                f"{_qualname(token)} is not registered on this container."
            )
        if registration.scope == "singleton":
            return self._resolve_singleton(registration)
        if registration.scope == "request":
            return self._resolve_request(registration)
        return self._build_instance(registration)

    def _resolve_singleton(self, registration: _Registration) -> Any:
        token = registration.token
        cached = self._state.singletons.get(token)
        if cached is not None:
            return cached
        # Take a tiny global lock just to allocate the per-token lock,
        # then release the global one. Per-token locks serialise the
        # actual __init__ call so two threads cannot double-build.
        with self._state.singleton_lock:
            cached = self._state.singletons.get(token)
            if cached is not None:
                return cached
            build_lock = self._state.per_token_build_locks.setdefault(token, threading.Lock())
        with build_lock:
            cached = self._state.singletons.get(token)
            if cached is not None:
                return cached
            instance = self._build_instance(registration, parent_scope="singleton")
            self._state.singletons[token] = instance
            self._state.singleton_order.append(token)
            return instance

    def _resolve_request(self, registration: _Registration) -> Any:
        cache = self._request_cache.get()
        if cache is None:
            raise OutOfScopeError(
                f"{_qualname(registration.token)} is request-scoped but no "
                f"request scope is active. Wrap the resolve in "
                f"`with container.request_scope():` or use "
                f"`async with container.async_request_scope():`."
            )
        token = registration.token
        cached = cache.get(token)
        if cached is not None:
            return cached
        instance = self._build_instance(registration, parent_scope="request")
        cache[token] = instance
        return instance

    def _build_instance(
        self,
        registration: _Registration,
        *,
        parent_scope: Scope | None = None,
    ) -> Any:
        if registration.instance is not None:
            return registration.instance
        if registration.factory is not None:
            return registration.factory(self)
        token = registration.token
        deps = introspect_dependencies(token)
        kwargs: dict[str, Any] = {}
        for name, dep_type in deps.items():
            dep_registration = self._registrations.get(dep_type)
            if dep_registration is None:
                raise ProviderNotRegisteredError(
                    f"{_qualname(dep_type)} is not registered on this "
                    f"container (dependency of {_qualname(token)}.__init__ "
                    f"parameter '{name}')."
                )
            if parent_scope == "singleton" and dep_registration.scope == "request":
                raise OutOfScopeError(
                    f"{_qualname(token)} (singleton) depends on "
                    f"{_qualname(dep_type)} (request-scoped). Singletons "
                    f"must not capture per-request state; promote "
                    f"{_qualname(token)} to request scope or change "
                    f"{_qualname(dep_type)} to singleton."
                )
            kwargs[name] = self.resolve(dep_type)
        return token(**kwargs)

    # ------------------------------------------------------------------
    # Request scope
    # ------------------------------------------------------------------

    def request_scope(self) -> AbstractContextManager[None]:
        """Open a per-request cache; ``with container.request_scope():``."""
        return self._sync_request_scope()

    def async_request_scope(self) -> AbstractAsyncContextManager[None]:
        """Async sibling of :meth:`request_scope`.

        Identical semantics — same per-context cache push/pop — but
        usable as ``async with container.async_request_scope():``.
        """
        return self._async_request_scope()

    @contextlib.contextmanager
    def _sync_request_scope(self) -> Generator[None]:
        token = self._request_cache.set({})
        try:
            yield
        finally:
            self._request_cache.reset(token)

    @contextlib.asynccontextmanager
    async def _async_request_scope(self) -> AsyncGenerator[None]:
        token = self._request_cache.set({})
        try:
            yield
        finally:
            self._request_cache.reset(token)

    # ------------------------------------------------------------------
    # Hooks for AJ-13 (lifecycle)
    # ------------------------------------------------------------------

    def iter_singletons(self) -> Iterator[Any]:
        """Yield every cached singleton instance in first-resolution order.

        AJ-13 walks this to fire ``on_module_init`` /
        ``on_app_bootstrap`` / ``on_app_shutdown`` hooks. Safe to call
        before any singleton has been resolved (yields zero items).
        """
        for token in self._state.singleton_order:
            yield self._state.singletons[token]


def _qualname(obj: object) -> str:
    return getattr(obj, "__qualname__", repr(obj))
