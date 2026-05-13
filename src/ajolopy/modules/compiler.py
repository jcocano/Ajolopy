"""Walk a ``@Module`` graph and produce a populated :class:`Container`.

Public entry point: :func:`compile_module`. Consumed by ``AjolopyFactory.create``
(AJ-14) at app startup; tests construct a ``compile_module`` call directly to
exercise modules without the bootstrap glue.

Compilation phases (in order):

1. **Walk** — DFS from the root, resolve ``forwardRef`` thunks, detect
   non-``forwardRef`` cycles, record the dependency-first topological
   order in ``module_order``.
2. **Dedup** — for every module, the union of ``providers`` /
   ``controllers`` / ``agents`` / ``workflows`` / ``evals`` is the set of
   tokens it owns. Overlap inside a single module is deduped silently;
   overlap *across* modules raises :class:`DuplicateProviderError`.
3. **Pre-populated container collision** — if the caller supplied a
   container that already has any owned token registered, that's a
   :class:`DuplicateProviderError` too.
4. **Visibility** — for each module, compute the set of tokens it can
   resolve: union of own providers, direct-imports' exports, and every
   global module's exports. Every provider's ``__init__`` DI dependency
   must be in this set; otherwise raise :class:`ModuleVisibilityError`.
5. **Register** — populate the container, honouring ``__ajolopy_scope__``
   when set by AJ-9's ``@Injectable`` (defaults to singleton).
6. **Pack** — build the frozen :class:`CompiledModule` for the caller.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ajolopy.di import Container, Scope

from ._introspect import collect_di_deps
from .errors import (
    CircularModuleImportError,
    DuplicateProviderError,
    ModuleVisibilityError,
    NotAModuleError,
)
from .forward_ref import ForwardRef

if TYPE_CHECKING:
    from .decorator import ModuleMetadata


def _meta(cls: type) -> ModuleMetadata:
    """Read the stamped ``ModuleMetadata`` from a ``@Module`` class.

    Callers must ensure ``cls`` is ``@Module``-decorated first (via
    :func:`_ensure_module`); this helper only narrows the typing.
    """
    return cast("ModuleMetadata", cls.__dict__["_ajolopy_module"])


@dataclass(frozen=True, slots=True)
class CompiledModule:
    """Result of :func:`compile_module`.

    All collections are tuples so callers cannot mutate the compiled
    graph mid-flight.

    Attributes
    ----------
    container:
        The populated :class:`Container`. Resolve any token in any
        module's visibility set on it.
    controllers / agents / workflows / evals:
        Flat tuples of classes in graph-traversal order (leaves first).
        AJ-14 mounts controllers in this order; future items consume
        the others.
    module_order:
        Modules in dependency-first topological order — leaves of the
        import graph appear before the modules that import them. Used
        by AJ-14 for deterministic controller mounting, **not** for
        lifecycle hooks (AJ-13 already drives those via
        ``Container.iter_singletons``).
    """

    container: Container
    controllers: tuple[type, ...]
    agents: tuple[type, ...]
    workflows: tuple[type, ...]
    evals: tuple[type, ...]
    module_order: tuple[type, ...]


def _ensure_module(cls: object) -> type:
    """Raise :class:`NotAModuleError` if ``cls`` is not a ``@Module``."""
    if not isinstance(cls, type) or "_ajolopy_module" not in cls.__dict__:
        # ``_ajolopy_module`` is not inherited (see decorator.py); use
        # __dict__ instead of getattr to enforce that.
        name = getattr(cls, "__qualname__", repr(cls))
        raise NotAModuleError(
            f"{name} is not decorated with @Module; cannot be used as an import or a compile root."
        )
    return cls


def _owned_tokens(meta: ModuleMetadata) -> set[type]:
    """Return the set of tokens a single module owns (intra-module dedup)."""
    return (
        set(meta.providers)
        | set(meta.controllers)
        | set(meta.agents)
        | set(meta.workflows)
        | set(meta.evals)
    )


def _walk_graph(
    root: type,
) -> tuple[list[type], dict[type, list[type]]]:
    """DFS from ``root``, resolving forwardRefs and detecting cycles.

    Returns
    -------
    module_order:
        Topological order, leaves first.
    resolved_imports:
        For each module, a list of its direct imports with all
        ``ForwardRef`` instances replaced by their resolved class.
        Stashed during the walk so subsequent phases don't re-call
        the thunks.
    """
    _ensure_module(root)

    module_order: list[type] = []
    state: dict[type, str] = {}  # module -> "visiting" | "done"
    path: list[type] = []
    resolved_imports: dict[type, list[type]] = {}

    def walk(mod: type) -> None:
        _ensure_module(mod)
        existing = state.get(mod)
        if existing == "done":
            return
        if existing == "visiting":
            cycle = " → ".join(m.__qualname__ for m in (*path, mod))
            raise CircularModuleImportError(f"Circular module import without forwardRef: {cycle}")
        state[mod] = "visiting"
        path.append(mod)

        meta = _meta(mod)
        resolved: list[type] = []
        for entry in meta.imports:
            target = entry.resolve() if isinstance(entry, ForwardRef) else entry
            _ensure_module(target)
            resolved.append(target)
            # Self-imports are always a bug — a module that imports itself
            # cannot be broken by forwardRef because the cycle is its own
            # provider graph, not a mutual dependency between distinct
            # modules.
            if target is mod:
                cycle = " → ".join(m.__qualname__ for m in (*path, mod))
                raise CircularModuleImportError(f"Module imports itself: {cycle}")
            # forwardRef breaks cycles between distinct modules: if we
            # already started visiting ``target`` and the edge is wrapped
            # in forwardRef, treat the edge as deferred and skip the
            # recursive descent.
            if isinstance(entry, ForwardRef) and state.get(target) == "visiting":
                continue
            walk(target)
        resolved_imports[mod] = resolved
        path.pop()
        state[mod] = "done"
        module_order.append(mod)

    walk(root)
    return module_order, resolved_imports


def _check_duplicates(module_order: list[type]) -> dict[type, type]:
    """Ensure no token is owned by two modules. Returns owner map."""
    owner: dict[type, type] = {}
    for mod in module_order:
        for token in _owned_tokens(_meta(mod)):
            previous = owner.get(token)
            if previous is not None and previous is not mod:
                raise DuplicateProviderError(
                    f"{token.__qualname__} is declared by both "
                    f"{previous.__qualname__} and {mod.__qualname__}. Only "
                    f"one module may own a provider; let the other module "
                    f"import the owner."
                )
            owner[token] = mod
    return owner


def _check_prepopulated_collisions(container: Container, owner: dict[type, type]) -> None:
    for token, mod in owner.items():
        if container.is_registered(token):
            raise DuplicateProviderError(
                f"Pre-populated container already has {token.__qualname__} "
                f"registered, but {mod.__qualname__} also declares it. The "
                f"pre-populated container does not bypass the graph's dedup "
                f"semantics; use a module that owns the alternative."
            )


def _compute_visibility(
    module_order: list[type], resolved_imports: dict[type, list[type]]
) -> dict[type, frozenset[type]]:
    """Per-module visibility = own + direct imports' exports + globals' exports."""
    globals_exports: set[type] = set()
    for mod in module_order:
        meta = _meta(mod)
        if meta.global_:
            globals_exports.update(meta.exports)

    visibility: dict[type, frozenset[type]] = {}
    for mod in module_order:
        meta = _meta(mod)
        own = _owned_tokens(meta)
        direct_exports: set[type] = set()
        for imp in resolved_imports[mod]:
            direct_exports.update(_meta(imp).exports)
        visibility[mod] = frozenset(own | direct_exports | globals_exports)
    return visibility


def _validate_visibility(module_order: list[type], visibility: dict[type, frozenset[type]]) -> None:
    for mod in module_order:
        for token in _owned_tokens(_meta(mod)):
            for dep in collect_di_deps(token):
                if dep not in visibility[mod]:
                    raise ModuleVisibilityError(
                        f"{token.__qualname__} (declared in "
                        f"{mod.__qualname__}) depends on {dep.__qualname__}, "
                        f"which is not visible from this module. Add an "
                        f"import of the module that exports it, mark that "
                        f"module global_=True, or move the dependency into "
                        f"this module."
                    )


_LEGAL_SCOPES: frozenset[Scope] = frozenset(("singleton", "request", "transient"))


def _register_providers(container: Container, module_order: list[type]) -> None:
    registered: set[type] = set()
    for mod in module_order:
        for token in _owned_tokens(_meta(mod)):
            if token in registered:
                continue
            raw_scope = getattr(token, "__ajolopy_scope__", "singleton")
            # AJ-9 stamps a legal scope; if some other attribute happens to
            # collide with our name we fall back to singleton rather than
            # propagating an opaque ``register`` error.
            scope: Scope = raw_scope if raw_scope in _LEGAL_SCOPES else "singleton"
            container.register(token, scope=scope)
            registered.add(token)


def _pack_compiled_module(container: Container, module_order: list[type]) -> CompiledModule:
    controllers: list[type] = []
    agents: list[type] = []
    workflows: list[type] = []
    evals: list[type] = []
    seen: set[type] = set()
    for mod in module_order:
        meta = _meta(mod)
        for token in meta.controllers:
            if token not in seen:
                controllers.append(token)
                seen.add(token)
        for token in meta.agents:
            if token not in seen:
                agents.append(token)
                seen.add(token)
        for token in meta.workflows:
            if token not in seen:
                workflows.append(token)
                seen.add(token)
        for token in meta.evals:
            if token not in seen:
                evals.append(token)
                seen.add(token)
    return CompiledModule(
        container=container,
        controllers=tuple(controllers),
        agents=tuple(agents),
        workflows=tuple(workflows),
        evals=tuple(evals),
        module_order=tuple(module_order),
    )


def compile_module(root: type, *, container: Container | None = None) -> CompiledModule:
    """Walk a ``@Module`` graph and produce a populated container.

    Parameters
    ----------
    root:
        The root ``@Module``-decorated class. Usually the
        application's ``AppModule``.
    container:
        Optional pre-built :class:`Container` to populate. Useful for
        tests that pre-seed mocks. If any token in the graph is already
        registered, raises :class:`DuplicateProviderError`.

    Returns
    -------
    :class:`CompiledModule`
        Frozen result containing the populated container, the flat
        lists of HTTP / AI primitives, and the dependency-first module
        order.

    Raises
    ------
    NotAModuleError
        ``root`` (or any import in the graph) is not ``@Module``-decorated.
    CircularModuleImportError
        Non-``forwardRef`` cycle in the import graph.
    UnresolvedForwardRefError
        A ``forwardRef`` thunk raised, returned a non-module, or
        returned another ``forwardRef``.
    DuplicateProviderError
        The same token is owned by two modules (or collides with the
        pre-populated container).
    ModuleVisibilityError
        A provider's ``__init__`` depends on a token outside its
        module's visibility set.
    """
    module_order, resolved_imports = _walk_graph(root)
    owner = _check_duplicates(module_order)

    if container is None:
        container = Container()
    else:
        _check_prepopulated_collisions(container, owner)

    visibility = _compute_visibility(module_order, resolved_imports)
    _validate_visibility(module_order, visibility)
    _register_providers(container, module_order)
    return _pack_compiled_module(container, module_order)
