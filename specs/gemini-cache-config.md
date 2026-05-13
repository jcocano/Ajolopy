# AJ-58 — Configurable cache lifecycle for Gemini

> Tracked in [`board.json`](../board.json) as `AJ-58`. Status, owner,
> branch, and dependencies live there — do not duplicate them in this
> file.
>
> Source of truth for the design: Brief v4.0 §03 (multi-provider — Gemini
> entry) + Google's official Context Caching documentation for the
> `google-genai` SDK. If this file ever conflicts with the Brief or with
> Google's API contract, those win.

## What

AJ-58 adds a configurable Context Caching lifecycle to `GeminiProvider`
(shipped by AJ-21). The default behaviour matches Google's
recommendation — **no implicit caching** — so the provider feels
identical to AJ-21 unless the caller explicitly opts in. The opt-in
unlocks a full lifecycle (create / reuse / extend / expire / delete) with
every parameter (TTL, minimum tokens, cache key derivation, expiry
handling, cleanup policy) exposed as a constructor kwarg.

This item exists because the `cache: bool = False` flag the `LLMProvider`
ABC shares across vendors does not map cleanly onto Gemini's API. Google
requires explicit `caches.create(...)` and `caches.delete(...)` calls and
deliberately leaves cache identity, TTL, and cleanup as **the
application's responsibility**. Forcing an implicit mapping behind
`cache=True` without surfacing those knobs would be fighting the API and
locking the framework into 6 design decisions that Google explicitly does
not make for users.

AJ-58 ships:

1. A configurable cache strategy on `GeminiProvider`'s constructor
   (~6 kwargs, all with Google-honest defaults).
2. The `cache=True` code path on `complete()` / `stream()` for the
   opt-in case (auto-create, reuse, recreate-on-expired).
3. Cleanup hooks (`provider.aclose()` and async context manager support)
   for the `cache_cleanup="on_provider_close"` strategy.
4. Tests covering the lifecycle in every mode.

AJ-58 does **not** ship:

- A cross-provider cache abstraction (Anthropic / OpenAI keep their own
  semantics; the abstraction layer is a separate, post-v0.1 conversation).
- A persistent cache store (caches are server-side at Google; the
  framework holds only the cache name in-memory for the provider's
  lifetime).

## Why

The user choice on AJ-21 was to ship the provider mechanically (no
caching) and follow it with a focused item — this one — that thinks
through the cache lifecycle properly. Splitting the work has two
benefits:

1. **AJ-21 stays mechanical.** Three native providers (Anthropic /
   OpenAI / Gemini) all look like sibling implementations of the same
   ABC. No vendor-specific surface leaks into AJ-21's spec.

2. **AJ-58 gets the design attention Context Caching deserves.** Google's
   API is intentionally opinionated; honouring those opinions means
   surfacing six knobs that other vendors don't have. Doing this in a
   dedicated PR is cleaner than smuggling them into the provider PR.

## Public surface (v0.1)

### Constructor — new kwargs

```python
from collections.abc import Callable
from typing import Literal

from ajolopy.providers.gemini import GeminiProvider

# Default behaviour — no auto-cache, no kwargs needed.
provider = GeminiProvider()
# cache=True on complete()/stream() remains a no-op.
# supports_prompt_caching() returns False.

# Opt-in — full auto lifecycle with all the knobs visible.
provider = GeminiProvider(
    cache_strategy="auto",
    cache_ttl_seconds=3600,
    cache_min_tokens=1024,
    cache_key_strategy="prefix_hash",
    cache_on_expired="recreate",
    cache_cleanup="on_provider_close",
)
# Now cache=True creates/reuses caches automatically.
# supports_prompt_caching() returns True.

# Custom cache key derivation (escape hatch for the key strategy).
def my_cache_key(messages: list[Message], system: str | None) -> str:
    # caller-driven, e.g. derived from a session id
    return f"session:{messages[0].name}"

provider = GeminiProvider(
    cache_strategy="auto",
    cache_key_strategy=my_cache_key,
)
```

### Constructor signature

```python
type CacheStrategy = Literal["off", "auto"]
type CacheKeyStrategyName = Literal["prefix_hash"]
type CacheKeyStrategy = (
    CacheKeyStrategyName | Callable[[list[Message], str | None], str]
)
type CacheOnExpired = Literal["recreate", "error"]
type CacheCleanup = Literal["manual", "on_provider_close"]


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: "genai.Client | None" = None,
        # AJ-58 — caching kwargs (all default to "off" / safe values)
        cache_strategy: CacheStrategy = "off",
        cache_ttl_seconds: int = 3600,
        cache_min_tokens: int = 1024,
        cache_key_strategy: CacheKeyStrategy = "prefix_hash",
        cache_on_expired: CacheOnExpired = "recreate",
        cache_cleanup: CacheCleanup = "on_provider_close",
    ) -> None: ...

    async def aclose(self) -> None: ...
    async def __aenter__(self) -> "GeminiProvider": ...
    async def __aexit__(self, *_: object) -> None: ...
```

