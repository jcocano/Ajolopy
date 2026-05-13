"""Decoration-time validation for ``@Get`` / ``@Post`` / ``@Put`` / ``@Patch`` / ``@Delete``."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from ajolopy.routes import (
    Delete,
    Get,
    Patch,
    Post,
    Put,
    RouteConfigError,
    RouteMetadata,
    get_route_metadata,
)
from ajolopy.routes.decorator import ROUTE_META_ATTR
from ajolopy.stream import Stream, StreamConfigError


class TestStampMetadata:
    def test_get_stamps_metadata_on_function(self) -> None:
        @Get("/users")
        async def list_users(self: object) -> dict[str, object]:
            return {"items": []}

        metadata = get_route_metadata(list_users)
        assert metadata is not None
        assert isinstance(metadata, RouteMetadata)
        assert metadata.method == "GET"
        assert metadata.path == "/users"
        assert metadata.handler is list_users

    def test_returns_method_unchanged(self) -> None:
        async def handler(self: object) -> dict[str, str]:
            return {"ok": "yes"}

        decorated = Get("/health")(handler)
        assert decorated is handler
        assert hasattr(decorated, ROUTE_META_ATTR)

    @pytest.mark.parametrize(
        ("decorator", "verb"),
        [
            (Post, "POST"),
            (Put, "PUT"),
            (Patch, "PATCH"),
            (Delete, "DELETE"),
        ],
    )
    def test_other_verbs_stamp_correct_method(
        self,
        decorator: Any,
        verb: str,
    ) -> None:
        @decorator("/users")
        async def handler(self: object) -> dict[str, str]:
            return {"id": "u_1"}

        metadata = get_route_metadata(handler)
        assert metadata is not None
        assert metadata.method == verb
        assert metadata.path == "/users"
        assert metadata.handler is handler

    def test_metadata_via_bound_method(self) -> None:
        class Host:
            @Get("/users")
            async def list_users(self) -> dict[str, str]:
                return {"ok": "yes"}

        instance = Host()
        metadata = get_route_metadata(instance.list_users)
        assert metadata is not None
        assert metadata.path == "/users"
        assert metadata.method == "GET"

    def test_sync_handler_is_supported(self) -> None:
        # AJ-15's add_route accepts sync handlers; route decorators
        # mirror that — the decorator itself only cares about metadata.
        @Get("/health")
        def health(self: object) -> dict[str, str]:
            return {"status": "ok"}

        metadata = get_route_metadata(health)
        assert metadata is not None
        assert metadata.method == "GET"


class TestPathValidation:
    @pytest.mark.parametrize("decorator", [Get, Post, Put, Patch, Delete])
    def test_empty_path_raises(self, decorator: Any) -> None:
        with pytest.raises(RouteConfigError, match="non-empty"):
            decorator("")(_fresh_handler())

    @pytest.mark.parametrize("decorator", [Get, Post, Put, Patch, Delete])
    def test_relative_path_raises(self, decorator: Any) -> None:
        with pytest.raises(RouteConfigError, match="start with '/'"):
            decorator("users")(_fresh_handler())

    @pytest.mark.parametrize(
        "path",
        [
            "/users/:user_id",
            "/users/:id/posts",
            "/:root",
        ],
    )
    def test_express_style_param_segment_raises(self, path: str) -> None:
        with pytest.raises(RouteConfigError, match="Express-style"):
            Get(path)(_fresh_handler())

    def test_starlette_style_param_segment_accepted(self) -> None:
        @Get("/users/{user_id}")
        async def get_user(self: object) -> dict[str, str]:
            return {"id": "u_1"}

        metadata = get_route_metadata(get_user)
        assert metadata is not None
        assert metadata.path == "/users/{user_id}"


class TestStacking:
    def test_two_route_decorators_on_same_method_raises(self) -> None:
        @Get("/users")
        async def handler(self: object) -> dict[str, str]:
            return {"ok": "yes"}

        with pytest.raises(RouteConfigError, match="stacked"):
            Post("/users")(handler)

    def test_two_same_verb_decorators_on_same_method_raise(self) -> None:
        @Get("/users")
        async def handler(self: object) -> dict[str, str]:
            return {"ok": "yes"}

        with pytest.raises(RouteConfigError, match="stacked"):
            Get("/other")(handler)

    def test_route_on_top_of_stream_raises(self) -> None:
        @Stream("/chat")
        async def respond(self: object) -> AsyncGenerator[str]:
            yield "hi"

        with pytest.raises(RouteConfigError, match="@Stream"):
            Get("/chat")(respond)

    def test_stream_on_top_of_route_is_rejected_by_stream_layer(self) -> None:
        # AJ-3 owns the symmetric guard. ``@Stream`` requires an
        # async-generator target; an ``async def`` already decorated
        # with ``@Get`` is a regular coroutine, so ``@Stream`` rejects
        # it for that reason (still surfacing as a config error,
        # though under the stream layer's exception type).
        @Get("/health")
        async def handler(self: object) -> dict[str, str]:
            return {"status": "ok"}

        with pytest.raises(StreamConfigError, match="async generator"):
            Stream("/health")(handler)  # pyright: ignore[reportArgumentType]


def _fresh_handler() -> Any:
    """Return a fresh async function for each test.

    Reusing one decorated function would re-trigger the "already
    stamped" guard after the first test in a parameterised set; building
    a new function per call keeps each test isolated.
    """

    async def handler(self: object) -> dict[str, str]:
        return {"ok": "yes"}

    return handler
