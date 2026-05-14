"""Decoration-time validation for ``@UseGuards`` and ``_normalize_guard``."""

from collections.abc import Awaitable
from typing import override

import pytest
from starlette.requests import Request

from ajolopy.guards import Guard, UseGuards, UseGuardsConfigError
from ajolopy.guards.base import _CallableGuard, _normalize_guard
from ajolopy.guards.decorator import GUARDS_META_ATTR, get_guard_chain


class _PassGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        return True


class _RequiresArgGuard(Guard):
    def __init__(self, *, label: str) -> None:
        self._label = label

    @override
    async def can_activate(self, request: Request) -> bool:
        return True


class _SyncGuard(Guard):
    @override
    def can_activate(self, request: Request) -> bool:  # type: ignore[override]
        return True


class TestStampMetadata:
    def test_stamps_instance_verbatim(self) -> None:
        instance = _PassGuard()

        @UseGuards(instance)
        class Host:
            pass

        chain = get_guard_chain(Host)
        assert chain == (instance,)

    def test_instantiates_zero_arg_subclass(self) -> None:
        @UseGuards(_PassGuard)
        class Host:
            pass

        chain = get_guard_chain(Host)
        assert len(chain) == 1
        assert isinstance(chain[0], _PassGuard)

    def test_wraps_callable_in_adapter(self) -> None:
        async def check(_request: Request) -> bool:
            return True

        @UseGuards(check)
        class Host:
            pass

        chain = get_guard_chain(Host)
        assert len(chain) == 1
        assert isinstance(chain[0], _CallableGuard)

    def test_multiple_guards_preserve_order(self) -> None:
        a = _PassGuard()
        b = _PassGuard()
        c = _PassGuard()

        @UseGuards(a, b, c)
        class Host:
            pass

        chain = get_guard_chain(Host)
        assert chain == (a, b, c)

    def test_method_level_stamp(self) -> None:
        instance = _PassGuard()

        class Host:
            @UseGuards(instance)
            async def handler(self) -> None:
                return None

        chain = get_guard_chain(Host.handler)
        assert chain == (instance,)

    def test_stacked_decorators_concatenate(self) -> None:
        a = _PassGuard()
        b = _PassGuard()

        # Outer decorator runs LAST in Python semantics; the framework
        # normalises so the user-visible declaration order is preserved.
        @UseGuards(a)
        @UseGuards(b)
        class Host:
            pass

        chain = get_guard_chain(Host)
        # Inner decorator stamps first (b), outer extends with (a).
        assert chain == (b, a)


class TestZeroArgsRejected:
    def test_zero_args_raises(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="at least one guard"):
            UseGuards()


class TestNonGuardArgRejected:
    def test_string_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="Accepted forms"):
            UseGuards("not-a-guard")  # pyright: ignore[reportArgumentType]

    def test_int_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="Accepted forms"):
            UseGuards(42)  # pyright: ignore[reportArgumentType]

    def test_non_guard_class_rejected(self) -> None:
        class NotAGuard:
            pass

        with pytest.raises(UseGuardsConfigError, match="not a Guard subclass"):
            UseGuards(NotAGuard)  # pyright: ignore[reportArgumentType]


class TestRequiredInitHint:
    def test_required_init_guard_class_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="pre-built instance"):
            UseGuards(_RequiresArgGuard)


class TestSyncCanActivateRejected:
    def test_sync_can_activate_class_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="async def can_activate"):
            UseGuards(_SyncGuard)


class TestDecorationTarget:
    def test_decorating_non_callable_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="class or a function"):
            UseGuards(_PassGuard())(42)

    def test_decorating_string_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="class or a function"):
            UseGuards(_PassGuard())("module-var")


class TestNormalizeHelper:
    def test_normalize_instance_passes_through(self) -> None:
        guard = _PassGuard()
        assert _normalize_guard(guard) is guard

    def test_normalize_async_callable_wraps(self) -> None:
        async def fn(_r: Request) -> bool:
            return True

        adapter = _normalize_guard(fn)
        assert isinstance(adapter, _CallableGuard)

    def test_normalize_sync_callable_wraps(self) -> None:
        def fn(_r: Request) -> bool:
            return True

        adapter = _normalize_guard(fn)
        assert isinstance(adapter, _CallableGuard)


class TestCallableAdapter:
    @pytest.mark.asyncio
    async def test_adapter_awaits_async_callable(self) -> None:
        called: list[bool] = []

        async def fn(_r: Request) -> bool:
            called.append(True)
            return True

        adapter = _CallableGuard(fn)
        result = await adapter.can_activate(_make_dummy_request())
        assert result is True
        assert called == [True]

    @pytest.mark.asyncio
    async def test_adapter_runs_sync_callable(self) -> None:
        def fn(_r: Request) -> bool:
            return True

        adapter = _CallableGuard(fn)
        assert await adapter.can_activate(_make_dummy_request()) is True

    @pytest.mark.asyncio
    async def test_adapter_awaits_explicit_awaitable(self) -> None:
        # Return an Awaitable[bool] (not just an async def call) to make
        # sure the adapter inspects ``inspect.isawaitable``.
        async def coroutine() -> bool:
            return True

        def fn(_r: Request) -> Awaitable[bool]:
            return coroutine()

        adapter = _CallableGuard(fn)
        assert await adapter.can_activate(_make_dummy_request()) is True


class TestMetadataAttributeName:
    def test_attribute_name_is_stable(self) -> None:
        # External tooling depends on the exact attribute name.
        assert GUARDS_META_ATTR == "_ajolopy_guards"

        @UseGuards(_PassGuard())
        class Host:
            pass

        assert hasattr(Host, GUARDS_META_ATTR)


def _make_dummy_request() -> Request:
    """Build the cheapest possible Starlette Request for unit testing."""
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)
