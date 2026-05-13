"""Tests for AJ-58 — configurable cache lifecycle on ``GeminiProvider``.

Every acceptance criterion in ``specs/gemini-cache-config.md`` has at
least one corresponding test here. The ``google-genai`` SDK boundary
(``client.aio.caches.create``, ``client.aio.caches.delete``, and the
``generate_content`` / ``generate_content_stream`` calls that reference
``config.cached_content``) is mocked through ``AsyncMock`` shims; no
real network traffic happens in CI.
"""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from ajolopy.providers import Message
from ajolopy.providers.gemini import (
    GeminiCacheCreateError,
    GeminiCacheError,
    GeminiCacheExpiredError,
    GeminiCacheMinTokensError,
    GeminiProvider,
    GeminiProviderError,
)
from ajolopy.providers.gemini.cache import prefix_hash_cache_key

from .conftest import (
    _AsyncStreamIterator,
    make_async_client,
    make_generate_response,
    make_stream_chunk,
)


def _install_caches_mocks(
    client: MagicMock,
    *,
    create_return: Any | None = None,
    create_side_effect: BaseException | list[BaseException | Any] | None = None,
    delete_side_effect: BaseException | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    """Attach ``aio.caches.create`` and ``aio.caches.delete`` mocks.

    Returns the two ``AsyncMock`` handles so tests can introspect call
    counts and arguments. ``create_side_effect`` may be a single
    exception (raised every call), a list (per-call sequence — exceptions
    raise, plain values return), or ``None``.
    """
    create_mock = AsyncMock(name="aio.caches.create")
    if create_side_effect is not None:
        create_mock.side_effect = create_side_effect
    else:
        create_mock.return_value = create_return or SimpleNamespace(name="cachedContents/abc")
    client.aio.caches.create = create_mock

    delete_mock = AsyncMock(name="aio.caches.delete")
    if delete_side_effect is not None:
        delete_mock.side_effect = delete_side_effect
    client.aio.caches.delete = delete_mock

    return create_mock, delete_mock


def _big_prompt(token_count_estimate: int = 5000) -> str:
    """Build a prompt long enough to satisfy the default ``cache_min_tokens``.

    The provider's char-fallback estimate is ``len(text) // 4``; pad to
    ``token_count_estimate * 4`` chars so the gate consistently passes
    even when ``count_tokens`` falls back inside a running event loop.
    """
    return "x" * (token_count_estimate * 4)


# ---------------------------------------------------------------------------
# Constructor — defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_constructor_keeps_aj21_behaviour() -> None:
    # ``GeminiProvider()`` without caching kwargs must look identical to
    # the AJ-21 release: no caches.create call, supports_prompt_caching
    # is False, cache=True passes through as a no-op.
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(client)
    provider = GeminiProvider(client=client)

    assert provider.supports_prompt_caching() is False
    response = await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="hi")],
        cache=True,
    )
    assert response.text == "hello"
    create_mock.assert_not_awaited()
    # No cached_content leaks into the call config either.
    config = client.aio.models.generate_content.call_args.kwargs.get("config")
    assert config is None or getattr(config, "cached_content", None) is None


def test_strategy_auto_flips_supports_prompt_caching_to_true() -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(client=client, cache_strategy="auto")
    assert provider.supports_prompt_caching() is True


def test_six_caching_kwargs_default_to_documented_values() -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(client=client)
    assert provider._cache_strategy == "off"
    assert provider._cache_ttl_seconds == 3600
    assert provider._cache_min_tokens == 1024
    assert provider._cache_key_strategy == "prefix_hash"
    assert provider._cache_on_expired == "recreate"
    assert provider._cache_cleanup == "on_provider_close"


@pytest.mark.parametrize("bad_ttl", [0, -1, -3600])
def test_invalid_cache_ttl_seconds_raises_value_error(bad_ttl: int) -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    with pytest.raises(ValueError, match="cache_ttl_seconds"):
        GeminiProvider(client=client, cache_ttl_seconds=bad_ttl)