### Errors

```python
class GeminiCacheError(GeminiProviderError): ...
class GeminiCacheMinTokensError(GeminiCacheError): ...    # content below cache_min_tokens
class GeminiCacheExpiredError(GeminiCacheError): ...      # only raised when cache_on_expired="error"
class GeminiCacheCreateError(GeminiCacheError): ...       # SDK rejects caches.create
```

## Design rules

- **Magical default**: `GeminiProvider()` (no caching kwargs) behaves
  identically to AJ-21's release — `cache=True` is a documented no-op,
  capability flag is `False`. No surprise behaviour for callers who don't
  ask for caching.
- **Opt-in escape hatch**: pass `cache_strategy="auto"` and the
  provider activates the full lifecycle. Every other knob has a default
  matching Google's documented best practice (1h TTL, 1024-token minimum
  for Flash-class models, prefix-hash key derivation, transparent
  recreate on expiry, cleanup on provider close).
- **Honest capability flag**: `supports_prompt_caching()` returns the
  effective state of the provider — `True` when `cache_strategy="auto"`,
  `False` when `"off"`. The framework can introspect this to decide
  whether to set `cache=True` on the wire call.
- **Cache identity is application-controlled.** Google does not impose a
  cache key concept; the framework's `prefix_hash` strategy is a
  pragmatic default (hash of the joined system instruction + first user
  message), but the escape hatch is a `Callable[(messages, system), str]`
  so apps can derive cache identity from session ids, document hashes,
  whatever fits their domain.
- **Below-minimum content is loud.** If `cache=True` is requested but the
  computed token count is below `cache_min_tokens`, raise
  `GeminiCacheMinTokensError` with the actual count, the threshold, and
  the offending request. Silently degrading to no-cache hides bugs. The
  token count is obtained by calling the provider's own
  `count_tokens(model=..., text=<joined system + first user message>)`;
  if that call falls back to its estimate (running loop / SDK failure),
  the estimate is used as-is — we never gate caching on a second SDK
  round-trip.
- **Expired-cache handling is configurable.** Default `"recreate"`:
  catch the SDK's 404 on the second call, transparently call
  `caches.create(...)` again, retry once, surface success to the caller.
  Alternative `"error"`: raise `GeminiCacheExpiredError` and let the
  caller decide.
- **Cleanup is best-effort.** `cache_cleanup="on_provider_close"`
  iterates the in-memory cache name registry and calls
  `caches.delete(name)` for each one inside `aclose()`. Failures are
  logged at WARNING level but do not raise — provider shutdown should
  not abort because a server-side cache had already expired naturally.
- **No persistence.** The cache name registry lives in the provider
  instance only. Two `GeminiProvider` instances in the same process do
  not share cache identity; this is intentional (per-provider scope
  matches per-test isolation and per-container DI scope semantics).

- **`aclose()` is provider-specific, not on the ABC.** The
  `LLMProvider` ABC (AJ-18) does not declare `aclose()` or the async
  context manager protocol. AJ-58 adds them only to `GeminiProvider`
  because only Gemini has server-side state (the cache resources) that
  the framework opted to manage. Anthropic and OpenAI providers remain
  stateless. If a future item generalises shutdown across providers,
  promote `aclose()` to the ABC in that item; do not retroactively
  edit AJ-18.

## Open design decisions (please confirm before implementation)

1. **`cache_strategy` is the master switch; default is `"off"`.** Three
   reasons:
   - Matches Google's recommended posture (no implicit caching).
   - Guarantees backwards-compat with AJ-21 (which ships `"off"`-equivalent
     behaviour).
   - Lets us advertise `supports_prompt_caching()` honestly per instance.

   **Agreed?**

2. **`cache_ttl_seconds=3600` is the default.** Google's SDK default is
   also 60 minutes. Power users can extend per-call via a future
   `caches.update(name, ttl=...)` hook, but v0.1 keeps the TTL fixed at
   construction time. **Agreed?**

3. **`cache_min_tokens=1024` is the default.** Matches the Flash-class
   threshold. Pro-class models require ~4096 tokens for caching; users
   targeting Pro should override at construction time. We pick the lower
   default because rejecting too-small content with a typed error is
   actionable; rejecting Flash-sized content with the Pro threshold
   would surprise the majority of callers. **Agreed?**

