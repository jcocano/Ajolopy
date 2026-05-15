"""Internal helpers shared by every :class:`Retriever` backend.

The retrievers all need the same two services:

1. Resolve an ``embedding_model`` string to a concrete
   :class:`~ajolopy.providers.LLMProvider` instance (so ``provider.embed``
   can be called).
2. Pick a default embedding dimension when the caller did not supply
   one — the v0.1 backends need the dim at collection-create / table-
   create time, before any embedding has been computed.

Both helpers live in a sibling module (not on the ``Retriever`` ABC) so
the public surface stays the three abstract methods the spec promises.
"""

from ajolopy.providers import (
    LLMProvider,
    ProviderNotRegisteredError,
    UnknownModelError,
    get_provider_class,
    resolve_provider,
)

from .errors import RetrieverConfigError, RetrieverRuntimeError

# Default vector dimensions for the v0.1-supported embedding models.
# Backends consult this table when the caller did not pass an explicit
# ``embedding_dim`` so collection / table creation can run before the
# first ``embed`` call. Unlisted models force the caller to pass
# ``embedding_dim=`` explicitly so collection setup stays deterministic.
_DEFAULT_EMBEDDING_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def default_embedding_dim(model: str) -> int | None:
    """Return the documented vector dimension for ``model`` (or ``None``).

    Returning ``None`` is the signal "we do not know — make the caller
    pass ``embedding_dim`` explicitly". Backends raise
    :class:`RetrieverConfigError` from their constructors in that case.
    """
    return _DEFAULT_EMBEDDING_DIMS.get(model)


def resolve_embedding_provider(embedding_model: str) -> LLMProvider:
    """Instantiate the :class:`LLMProvider` that owns ``embedding_model``.

    Wraps :func:`ajolopy.providers.resolve_provider` +
    :func:`get_provider_class` so retriever callers get a uniform
    :class:`RetrieverConfigError` instead of two different exception
    types from the registry. Instantiation failure becomes
    :class:`RetrieverRuntimeError` so the retriever's call sites can
    catch a single base class.
    """
    try:
        key = resolve_provider(embedding_model)
    except UnknownModelError as exc:
        raise RetrieverConfigError(
            f"Unknown embedding model {embedding_model!r}: {exc}. "
            f"Register a routing prefix via "
            f"``ajolopy.providers.register_route``."
        ) from exc
    try:
        cls = get_provider_class(key)
    except ProviderNotRegisteredError as exc:
        raise RetrieverConfigError(
            f"Provider {key!r} is registered as a routing target but no "
            f"concrete LLMProvider class is bound. Import the matching "
            f"``ajolopy.providers.*`` package."
        ) from exc
    try:
        return cls()
    except Exception as exc:
        raise RetrieverRuntimeError(
            f"Failed to instantiate provider {key!r} for embedding model {embedding_model!r}: {exc}"
        ) from exc


__all__ = ["default_embedding_dim", "resolve_embedding_provider"]
