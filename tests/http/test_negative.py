"""Negative cases for introspection at ``add_route`` time."""

from typing import Annotated

import pytest
from starlette.requests import Request

from ajolopy.http import (
    Body,
    Header,
    HttpHandlerConfigError,
    Query,
    add_route,
    create_app,
)


def test_two_markers_on_one_parameter_raises_config_error():
    async def handler(x: Annotated[str, Query(), Header()]) -> dict[str, str]:
        return {"x": x}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="multiple"):
        add_route(app, "GET", "/x", handler)


def test_unannotated_param_with_marker_raises_config_error():
    async def handler(x=Body()) -> dict[str, str]:  # noqa: B008  — testing missing annotation
        return {"x": str(x)}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="no type annotation"):
        add_route(app, "GET", "/x", handler)


def test_unannotated_param_without_marker_raises_config_error():
    async def handler(x) -> dict[str, str]:
        return {"x": str(x)}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="no type annotation"):
        add_route(app, "GET", "/x", handler)


def test_typed_param_without_marker_and_not_request_raises_config_error():
    async def handler(x: int) -> dict[str, int]:
        return {"x": x}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="no param marker"):
        add_route(app, "GET", "/x", handler)


def test_two_body_parameters_raise_config_error():
    async def handler(
        a: Annotated[bytes, Body()],
        b: Annotated[bytes, Body()],
    ) -> dict[str, int]:
        return {"a": len(a), "b": len(b)}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="more than one"):
        add_route(app, "POST", "/x", handler)


def test_unsupported_body_type_raises_config_error():
    class _NotPydantic:
        pass

    async def handler(body: Annotated[_NotPydantic, Body()]) -> dict[str, str]:
        return {"ok": "x"}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="unsupported"):
        add_route(app, "POST", "/x", handler)


def test_unresolvable_forward_reference_raises_config_error():
    # Build a function whose annotation is an unresolvable forward reference.
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 — intentional: synthesise a handler with a bad annotation.
        "async def handler(x: 'DefinitelyDoesNotExist') -> dict: return {}",
        namespace,
    )

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="unresolvable"):
        add_route(app, "GET", "/x", namespace["handler"])  # type: ignore[arg-type]


def test_raw_request_parameter_works_alongside_markers():
    async def handler(
        request: Request,
        page: Annotated[int, Query()],
    ) -> dict[str, object]:
        return {"path": request.url.path, "page": page}

    app = create_app()
    add_route(app, "GET", "/x", handler)

    from starlette.testclient import TestClient

    response = TestClient(app).get("/x?page=5")
    assert response.status_code == 200
    assert response.json() == {"path": "/x", "page": 5}
