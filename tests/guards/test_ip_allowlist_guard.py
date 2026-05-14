"""End-to-end behaviour for :class:`IPAllowlistGuard`."""

from typing import Any

import pytest
from starlette.testclient import TestClient

from ajolopy.guards import IPAllowlistGuard, UseGuards, UseGuardsConfigError
from ajolopy.http import create_app
from ajolopy.routes import Controller, Get, mount_routes


def _app_with_allowlist(
    allowed: list[str],
    *,
    trust_forwarded_for: bool = False,
) -> Any:
    @Controller("/restricted")
    class Restricted:
        @UseGuards(
            IPAllowlistGuard(
                allowed=allowed,
                trust_forwarded_for=trust_forwarded_for,
            )
        )
        @Get("/data")
        async def data(self) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    mount_routes(app, [Restricted])
    return app


class TestConstructionValidation:
    def test_invalid_cidr_raises(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="not a valid"):
            IPAllowlistGuard(allowed=["not-an-ip"])

    def test_empty_allowed_raises(self) -> None:
        with pytest.raises(UseGuardsConfigError, match="at least one"):
            IPAllowlistGuard(allowed=[])


class TestHostMatching:
    def test_allowed_ipv4_passes(self) -> None:
        with TestClient(
            _app_with_allowlist(["127.0.0.1"]),
            client=("127.0.0.1", 50000),
        ) as client:
            response = client.get("/restricted/data")
        assert response.status_code == 200

    def test_rejected_ipv4_returns_403(self) -> None:
        with TestClient(
            _app_with_allowlist(["10.0.0.1"]),
            client=("192.168.0.1", 50000),
        ) as client:
            response = client.get("/restricted/data")
        assert response.status_code == 403


class TestCidrMatching:
    def test_cidr_range_matches(self) -> None:
        # TestClient sets ``client=("testclient", 50000)`` — patch the
        # request scope by using the ``client`` kwarg.
        with TestClient(
            _app_with_allowlist(["10.0.0.0/8"]),
            client=("10.0.1.5", 50000),
        ) as client:
            response = client.get("/restricted/data")
        assert response.status_code == 200

    def test_cidr_range_rejects_outside(self) -> None:
        with TestClient(
            _app_with_allowlist(["10.0.0.0/8"]),
            client=("192.168.0.1", 50000),
        ) as client:
            response = client.get("/restricted/data")
        assert response.status_code == 403


class TestIPv6:
    def test_ipv6_loopback_matches(self) -> None:
        with TestClient(
            _app_with_allowlist(["::1/128"]),
            client=("::1", 50000),
        ) as client:
            response = client.get("/restricted/data")
        assert response.status_code == 200


class TestForwardedFor:
    def test_trust_forwarded_for_false_ignores_header(self) -> None:
        # Allow only 10.0.0.1 — header says 10.0.0.1 but trust is OFF,
        # so the guard reads ``request.client.host`` (here 192.168.0.1)
        # which is NOT in the allowlist.
        with TestClient(
            _app_with_allowlist(["10.0.0.1"], trust_forwarded_for=False),
            client=("192.168.0.1", 50000),
        ) as client:
            response = client.get("/restricted/data", headers={"x-forwarded-for": "10.0.0.1"})
        assert response.status_code == 403

    def test_trust_forwarded_for_true_uses_leftmost(self) -> None:
        # Allow only 10.0.0.1; with trust ON the header steers the check.
        with TestClient(
            _app_with_allowlist(["10.0.0.1"], trust_forwarded_for=True),
            client=("192.168.0.1", 50000),
        ) as client:
            response = client.get(
                "/restricted/data",
                headers={"x-forwarded-for": "10.0.0.1, 192.168.0.1"},
            )
        assert response.status_code == 200

    def test_trust_forwarded_for_true_falls_back_to_client(self) -> None:
        with TestClient(
            _app_with_allowlist(["127.0.0.1"], trust_forwarded_for=True),
            client=("127.0.0.1", 50000),
        ) as client:
            response = client.get("/restricted/data")
        assert response.status_code == 200


class TestMissingClient:
    @pytest.mark.asyncio
    async def test_request_without_client_is_rejected(self) -> None:
        # Direct guard invocation with a Request whose ``client`` is None.
        from starlette.requests import Request

        scope: dict[str, object] = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        guard = IPAllowlistGuard(allowed=["127.0.0.1"])
        from ajolopy.guards.errors import GuardForbiddenError

        with pytest.raises(GuardForbiddenError):
            await guard.can_activate(request)
