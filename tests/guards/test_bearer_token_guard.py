"""End-to-end behaviour for :class:`BearerTokenGuard`."""

from typing import Any

import pytest
from starlette.testclient import TestClient

from ajolopy.guards import BearerTokenGuard, UseGuards
from ajolopy.http import create_app
from ajolopy.routes import Controller, Get, mount_routes


def _app_with_env_guard() -> Any:
    # ``token_env="API_TOKEN"`` is the env-var NAME, not a literal token.
    @Controller("/secure")
    class Secure:
        @UseGuards(BearerTokenGuard(token_env="API_TOKEN"))  # noqa: S106
        @Get("/data")
        async def data(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [Secure])
    return app


def _app_with_literal_guard() -> Any:
    @Controller("/secure")
    class Secure:
        @UseGuards(BearerTokenGuard(token="literal-secret"))  # noqa: S106
        @Get("/data")
        async def data(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [Secure])
    return app


class TestEnvLazyLookup:
    def test_env_var_set_after_decoration_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _app_with_env_guard()
        # Set env AFTER controller is decorated.
        monkeypatch.setenv("API_TOKEN", "abc123")
        with TestClient(app) as client:
            response = client.get("/secure/data", headers={"authorization": "Bearer abc123"})
        assert response.status_code == 200
        assert response.json() == {"ok": "yes"}

    def test_correct_token_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_TOKEN", "abc123")
        with TestClient(_app_with_env_guard()) as client:
            response = client.get("/secure/data", headers={"authorization": "Bearer abc123"})
        assert response.status_code == 200

    def test_wrong_token_returns_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_TOKEN", "abc123")
        with TestClient(_app_with_env_guard()) as client:
            response = client.get("/secure/data", headers={"authorization": "Bearer wrong"})
        assert response.status_code == 403


class TestMissingAuthHeader:
    def test_no_header_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_TOKEN", "abc123")
        with TestClient(_app_with_env_guard()) as client:
            response = client.get("/secure/data")
        assert response.status_code == 401


class TestWrongScheme:
    def test_basic_scheme_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_TOKEN", "abc123")
        with TestClient(_app_with_env_guard()) as client:
            response = client.get("/secure/data", headers={"authorization": "Basic abc123"})
        assert response.status_code == 401


class TestLiteralToken:
    def test_literal_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Env var deliberately unset / set to a different value: literal
        # must win.
        monkeypatch.setenv("API_TOKEN", "different")
        with TestClient(_app_with_literal_guard()) as client:
            response = client.get(
                "/secure/data", headers={"authorization": "Bearer literal-secret"}
            )
        assert response.status_code == 200

    def test_literal_ignores_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_TOKEN", "env-value")
        with TestClient(_app_with_literal_guard()) as client:
            # Send the env value (which is NOT the literal) — must fail.
            response = client.get("/secure/data", headers={"authorization": "Bearer env-value"})
        assert response.status_code == 403


class TestMissingEnvVar:
    def test_unset_env_returns_401_with_generic_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("API_TOKEN", raising=False)
        with TestClient(_app_with_env_guard()) as client:
            response = client.get("/secure/data", headers={"authorization": "Bearer anything"})
        # Generic 401 — must NOT leak "env var unset" in the body.
        assert response.status_code == 401
        body = response.json()
        message = str(body.get("message", "")).lower()
        assert "env" not in message
        assert "api_token" not in message
