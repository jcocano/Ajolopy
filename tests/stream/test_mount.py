"""``mount_streams`` and ``create_app(streams=...)`` integration."""

from collections.abc import AsyncGenerator
from typing import Annotated
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from ajolopy.http import Body, create_app
from ajolopy.stream import Stream, StreamConfigError, mount_streams


class _Greeting(BaseModel):
    message: str


class _Hello:
    @Stream("/hello")
    async def respond(self, body: Annotated[_Greeting, Body()]) -> AsyncGenerator[str]:
        yield f"hi {body.message}"


class _AdminHello:
    @Stream("/admin/hello")
    async def admin(self, body: Annotated[_Greeting, Body()]) -> AsyncGenerator[str]:
        yield f"admin {body.message}"


class TestMountStreams:
    def test_mounts_method_for_class(self) -> None:
        app = create_app()
        mount_streams(app, [_Hello])
        assert _route_exists(app, "/hello", "POST")

    def test_mounts_method_for_pre_built_instance(self) -> None:
        app = create_app()
        mount_streams(app, [_Hello()])
        assert _route_exists(app, "/hello", "POST")

    def test_instance_supplied_is_not_reinstantiated(self) -> None:
        instance = _Hello()
        app = create_app()
        with patch.object(_Hello, "__init__", return_value=None) as init_spy:
            mount_streams(app, [instance])
            init_spy.assert_not_called()

    def test_class_with_no_stream_methods_raises(self) -> None:
        class Empty:
            pass

        app = create_app()
        with pytest.raises(StreamConfigError, match="no @Stream-marked methods"):
            mount_streams(app, [Empty])

    def test_class_with_required_constructor_args_raises(self) -> None:
        class Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Stream("/needs")
            async def respond(self) -> AsyncGenerator[str]:
                yield "x"

        app = create_app()
        with pytest.raises(StreamConfigError, match="requires constructor argument"):
            mount_streams(app, [Needs])

    def test_pre_built_instance_bypasses_constructor_check(self) -> None:
        class Needs:
            def __init__(self, db: object) -> None:
                self.db = db

            @Stream("/needs")
            async def respond(self) -> AsyncGenerator[str]:
                yield "x"

        app = create_app()
        mount_streams(app, [Needs(db=object())])
        assert _route_exists(app, "/needs", "POST")

    def test_duplicate_method_path_raises(self) -> None:
        class Other:
            @Stream("/hello")
            async def respond(self, body: Annotated[_Greeting, Body()]) -> AsyncGenerator[str]:
                yield body.message

        app = create_app()
        with pytest.raises(StreamConfigError, match="Duplicate"):
            mount_streams(app, [_Hello, Other])

    def test_two_streams_on_one_class_both_registered(self) -> None:
        class Two:
            @Stream("/chat")
            async def chat(self, body: Annotated[_Greeting, Body()]) -> AsyncGenerator[str]:
                yield body.message

            @Stream("/admin/chat")
            async def admin(self, body: Annotated[_Greeting, Body()]) -> AsyncGenerator[str]:
                yield body.message

        app = create_app()
        mount_streams(app, [Two])
        assert _route_exists(app, "/chat", "POST")
        assert _route_exists(app, "/admin/chat", "POST")


class TestCreateAppStreamsKwarg:
    def test_streams_none_leaves_app_unchanged(self) -> None:
        app = create_app()
        routes_before = list(app.router.routes)
        app2 = create_app(streams=None)
        # Default Starlette has no routes besides the ones we added.
        assert len(app2.router.routes) == len(routes_before)

    def test_streams_kwarg_forwards_to_mount(self) -> None:
        app = create_app(streams=[_Hello])
        assert _route_exists(app, "/hello", "POST")

    def test_streams_kwarg_accepts_instances_too(self) -> None:
        app = create_app(streams=[_Hello(), _AdminHello()])
        assert _route_exists(app, "/hello", "POST")
        assert _route_exists(app, "/admin/hello", "POST")

    def test_end_to_end_hello(self) -> None:
        app = create_app(streams=[_Hello])
        with (
            TestClient(app) as client,
            client.stream("POST", "/hello", json={"message": "world"}) as response,
        ):
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["connection"] == "keep-alive"
            body = b"".join(response.iter_bytes())
        assert body == b"data: hi world\n\n"

    def test_end_to_end_three_tokens(self) -> None:
        class Triplet:
            @Stream("/triplet", heartbeat_seconds=None)
            async def respond(self) -> AsyncGenerator[str]:
                yield "a"
                yield "b"
                yield "c"

        app = create_app(streams=[Triplet])
        with (
            TestClient(app) as client,
            client.stream("POST", "/triplet") as response,
        ):
            body = b"".join(response.iter_bytes())
        assert body == b"data: a\n\ndata: b\n\ndata: c\n\n"


def _route_exists(app: Starlette, path: str, method: str) -> bool:
    for route in app.router.routes:
        path_attr = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path_attr == path and methods is not None and method in methods:
            return True
    return False