@pytest.mark.parametrize("bad_min", [0, -1, -1024])
def test_invalid_cache_min_tokens_raises_value_error(bad_min: int) -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    with pytest.raises(ValueError, match="cache_min_tokens"):
        GeminiProvider(client=client, cache_min_tokens=bad_min)


# ---------------------------------------------------------------------------
# cache_strategy="auto" — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_cached_complete_call_triggers_caches_create_with_configured_ttl() -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(client=client, cache_strategy="auto", cache_ttl_seconds=900)

    big = _big_prompt()
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big)],
        cache=True,
    )

    create_mock.assert_awaited_once()
    create_kwargs = create_mock.call_args.kwargs
    assert create_kwargs["model"] == "gemini-2.5-flash"
    config = create_kwargs["config"]
    assert isinstance(config, genai_types.CreateCachedContentConfig)
    assert config.ttl == "900s"

    gc_kwargs = client.aio.models.generate_content.call_args.kwargs
    assert gc_kwargs["config"].cached_content == "cachedContents/abc"


@pytest.mark.asyncio
async def test_subsequent_complete_with_same_key_reuses_cache_name() -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")

    big = _big_prompt()
    for _ in range(2):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )

    # Only one caches.create — the second call reused the registry entry.
    assert create_mock.await_count == 1
    # Both generate_content calls referenced the same cached_content name.
    calls = client.aio.models.generate_content.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["config"].cached_content == "cachedContents/abc"
    assert calls[1].kwargs["config"].cached_content == "cachedContents/abc"


@pytest.mark.asyncio
async def test_stream_reuses_cache_created_by_complete_when_keys_match() -> None:
    events = [make_stream_chunk(text="hi"), make_stream_chunk(finish_reason="STOP")]
    client = make_async_client(stream_events=events)
    create_mock, _delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")

    big = _big_prompt()
    msgs = [Message(role="user", content=big)]

    # First call uses complete and creates the cache.
    await provider.complete(model="gemini-2.5-flash", messages=msgs, cache=True)

    # Second call uses stream and should reuse the same cache name.
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gemini-2.5-flash",
            messages=msgs,
            cache=True,
        )
    ]
    assert [c.delta for c in chunks if c.delta] == ["hi"]
    assert chunks[-1].finish_reason == "stop"
    assert create_mock.await_count == 1
    stream_kwargs = client.aio.models.generate_content_stream.call_args.kwargs
    assert stream_kwargs["config"].cached_content == "cachedContents/abc"


# ---------------------------------------------------------------------------
# Cache key strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prefix_hash_strategy_shares_cache_for_same_prefix() -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")

    shared = _big_prompt()
    msgs_a = [
        Message(role="system", content="You are concise."),
        Message(role="user", content=shared),
    ]
    msgs_b = [
        Message(role="system", content="You are concise."),
        Message(role="user", content=shared),
    ]
    await provider.complete(model="gemini-2.5-flash", messages=msgs_a, cache=True)
    await provider.complete(model="gemini-2.5-flash", messages=msgs_b, cache=True)
    assert create_mock.await_count == 1


@pytest.mark.asyncio
async def test_prefix_hash_strategy_makes_new_cache_for_different_prefix() -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/one"),
            SimpleNamespace(name="cachedContents/two"),
        ],
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")

    big_a = _big_prompt() + "alpha"
    big_b = _big_prompt() + "beta"
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big_a)],
        cache=True,
    )
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big_b)],
        cache=True,
    )
    assert create_mock.await_count == 2


