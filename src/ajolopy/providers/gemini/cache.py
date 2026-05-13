"""Cache lifecycle building blocks for ``GeminiProvider``.

Gemini's Context Caching is a stateful server-side resource lifecycle:
callers issue ``client.aio.caches.create(...)`` ahead of time, reference
the returned cache name on subsequent ``generate_content`` calls via
``GenerateContentConfig.cached_content``, and explicitly
``client.aio.caches.delete(name)`` when they are done. The framework's
shared ``cache: bool`` flag on ``LLMProvider`` does not capture any of
that, so AJ-58 introduces a small per-provider state machine that the
caller opts into via the ``cache_strategy="auto"`` constructor kwarg.

This module owns the lifecycle's stateless building blocks:

- The literal types describing the constructor knobs.
- The default ``prefix_hash`` cache-key derivation function.
- The in-memory registry that maps a derived *cache key* to the
  server-assigned *cache name* for the provider's lifetime.

All policy decisions (when to gate on the token minimum, when to recreate
on a 404, when to delete on shutdown) live in ``provider.py`` so this
module stays trivially testable.

The TTL is converted to the SDK's duration-string form at the call site
(``f"{cache_ttl_seconds}s"``) — the SDK accepts the ``ttl`` config field
as a string like ``"3600s"`` rather than an integer.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ajolopy.providers.types import Message

CacheStrategy = Literal["off", "auto"]
"""Master switch for the caching lifecycle. ``"off"`` (default) makes
``GeminiProvider`` behave identically to the AJ-21 release; ``"auto"``
activates create / reuse / recreate-on-expired / delete-on-close."""

CacheKeyStrategyName = Literal["prefix_hash"]
"""Built-in key-derivation strategies. ``"prefix_hash"`` is the only
v0.1 option; callers needing something else pass a ``Callable``."""

CacheKeyCallable = Callable[[list[Message], str | None], str]
"""Escape-hatch signature for caller-supplied key derivation. Receives
``(messages, system_instruction)`` and must return a non-empty string."""

CacheKeyStrategy = CacheKeyStrategyName | CacheKeyCallable
"""Either the ``"prefix_hash"`` literal or a custom callable."""

CacheOnExpired = Literal["recreate", "error"]
"""Policy for handling a 404 on the cached-content reference. ``"recreate"``
transparently recreates the cache and retries once (only on
``complete()``; ``stream()`` cannot replay yielded deltas, see the spec).
``"error"`` always surfaces ``GeminiCacheExpiredError``."""

CacheCleanup = Literal["manual", "on_provider_close"]
"""Policy for deleting tracked caches at shutdown. ``"on_provider_close"``
pairs with the provider's ``aclose()`` / async-context-manager protocol;
``"manual"`` leaves cache deletion entirely to the caller."""


def prefix_hash_cache_key(messages: list[Message], system_instruction: str | None) -> str:
    """Default cache-key derivation — SHA-256 over ``system + first user msg``.

    Two requests that share the same system instruction and same first
    user message share a cache; everything else is per-prefix. The first
    user message is conventionally where the "load my context" payload
    sits (long document, code dump, retrieval result), so this captures
    the 90% case without forcing the caller to think about cache identity.

    Hashing collapses the prefix to a short stable string suitable for
    use as a dict key in the in-memory registry.
    """
    first_user_content = ""
    for msg in messages:
        if msg.role == "user":
            first_user_content = msg.content
            break
    payload = (system_instruction or "") + "\n\n" + first_user_content
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CacheRegistry:
    """In-memory mapping of *cache key* → server-assigned *cache name*.

    Holds the names of every cache the provider has successfully created
    in the current process. Concurrency note (per spec): no internal
    locking. A race between two coroutines deriving the same key issues
    two ``caches.create`` calls; both names get tracked so the cleanup
    path can delete both. The marginal cost is at most one wasted create
    per race — acceptable for keeping the hot path lock-free.

    ``names_for(key)`` returns every name registered for a given key so
    callers do not need to know whether a race happened. The latest entry
    is the one used for subsequent ``cached_content`` references.
    """

    _by_key: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    def register(self, key: str, name: str) -> None:
        """Track a freshly created cache name under its derivation key."""
        self._by_key.setdefault(key, []).append(name)

    def latest(self, key: str) -> str | None:
        """Return the most recently registered cache name for ``key``."""
        entries = self._by_key.get(key)
        if not entries:
            return None
        return entries[-1]

    def names_for(self, key: str) -> list[str]:
        """Return every tracked cache name for ``key`` (oldest first)."""
        return list(self._by_key.get(key, []))

    def drop_name(self, key: str, name: str) -> None:
        """Remove a single cache name from the registry under ``key``.

        Used by the expiry-recreate path after a 404 — the stale cache
        name is dropped so subsequent lookups go through the recreate
        flow rather than reusing the dead name.
        """
        entries = self._by_key.get(key)
        if not entries:
            return
        with_removed = [n for n in entries if n != name]
        if with_removed:
            self._by_key[key] = with_removed
        else:
            del self._by_key[key]

    def snapshot(self) -> list[tuple[str, str]]:
        """Return ``[(key, name), ...]`` over every tracked cache name.

        Used by the cleanup path so ``aclose()`` can iterate without
        holding a reference to the live registry while it awaits each
        delete call. A caller mutating the registry mid-iteration does
        not affect this snapshot.
        """
        return [(key, name) for key, names in self._by_key.items() for name in names]

    def clear(self) -> None:
        """Empty the registry. Idempotent — calling on an empty registry
        is a no-op."""
        self._by_key.clear()

    def is_empty(self) -> bool:
        return not self._by_key
