"""``@Module(...)`` decorator + frozen ``ModuleMetadata`` schema.

The decorator stamps a single private attribute (``_ajolopy_module``) on
the target class. The class body is otherwise untouched — modules are
metadata containers, not instances. The compiler (in ``compiler.py``)
consumes this attribute when walking the import graph.

All eight kwargs are keyword-only; omitted lists collapse to empty
tuples (frozen for safety — modifying ``MyModule._ajolopy_module.providers``
must not affect the source declaration).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import ModuleConfigError
from .forward_ref import ForwardRef

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    """Frozen snapshot of a ``@Module(...)`` declaration.

    Lives on the decorated class under ``_ajolopy_module``. Tuples
    rather than lists so introspection cannot mutate the original
    declaration.
    """

    imports: tuple[type | ForwardRef, ...]
    providers: tuple[type, ...]
    controllers: tuple[type, ...]
    agents: tuple[type, ...]
    workflows: tuple[type, ...]
    evals: tuple[type, ...]
    exports: tuple[type, ...]
    global_: bool


def _validate_type_list(
    name: str,
    items: list[Any] | None,
    *,
    allow_forward_ref: bool = False,
) -> tuple[Any, ...]:
    """Validate a kwarg list contains only ``type`` (and optionally
    ``ForwardRef`` for ``imports=``), returning it as a frozen tuple."""
    if items is None:
        return ()
    if not isinstance(items, list):  # pyright: ignore[reportUnnecessaryIsInstance]
        # Runtime guard — callers can pass any value despite the type hint.
        raise ModuleConfigError(
            f"@Module(..., {name}=...) must be a list, got {type(items).__name__}"
        )
    for index, entry in enumerate(items):
        if allow_forward_ref and isinstance(entry, ForwardRef):
            continue
        if not isinstance(entry, type):
            label = "type" if not allow_forward_ref else "type or forwardRef(...)"
            raise ModuleConfigError(
                f"@Module(..., {name}=[..., {entry!r}, ...]) at index {index}: "
                f"expected a {label}, got {type(entry).__name__}"
            )
    return tuple(items)


def Module(  # noqa: N802 — Brief locks the decorator name as ``Module``
    *,
    imports: list[type | ForwardRef] | None = None,
    providers: list[type] | None = None,
    controllers: list[type] | None = None,
    agents: list[type] | None = None,
    workflows: list[type] | None = None,
    evals: list[type] | None = None,
    exports: list[type] | None = None,
    global_: bool = False,
) -> Callable[[type], type]:
    """Mark a class as an Ajolopy module.

    Composition kwargs (all keyword-only):

    - ``imports``: other ``@Module``-decorated classes (and/or
      ``forwardRef(lambda: ...)`` sentinels for circular references)
      whose exports are visible inside this module.
    - ``providers``: classes the container resolves inside this module.
      Listed once; declaring the same class in two modules raises
      :class:`DuplicateProviderError` at compile time.
    - ``controllers`` / ``agents`` / ``workflows`` / ``evals``: classes
      that act as the AI / HTTP primitives of the module. Each is also
      registered into the container as a singleton provider; overlap
      with ``providers=`` is deduped silently.
    - ``exports``: subset of ``providers=`` that becomes visible to
      modules importing this one. Lists that are not also in
      ``providers=`` raise :class:`ModuleConfigError` at decoration
      time. Re-exporting another module (``exports=[OtherModule]``) is
      not supported.
    - ``global_``: when ``True``, every provider in ``exports=`` becomes
      visible to every module in the graph without an explicit
      ``imports=`` entry. Useful for ``ConfigModule`` / ``LoggerModule``
      cross-cutting concerns.

    Returns the class unchanged after stamping a single private
    attribute (``_ajolopy_module``).
    """
    imports_t = _validate_type_list("imports", imports, allow_forward_ref=True)
    providers_t = _validate_type_list("providers", providers)
    controllers_t = _validate_type_list("controllers", controllers)
    agents_t = _validate_type_list("agents", agents)
    workflows_t = _validate_type_list("workflows", workflows)
    evals_t = _validate_type_list("evals", evals)
    exports_t = _validate_type_list("exports", exports)

    if not isinstance(global_, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        # Runtime guard — callers may pass any value despite the type hint.
        raise ModuleConfigError(
            f"@Module(..., global_=...) must be a bool, got {type(global_).__name__}"
        )

    metadata = ModuleMetadata(
        imports=imports_t,
        providers=providers_t,
        controllers=controllers_t,
        agents=agents_t,
        workflows=workflows_t,
        evals=evals_t,
        exports=exports_t,
        global_=global_,
    )

    # Exports must reference providers the module owns. The compiler will
    # also dedup overlap between ``providers=`` and the AI / controllers
    # lists; here we only validate the exports invariant because it is
    # purely declarative.
    owned = set(providers_t) | set(controllers_t) | set(agents_t) | set(workflows_t) | set(evals_t)
    for token in exports_t:
        if token not in owned:
            raise ModuleConfigError(
                f"@Module(..., exports=[{token.__qualname__}]) is not in this "
                f"module's providers/controllers/agents/workflows/evals. "
                f"Re-exporting imported modules is not supported in v0.1; "
                f"import the owning module directly from the consumer."
            )

    def decorator(cls: type) -> type:
        # ``_ajolopy_module`` is *not* inherited: a subclass needs its own
        # @Module decorator to count as a module. We detect re-decoration
        # by checking the class's own __dict__, not getattr (which would
        # walk the MRO and reject a legitimate ``class B(A): ...`` where
        # ``A`` is already a module).
        if "_ajolopy_module" in cls.__dict__:
            raise ModuleConfigError(
                f"@Module(...) re-applied to {cls.__qualname__}; the class is "
                f"already decorated as a module."
            )
        cls._ajolopy_module = metadata
        return cls

    return decorator
