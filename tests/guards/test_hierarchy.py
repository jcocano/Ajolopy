"""Class-level + method-level guard concatenation."""

from typing import Any, override

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from ajolopy.guards import Guard, UseGuards
from ajolopy.guards.errors import GuardForbiddenError, GuardUnauthorizedError
from ajolopy.http import create_app
from ajolopy.routes import Controller, Get, mount_routes


class _RecordingGuard(Guard):
    """Records its name into a class-level list when can_activate runs."""

    log: list[str] = []
    decision: bool = True
    raise_error: type[Exception] | None = None

    @override
    async def can_activate(self, request: Request) -> bool:
        _RecordingGuard.log.append(self._name())
        if self.raise_error is not None:
            raise self.raise_error("denied")
        return self.decision

    def _name(self) -> str:
        return type(self).__name__


class _GuardA(_RecordingGuard):
    pass


class _GuardB(_RecordingGuard):
    pass


class _DenyGuard(_RecordingGuard):
    decision = False


class _UnauthorizedGuard(_RecordingGuard):
    raise_error = GuardUnauthorizedError


class _ForbiddenGuard(_RecordingGuard):
    raise_error = GuardForbiddenError


@pytest.fixture(autouse=True)
def _reset_log() -> None:  # pyright: ignore[reportUnusedFunction]
    """Wipe the shared guard log between tests so per-test assertions hold."""
    _RecordingGuard.log.clear()


def _app_class_and_method() -> Any:
    @UseGuards(_GuardA())
    @Controller("/things")
    class Things:
        @UseGuards(_GuardB())
        @Get("/items")
        async def items(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [Things])
    return app


def _app_class_only() -> Any:
    @UseGuards(_GuardA())
    @Controller("/things")
    class Things:
        @Get("/items")
        async def items(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [Things])
    return app


def _app_method_only() -> Any:
    @Controller("/things")
    class Things:
        @UseGuards(_GuardB())
        @Get("/items")
        async def items(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [Things])
    return app


class TestClassAndMethodConcatenate:
    def test_both_run_in_order(self) -> None:
        with TestClient(_app_class_and_method()) as client:
            response = client.get("/things/items")
        assert response.status_code == 200
        assert _RecordingGuard.log == ["_GuardA", "_GuardB"]


class TestShortCircuit:
    def test_first_failure_skips_second(self) -> None:
        @UseGuards(_UnauthorizedGuard())
        @Controller("/things")
        class Things:
            @UseGuards(_GuardB())
            @Get("/items")
            async def items(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        mount_routes(app, [Things])
        with TestClient(app) as client:
            response = client.get("/things/items")
        assert response.status_code == 401
        assert _RecordingGuard.log == ["_UnauthorizedGuard"]


class TestClassOnly:
    def test_runs_class_chain(self) -> None:
        with TestClient(_app_class_only()) as client:
            response = client.get("/things/items")
        assert response.status_code == 200
        assert _RecordingGuard.log == ["_GuardA"]


class TestMethodOnly:
    def test_runs_method_chain(self) -> None:
        with TestClient(_app_method_only()) as client:
            response = client.get("/things/items")
        assert response.status_code == 200
        assert _RecordingGuard.log == ["_GuardB"]


class TestMultipleGuardsInOneDecorator:
    def test_argument_order_preserved(self) -> None:
        @UseGuards(_GuardA(), _GuardB())
        @Controller("/things")
        class Things:
            @Get("/items")
            async def items(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        mount_routes(app, [Things])
        with TestClient(app) as client:
            response = client.get("/things/items")
        assert response.status_code == 200
        assert _RecordingGuard.log == ["_GuardA", "_GuardB"]


class TestReturnsFalseShortCircuits:
    def test_false_yields_401(self) -> None:
        @UseGuards(_DenyGuard())
        @Controller("/things")
        class Things:
            @Get("/items")
            async def items(self) -> dict[str, str]:
                return {"ok": "yes"}

        app = create_app()
        mount_routes(app, [Things])
        with TestClient(app) as client:
            response = client.get("/things/items")
        assert response.status_code == 401
