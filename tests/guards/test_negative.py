"""Negative cases — misuse surfaces at decoration / mount time."""

from collections.abc import AsyncGenerator
from typing import override

import pytest
from starlette.requests import Request

from ajolopy.guards import Guard, UseGuards, UseGuardsConfigError
from ajolopy.http import create_app
from ajolopy.stream import Stream, StreamConfigError, mount_streams


class _PassGuard(Guard):
    @override
    async def can_activate(self, request: Request) -> bool:
        return True


class TestNonClassOrFunctionTarget:
    def test_int_target_rejected(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="class or a function"):
            UseGuards(_PassGuard())(42)


class TestTwoDecoratorsConcatenate:
    def test_concatenation_preserves_order(self) -> None:
        a = _PassGuard()
        b = _PassGuard()

        @UseGuards(a)
        @UseGuards(b)
        class Host:
            pass

        chain = Host._ajolopy_guards  # pyright: ignore[reportAttributeAccessIssue]
        assert isinstance(chain, tuple)
        # Inner decorator stamps first → ``b``; outer extends → ``a``.
        assert chain == (b, a)


class TestSyncCanActivateGuard:
    def test_sync_guard_rejected_at_decoration(self) -> None:
        class _SyncGuard(Guard):
            @override
            def can_activate(self, request: Request) -> bool:  # type: ignore[override]
                return True

        with pytest.raises(UseGuardsConfigError, match="async def"):
            UseGuards(_SyncGuard)


class TestStreamAuthMisuse:
    def test_auth_true_without_guards_raises_named_method(self) -> None:
        class Chat:
            @Stream("/chat", auth=True)
            async def respond(self) -> AsyncGenerator[str]:
                yield "x"

        app = create_app()
        with pytest.raises(StreamConfigError, match="respond"):
            mount_streams(app, [Chat])