@pytest.mark.asyncio
async def test_callable_strategy_is_invoked_with_messages_and_system() -> None:
    seen: list[tuple[list[Message], str | None]] = []

    def custom(msgs: list[Message], system: str | None) -> str:
        seen.append((msgs, system))
        return "session:42"

    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(
        client=client,
        cache_strategy="auto",
        cache_key_strategy=custom,
    )
    big = _big_prompt()
    msgs = [
        Message(role="system", content="You are concise."),
        Message(role="user", content=big),
    ]
    await provider.complete(model="gemini-2.5-flash", messages=msgs, cache=True)

    assert len(seen) == 1
    captured_msgs, captured_system = seen[0]
    assert captured_system == "You are concise."
    assert [m.content for m in captured_msgs] == [m.content for m in msgs]
    # And the registry tracked the cache under the custom key.
    assert provider._cache_registry.latest("session:42") == "cachedContents/abc"
    create_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_callable_strategy_raise_surfaces_as_cache_error() -> None:
    def boom(_msgs: list[Message], _system: str | None) -> str:
        raise RuntimeError("kaboom")

    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(
        client=client,
        cache_strategy="auto",
        cache_key_strategy=boom,
    )
    big = _big_prompt()
    with pytest.raises(GeminiCacheError) as exc_info:
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "kaboom" in str(exc_info.value)


@pytest.mark.parametrize("falsy", ["", 0, None])
@pytest.mark.asyncio
async def test_callable_strategy_falsy_return_surfaces_as_cache_error(falsy: Any) -> None:
    def empty(_msgs: list[Message], _system: str | None) -> Any:
        return falsy

    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(
        client=client,
        cache_strategy="auto",
        cache_key_strategy=empty,
    )
    big = _big_prompt()
    with pytest.raises(GeminiCacheError, match="falsy"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )


def test_prefix_hash_function_is_deterministic_and_prefix_sensitive() -> None:
    a = prefix_hash_cache_key(
        [Message(role="user", content="same prefix payload")],
        "system A",
    )
    b = prefix_hash_cache_key(
        [Message(role="user", content="same prefix payload")],
        "system A",
    )
    c = prefix_hash_cache_key(
        [Message(role="user", content="different prefix payload")],
        "system A",
    )
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# Cache minimum tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_below_min_tokens_raises_before_caches_create() -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(client)
    provider = GeminiProvider(client=client, cache_strategy="auto", cache_min_tokens=1024)
    with pytest.raises(GeminiCacheMinTokensError, match="cache_min_tokens"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
            cache=True,
        )
    create_mock.assert_not_awaited()
    client.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_min_tokens_error_message_names_count_threshold_and_kwarg() -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(client=client, cache_strategy="auto", cache_min_tokens=1024)
    with pytest.raises(GeminiCacheMinTokensError) as exc_info:
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
            cache=True,
        )
    msg = str(exc_info.value)
    assert "1024" in msg
    assert "cache_min_tokens" in msg


# ---------------------------------------------------------------------------
# Expiry handling
# ---------------------------------------------------------------------------


def _expired_404() -> genai_errors.APIError:
    return genai_errors.APIError(
        code=404, response_json={"error": {"message": "Cached content not found"}}
    )


@pytest.mark.asyncio
async def test_cache_on_expired_recreate_transparently_retries() -> None:
    # Two cache names — the first expires, the second is the recreate result.
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/old"),
            SimpleNamespace(name="cachedContents/new"),
        ],
    )

    success_response = make_generate_response(text="recovered")
    expired = _expired_404()
    client.aio.models.generate_content.side_effect = [expired, success_response]

    provider = GeminiProvider(client=client, cache_strategy="auto", cache_on_expired="recreate")
    big = _big_prompt()
    response = await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big)],
        cache=True,
    )

    assert response.text == "recovered"
    # First create + recreate = 2 caches.create awaits.
    assert create_mock.await_count == 2
    # First generate_content used the old cache; second used the new one.
    calls = client.aio.models.generate_content.await_args_list
    assert calls[0].kwargs["config"].cached_content == "cachedContents/old"
    assert calls[1].kwargs["config"].cached_content == "cachedContents/new"