4. **`cache_key_strategy="prefix_hash"` is the default.** Hash of
   `(system_instruction or "") + "\n\n" + messages[0].content`. The
   first user message is usually where the "load my context" payload
   sits (long document, codebase, retrieval result). If two requests
   share that prefix, they share the cache. Escape hatch: pass a
   `Callable` and you own the key. **Agreed?**

5. **`cache_on_expired="recreate"` is the default.** TTL expiry inside
   a session is a recoverable hiccup, not a user-facing error. The
   alternative (`"error"`) is available for callers that want strict
   semantics. **Agreed?**

6. **`cache_cleanup="on_provider_close"` is the default.** Pairs with
   the new `aclose()` / async-context-manager protocol on the provider.
   In an Ajolopy app the provider is a DI singleton, so its `aclose()`
   fires in AJ-13's `on_app_shutdown` hook chain — caches get cleaned
   up at app shutdown automatically. Manual mode is for callers who
   want full control. **Agreed?**

7. **Concurrency: no internal lock; first-call-wins per-key.** If two
   coroutines call `complete(..., cache=True)` with the same derived
   key before the first cache is created, both will issue
   `caches.create()` calls. Google's API tolerates this — the second
   create returns a different cache name with the same content, and the
   framework simply stores both names in the registry. Cleaner than
   serialising every cache-eligible call behind a per-key lock; the
   marginal cost is one wasted `caches.create()` call per race, which
   is an acceptable trade for keeping the hot path lock-free.
   **Agreed?** (Alternative: per-key `asyncio.Lock` in the registry;
   ~+15 LOC.)

## Out of scope for this item

- Cross-provider cache abstraction in `LLMProvider`. Anthropic /
  OpenAI / Gemini cache semantics are too different in v0.1 to unify
  behind a single abstract method. Revisit post-v0.1 if a user
  workflow demands cross-vendor caching.
- Cache pre-warming (creating a cache outside a `complete()` call so
  the first real request hits a populated cache). Easy to add later as
  `provider.create_cache(content=..., ttl=...) -> CacheHandle`; not
  needed for the implicit `cache=True` flow.
- TTL extension mid-session (`caches.update(name, ttl=...)`). The
  default 1h is enough for v0.1's killer-demo arc; longer sessions
  open the dynamic TTL conversation in a follow-up.
- Cache observability (OTel spans annotating cache hit / miss /
  recreate). AJ-28's framework-wide observability item lands first;
  AJ-58's cache events plug into whatever span shape AJ-28 establishes.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All tests mock the `google-genai` SDK boundary
(`client.aio.caches.create`, `client.aio.caches.delete`, and the
`generate_content` calls that reference `config.cached_content`).

### Constructor — defaults

- [ ] `GeminiProvider()` (no caching kwargs) behaves identically to the
      AJ-21 release — `cache=True` is a no-op,
      `supports_prompt_caching()` returns `False`, no
      `caches.create` calls are made.
- [ ] Passing `cache_strategy="auto"` flips
      `supports_prompt_caching()` to `True`.
- [ ] All six caching kwargs default to the documented values.
- [ ] `cache_ttl_seconds=0` or a negative value raises `ValueError` at
      construction time naming the offending kwarg. Same for
      `cache_min_tokens <= 0`.

### `cache_strategy="auto"` — happy path

- [ ] First `complete(..., cache=True)` with content above
      `cache_min_tokens` triggers `client.aio.caches.create(...)` with
      the configured TTL and the derived cache name.
- [ ] Subsequent `complete(..., cache=True)` with the same derived key
      reuses the existing cache name via `config.cached_content` — no
      new `caches.create` call.
- [ ] `stream(..., cache=True)` exercises the same lifecycle as
      `complete()` (cache reused across complete and stream calls if
      keys match).

### Cache key strategy

- [ ] Default `"prefix_hash"` derives the key from
      `system_instruction + "\n\n" + first user message.content`. Two
      requests with the same prefix share a cache; two requests with
      different prefixes get separate caches.
- [ ] Callable strategy is invoked with `(messages, system_instruction)`
      and its return value is used as the cache identity verbatim.
- [ ] A callable strategy that raises surfaces the exception as
      `GeminiCacheError` with the original chained.
- [ ] A callable strategy that returns a falsy value (`""`, `None`,
      `0`) raises `GeminiCacheError` naming the strategy and the
      offending return value. Empty cache keys collide silently in the
      registry, so we refuse to accept them.

### Cache minimum tokens

- [ ] `complete(..., cache=True)` with content below `cache_min_tokens`
      raises `GeminiCacheMinTokensError` with the actual count, the
      threshold, and a hint pointing to the constructor kwarg.
- [ ] The error fires *before* any `caches.create` SDK call.

### Expiry handling

