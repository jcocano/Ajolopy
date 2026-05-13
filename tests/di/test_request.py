"""Request-scope semantics — sync + async, plus concurrent isolation."""

import asyncio

import pytest

from ajolopy.di import Container, OutOfScopeError


class _RequestContext:
    pass


class _Singleton:
    def __init__(self, ctx: _RequestContext) -> None:
        self.ctx = ctx


def test_resolve_outside_scope_raises() -> None:
    container = Container()
    container.register(_RequestContext, scope="request")
    with pytest.raises(OutOfScopeError, match="no request scope is active"):
        container.resolve(_RequestContext)


def test_same_instance_inside_one_scope() -> None:
    container = Container()
    container.register(_RequestContext, scope="request")
    with container.request_scope():
        a = container.resolve(_RequestContext)
        b = container.resolve(_RequestContext)
        assert a is b


def test_sequential_scopes_produce_distinct_instances() -> None:
    container = Container()
    container.register(_RequestContext, scope="request")
    with container.request_scope():
        a = container.resolve(_RequestContext)
    with container.request_scope():
        b = container.resolve(_RequestContext)
    assert a is not b


def test_singleton_depending_on_request_scoped_raises_eagerly() -> None:
    container = Container()
    container.register(_RequestContext, scope="request")
    container.register(_Singleton)
    # Even *inside* a request scope, a singleton must not capture
    # request-scoped state — the build should fail explicitly.
    with container.request_scope(), pytest.raises(OutOfScopeError, match="must not capture"):
        container.resolve(_Singleton)


@pytest.mark.asyncio
async def test_concurrent_tasks_get_independent_scopes() -> None:
    container = Container()
    container.register(_RequestContext, scope="request")

    async def handle() -> int:
        async with container.async_request_scope():
            ctx = container.resolve(_RequestContext)
            # Tiny await so the two tasks actually interleave.
            await asyncio.sleep(0)
            return id(ctx)

    first, second = await asyncio.gather(handle(), handle())
    assert first != second


@pytest.mark.asyncio
async def test_async_request_scope_shares_within_one_task() -> None:
    container = Container()
    container.register(_RequestContext, scope="request")
    async with container.async_request_scope():
        a = container.resolve(_RequestContext)
        b = container.resolve(_RequestContext)
        assert a is b