@pytest.mark.asyncio
async def test_cache_on_expired_error_raises_typed_error_without_retry() -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/old")
    )
    client.aio.models.generate_content.side_effect = _expired_404()

    provider = GeminiProvider(client=client, cache_strategy="auto", cache_on_expired="error")
    big = _big_prompt()
    with pytest.raises(GeminiCacheExpiredError, match="cachedContents/old"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )
    # Only the initial create — no recreate path on "error" mode.
    assert create_mock.await_count == 1


@pytest.mark.asyncio
async def test_recreate_failure_surfaces_as_cache_create_error() -> None:
    # Create succeeds once, then the recreate path's caches.create fails.
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/old"),
            RuntimeError("create unavailable"),
        ],
    )
    client.aio.models.generate_content.side_effect = _expired_404()

    provider = GeminiProvider(client=client, cache_strategy="auto", cache_on_expired="recreate")
    big = _big_prompt()
    with pytest.raises(GeminiCacheCreateError, match=r"caches\.create failed"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )
    assert create_mock.await_count == 2


@pytest.mark.asyncio
async def test_stream_expiry_always_raises_cache_expired_regardless_of_kwarg() -> None:
    # Streaming + 404 mid-iteration must surface GeminiCacheExpiredError
    # even when cache_on_expired="recreate"; the iterator cannot replay.
    client = make_async_client()
    _install_caches_mocks(client, create_return=SimpleNamespace(name="cachedContents/streamy"))

    expired = _expired_404()
    events = [make_stream_chunk(text="partial")]
    iterator = _AsyncStreamIterator(events, raise_after=expired)

    def _stream(**_kwargs: Any) -> Any:
        return iterator

    client.aio.models.generate_content_stream = MagicMock(
        name="aio.models.generate_content_stream", side_effect=_stream
    )

    provider = GeminiProvider(client=client, cache_strategy="auto", cache_on_expired="recreate")
    big = _big_prompt()
    iter_chunks = provider.stream(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big)],
        cache=True,
    )
    first = await iter_chunks.__anext__()
    assert first.delta == "partial"
    with pytest.raises(GeminiCacheExpiredError, match="retry the request"):
        await iter_chunks.__anext__()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_deletes_each_tracked_cache_under_on_provider_close() -> None:
    client = make_async_client()
    create_mock, delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/one"),
            SimpleNamespace(name="cachedContents/two"),
        ],
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")

    # Two distinct prefixes → two cache entries.
    big_a = _big_prompt() + "alpha"
    big_b = _big_prompt() + "beta"
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big_a)],
        cache=True,
    )
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big_b)],
        cache=True,
    )
    assert create_mock.await_count == 2

    await provider.aclose()
    assert delete_mock.await_count == 2
    deleted_names = {call.kwargs["name"] for call in delete_mock.await_args_list}
    assert deleted_names == {"cachedContents/one", "cachedContents/two"}
    assert provider._cache_registry.is_empty()


@pytest.mark.asyncio
async def test_aclose_manual_mode_does_not_delete_or_clear() -> None:
    client = make_async_client()
    create_mock, delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(client=client, cache_strategy="auto", cache_cleanup="manual")
    big = _big_prompt()
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big)],
        cache=True,
    )
    create_mock.assert_awaited_once()
    await provider.aclose()
    delete_mock.assert_not_awaited()
    # Registry persists (until GC).
    assert not provider._cache_registry.is_empty()


