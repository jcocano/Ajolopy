"""Provider registry + model-string router.

Two cooperative tables, both populated at process startup:

- ``_PROVIDERS`` — provider key (``"anthropic"``, ``"openai"``, …) → registered
  ``LLMProvider`` subclass.
- ``_ROUTES`` — ordered list of ``(pattern, provider_key)`` pairs. Patterns
  use ``fnmatch`` syntax. The most recently appended rule wins, so users can
  override a default by calling ``register_route`` after import.

Concrete providers live in sibling packages (AJ-19/20/21/22) and call
``register_provider`` once at import time. The default route table covers the
four v0.1 provider families even before any concrete provider class is
imported, so ``resolve_provider`` returns a stable key as soon as this module
is loaded.
"""

import fnmatch

from .base import LLMProvider


class ProviderNotRegisteredError(KeyError):
    """A provider key was looked up but no class is registered under it."""


class UnknownModelError(ValueError):
    """A model string did not match any registered routing pattern."""


_PROVIDERS: dict[str, type[LLMProvider]] = {}
_ROUTES: list[tuple[str, str]] = []


_DEFAULT_ROUTES: list[tuple[str, str]] = [
    ("claude-*", "anthropic"),
    ("gpt-*", "openai"),
    ("o1-*", "openai"),
    ("o3-*", "openai"),
    ("text-embedding-3*", "openai"),
    ("gemini-*", "gemini"),
    ("ollama:*", "universal-openai"),
    ("groq:*", "universal-openai"),
    ("together:*", "universal-openai"),
    ("mistral:*", "universal-openai"),
    ("deepseek:*", "universal-openai"),
    ("openrouter:*", "universal-openai"),
    ("azure:*", "universal-openai"),
]


def _seed_default_routes() -> None:
    _ROUTES.extend(_DEFAULT_ROUTES)


_seed_default_routes()


def register_provider(
    key: str,
    cls: type[LLMProvider],
    *,
    overwrite: bool = False,
) -> None:
    """Register a provider class under ``key``.

    Raises ``TypeError`` if ``cls`` is not an ``LLMProvider`` subclass, and
    ``ValueError`` if ``key`` is already taken and ``overwrite`` is ``False``.
    Re-registration must be explicit so concurrent imports of two libraries
    that both want the same key fail loudly instead of silently shadowing.
    """
    # Defensive runtime check — callers that bypass the type signature still
    # get a clear error instead of a TypeError raised inside the registry dict.
    if not isinstance(cls, type) or not issubclass(cls, LLMProvider):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"register_provider(key={key!r}): cls must be an LLMProvider subclass, got {cls!r}."
        )
    if key in _PROVIDERS and not overwrite:
        raise ValueError(
            f"register_provider({key!r}): key already registered to "
            f"{_PROVIDERS[key].__name__}. Pass overwrite=True to replace."
        )
    _PROVIDERS[key] = cls


def get_provider_class(key: str) -> type[LLMProvider]:
    """Look up the provider class registered under ``key``.

    Raises ``ProviderNotRegisteredError`` naming the known keys if missing.
    """
    try:
        return _PROVIDERS[key]
    except KeyError as exc:
        known = sorted(_PROVIDERS.keys())
        raise ProviderNotRegisteredError(
            f"No provider registered for key {key!r}. Known keys: {known!r}"
        ) from exc


def register_route(pattern: str, key: str) -> None:
    """Append a routing rule. Matched in reverse order — most recent wins."""
    _ROUTES.append((pattern, key))


def resolve_provider(model: str) -> str:
    """Map a model string to a provider key via the routing table.

    Iterates ``_ROUTES`` in reverse insertion order so user-registered rules
    override defaults. Raises ``UnknownModelError`` listing the known prefix
    patterns when nothing matches.
    """
    for pattern, key in reversed(_ROUTES):
        if fnmatch.fnmatchcase(model, pattern):
            return key
    known_patterns = sorted({pattern for pattern, _ in _ROUTES})
    raise UnknownModelError(
        f"Model {model!r} matches no registered provider prefix. "
        f"Supported patterns: {known_patterns!r}"
    )