- [ ] `cache_on_expired="recreate"` (default): when a `generate_content`
      call returns a 404 referencing the cached content, the provider
      transparently calls `caches.create` again, retries once, and
      returns success. Verified by mock + counting SDK invocations.
- [ ] `cache_on_expired="error"`: the same 404 surfaces as
      `GeminiCacheExpiredError` with the cache name in the message; no
      retry happens.
- [ ] Recreate failures (the second `caches.create` also fails) surface
      as `GeminiCacheCreateError` regardless of `cache_on_expired`.
- [ ] Streaming + cache expiry: when a `stream(..., cache=True)` call
      encounters the 404 mid-iteration, the iterator surfaces
      `GeminiCacheExpiredError` on the offending step **regardless** of
      `cache_on_expired`. Recreate-on-expired only applies to
      `complete()`; replaying already-yielded stream deltas after a
      transparent recreate is not possible without buffering the whole
      output, which we refuse to do. The error message points callers
      to retry the stream as a fresh call.

### Cleanup

- [ ] `cache_cleanup="on_provider_close"` (default): `await provider.aclose()`
      iterates the cache registry and calls
      `client.aio.caches.delete(name)` for each entry. The registry
      empties after `aclose`.
- [ ] `cache_cleanup="manual"`: `aclose()` does not delete any caches;
      the registry persists until the provider is garbage-collected.
- [ ] A `caches.delete` failure during cleanup logs at WARNING and does
      not raise. Other entries are still cleaned up.
- [ ] `async with GeminiProvider(cache_strategy="auto") as provider:`
      drives `aclose` on exit (`__aenter__` returns `self`,
      `__aexit__` calls `aclose`).
- [ ] Calling `aclose()` twice is idempotent — the second call is a
      no-op (registry already empty, no SDK calls). No exception
      raised.
- [ ] `aclose()` invoked while a `complete(..., cache=True)` call is
      in flight does not abort the in-flight call. Cleanup observes
      whatever caches exist in the registry at the moment of the
      `aclose` call; caches added afterwards survive until garbage
      collection. Verified with an `asyncio.gather` test that runs
      `aclose()` and a slow `complete` in parallel.

### Capability flag

- [ ] `supports_prompt_caching()` returns `False` when
      `cache_strategy="off"`.
- [ ] `supports_prompt_caching()` returns `True` when
      `cache_strategy="auto"`.

### Concurrency

- [ ] Two concurrent `asyncio.Task`s calling
      `complete(..., cache=True)` with the same derived key issue two
      independent `caches.create` calls (verified by SDK call count).
      Both calls succeed and each call returns a `Response`. The
      registry ends with both cache names tracked.

## Implementation pointers

- Source: extend `src/ajolopy/providers/gemini/` (no new package).
  - `provider.py` — add caching-related methods + the lifecycle code
    path inside `complete()` / `stream()`.
  - `cache.py` (new) — `CacheStrategy` literal + the prefix-hash key
    function + the in-memory cache registry dataclass.
  - `errors.py` — add the four new error classes listed above.
- Tests: extend `tests/providers/gemini/`. New file
  `test_cache_lifecycle.py` covers every acceptance criterion.
- Runtime deps: none new. `google-genai` already covers the
  `caches.create` / `caches.delete` SDK surface.
- Naming: `aclose` follows the `asyncio` stdlib convention
  (`asyncio.StreamWriter.aclose()`, `httpx.AsyncClient.aclose()`); the
  async-context-manager pair is a small but conventional addition.
- The cache registry is a `dict[str, str]` mapping
  *cache key* → *server-assigned cache name*. Threading safety is not
  a concern: every `GeminiProvider` is constructed inside a single
  `asyncio` event loop in the framework's bootstrap, and the registry
  is mutated only inside `await` points. If a thread-unsafe scenario
  surfaces post-v0.1, wrap the registry in `asyncio.Lock`.
- TTL on the SDK boundary: `client.aio.caches.create(...)` accepts
  `ttl` as a duration string like `"3600s"`. Convert
  `cache_ttl_seconds: int` to `f"{cache_ttl_seconds}s"` at the call
  site. Document the choice in `cache.py`.
- Two `GeminiProvider` instances that share the **same** `genai.Client`
  (passed via the `client=` kwarg) keep independent in-memory cache
  registries; the server-side `cachedContents/*` resources are shared
  across both because they live in the Google project, not in the
  client. This is intentional — if a caller wants two isolated
  providers, they should construct two independent clients. Documented
  here as an integration note for tests that instantiate provider
  pairs.

## Implementation notes

<!-- Filled during implementation. Capture scope decisions taken at
write time, edge-case findings, coverage numbers, and any test-only
quirks. -->