@pytest.mark.asyncio
async def test_aclose_logs_warning_on_delete_failure_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/one"),
            SimpleNamespace(name="cachedContents/two"),
        ],
    )
    # One success, one failure — failure must not abort the loop.
    delete_mock = AsyncMock(name="aio.caches.delete")
    delete_mock.side_effect = [
        None,
        RuntimeError("delete blew up"),
    ]
    client.aio.caches.delete = delete_mock

    provider = GeminiProvider(client=client, cache_strategy="auto")
    big_a = _big_prompt() + "alpha"
    big_b = _big_prompt() + "beta"
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big_a)],
        cache=True,
    )
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big_b)],
        cache=True,
    )
    assert create_mock.await_count == 2

    with caplog.at_level(logging.WARNING, logger="ajolopy.providers.gemini"):
        await provider.aclose()

    assert delete_mock.await_count == 2
    assert any("failed during shutdown" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_async_context_manager_calls_aclose_on_exit() -> None:
    client = make_async_client()
    create_mock, delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    big = _big_prompt()
    async with GeminiProvider(client=client, cache_strategy="auto") as provider:
        assert isinstance(provider, GeminiProvider)
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )

    create_mock.assert_awaited_once()
    delete_mock.assert_awaited_once()
    await_args = delete_mock.await_args
    assert await_args is not None
    assert await_args.kwargs["name"] == "cachedContents/abc"


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    client = make_async_client()
    _create_mock, delete_mock = _install_caches_mocks(
        client, create_return=SimpleNamespace(name="cachedContents/abc")
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")
    big = _big_prompt()
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content=big)],
        cache=True,
    )
    await provider.aclose()
    first_call_count = delete_mock.await_count
    await provider.aclose()
    # Second call observes an empty registry → no extra SDK call.
    assert delete_mock.await_count == first_call_count


@pytest.mark.asyncio
async def test_aclose_does_not_abort_in_flight_complete_call() -> None:
    """Concurrent aclose() does not cancel an in-flight cached call.

    The spec requires that caches created after the snapshot survive
    until garbage collection. Implementation uses a snapshot+clear of
    the registry so the in-flight call's create-and-register happens on
    a fresh registry post-cleanup.
    """
    started = asyncio.Event()
    finish = asyncio.Event()

    client = make_async_client()
    create_mock, delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/one"),
            SimpleNamespace(name="cachedContents/two"),
        ],
    )

    # Wrap caches.create so the first await blocks until ``finish`` is set,
    # giving us a deterministic window in which aclose() can run between
    # the snapshot and the in-flight create.
    async def slow_create(*_args: Any, **_kwargs: Any) -> Any:
        started.set()
        await finish.wait()
        return SimpleNamespace(name="cachedContents/inflight")

    create_mock.side_effect = slow_create

    provider = GeminiProvider(client=client, cache_strategy="auto")
    big = _big_prompt()

    async def slow_complete() -> Any:
        return await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )

    complete_task = asyncio.create_task(slow_complete())
    await started.wait()
    # While the in-flight create is blocked, aclose observes an empty
    # registry (no register has happened yet) and returns immediately.
    await provider.aclose()
    delete_mock.assert_not_awaited()
    # Now unblock the in-flight call. It must complete successfully and
    # leave its cache name in the (newly empty) registry.
    finish.set()
    response = await complete_task
    assert response.text == "hello"
    assert (
        provider._cache_registry.latest(
            prefix_hash_cache_key([Message(role="user", content=big)], None)
        )
        == "cachedContents/inflight"
    )


# ---------------------------------------------------------------------------
# Capability flag
# ---------------------------------------------------------------------------


def test_supports_prompt_caching_returns_false_when_off() -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(client=client, cache_strategy="off")
    assert provider.supports_prompt_caching() is False


def test_supports_prompt_caching_returns_true_when_auto() -> None:
    client = make_async_client()
    _install_caches_mocks(client)
    provider = GeminiProvider(client=client, cache_strategy="auto")
    assert provider.supports_prompt_caching() is True


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_first_call_per_key_issues_two_creates() -> None:
    # No internal lock — two coroutines that race past the same empty
    # registry slot both call caches.create. Both succeed; both names get
    # tracked. Marginal cost is one wasted create per race; acceptable.
    client = make_async_client()
    create_mock, _delete_mock = _install_caches_mocks(
        client,
        create_side_effect=[
            SimpleNamespace(name="cachedContents/one"),
            SimpleNamespace(name="cachedContents/two"),
        ],
    )

    # Hold both creates so the registry remains empty for both branches
    # before any register() call happens — that's where the race lives.
    barrier = asyncio.Event()
    started = asyncio.Semaphore(0)
    queue: list[Any] = [
        SimpleNamespace(name="cachedContents/one"),
        SimpleNamespace(name="cachedContents/two"),
    ]

    async def racy_create(*_args: Any, **_kwargs: Any) -> Any:
        started.release()
        await barrier.wait()
        return queue.pop(0)

    create_mock.side_effect = racy_create

    provider = GeminiProvider(client=client, cache_strategy="auto")
    big = _big_prompt()
    msgs = [Message(role="user", content=big)]

    t1 = asyncio.create_task(provider.complete(model="gemini-2.5-flash", messages=msgs, cache=True))
    t2 = asyncio.create_task(provider.complete(model="gemini-2.5-flash", messages=msgs, cache=True))
    await started.acquire()
    await started.acquire()
    barrier.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1.text == "hello"
    assert r2.text == "hello"
    assert create_mock.await_count == 2
    # Both names tracked under the single derived key.
    key = prefix_hash_cache_key(msgs, None)
    tracked = provider._cache_registry.names_for(key)
    assert sorted(tracked) == ["cachedContents/one", "cachedContents/two"]


# ---------------------------------------------------------------------------
# Negative — non-recoverable SDK errors on creation surface cleanly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_create_failure_surfaces_as_cache_create_error() -> None:
    client = make_async_client()
    _install_caches_mocks(client, create_side_effect=RuntimeError("transport gone"))
    provider = GeminiProvider(client=client, cache_strategy="auto")
    big = _big_prompt()
    with pytest.raises(GeminiCacheCreateError, match=r"caches\.create failed"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )


@pytest.mark.asyncio
async def test_create_returning_empty_name_surfaces_as_cache_create_error() -> None:
    client = make_async_client()
    _install_caches_mocks(client, create_return=SimpleNamespace(name=""))
    provider = GeminiProvider(client=client, cache_strategy="auto")
    big = _big_prompt()
    with pytest.raises(GeminiCacheCreateError, match="no usable cache name"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )


@pytest.mark.asyncio
async def test_strategy_off_with_cache_true_is_a_documented_no_op_on_stream() -> None:
    # Symmetry check with complete(): stream() must NOT leak cached_content
    # into the SDK config when the master switch is off.
    events = [make_stream_chunk(text="hi"), make_stream_chunk(finish_reason="STOP")]
    client = make_async_client(stream_events=events)
    create_mock, _delete_mock = _install_caches_mocks(client)
    provider = GeminiProvider(client=client)  # cache_strategy="off" by default
    chunks = [
        chunk
        async for chunk in provider.stream(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
            cache=True,
        )
    ]
    assert chunks[-1].finish_reason == "stop"
    create_mock.assert_not_awaited()
    stream_kwargs = client.aio.models.generate_content_stream.call_args.kwargs
    config = stream_kwargs.get("config")
    assert config is None or getattr(config, "cached_content", None) is None


@pytest.mark.asyncio
async def test_non_404_sdk_error_with_cache_active_falls_through_as_provider_error() -> None:
    # A non-404 SDK error during generate_content must still surface as
    # GeminiProviderError — the cache-expiry detour only matters for 404s.
    client = make_async_client()
    _install_caches_mocks(client, create_return=SimpleNamespace(name="cachedContents/abc"))
    client.aio.models.generate_content.side_effect = genai_errors.APIError(
        code=503, response_json={"error": {"message": "overloaded"}}
    )
    provider = GeminiProvider(client=client, cache_strategy="auto")
    big = _big_prompt()
    with pytest.raises(GeminiProviderError, match="Gemini SDK error during complete"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content=big)],
            cache=True,
        )
