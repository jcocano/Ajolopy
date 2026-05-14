"""Decorator-time validation for ``@Stream``."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from ajolopy.stream import Stream, StreamConfigError, StreamMetadata, get_stream_metadata
from ajolopy.stream.decorator import STREAM_META_ATTR


async def _ok(self: object) -> AsyncGenerator[str]:
    """Sample async generator used by validation tests."""
    yield "x"


class TestStampMetadata:
    def test_stamps_metadata_on_function(self) -> None:
        @Stream("/chat")
        async def respond(self: object, message: str) -> AsyncGenerator[str]:
            yield message

        metadata = get_stream_metadata(respond)
        assert metadata is not None
        assert isinstance(metadata, StreamMetadata)
        assert metadata.path == "/chat"
        assert metadata.method == "POST"
        assert metadata.auth is False
        assert metadata.heartbeat_seconds == pytest.approx(30.0)
        assert metadata.handler is respond

    def test_returns_method_unchanged(self) -> None:
        async def respond(self: object, message: str) -> AsyncGenerator[str]:
            yield message

        decorated = Stream("/chat")(respond)
        assert decorated is respond
        assert hasattr(decorated, STREAM_META_ATTR)

    def test_uppercases_method(self) -> None:
        decorated = Stream("/chat", method="get")(_ok)
        metadata = get_stream_metadata(decorated)
        assert metadata is not None
        assert metadata.method == "GET"

    def test_get_metadata_via_bound_method(self) -> None:
        class Host:
            @Stream("/chat")
            async def respond(self) -> AsyncGenerator[str]:
                yield "hi"

        instance = Host()
        metadata = get_stream_metadata(instance.respond)
        assert metadata is not None
        assert metadata.path == "/chat"


class TestPathValidation:
    def test_empty_path_raises(self) -> None:
        with pytest.raises(StreamConfigError, match="non-empty"):
            Stream("")(_fresh_ok())

    def test_relative_path_raises(self) -> None:
        with pytest.raises(StreamConfigError, match="start with '/'"):
            Stream("chat")(_fresh_ok())


class TestMethodValidation:
    @pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH", "OPTIONS"])
    def test_unsupported_method_raises(self, method: str) -> None:
        with pytest.raises(StreamConfigError, match="not supported"):
            Stream("/chat", method=method)(_fresh_ok())


class TestAuthValidation:
    def test_auth_true_is_legal_at_decoration_time(self) -> None:
        # AJ-17 flipped the reservation: ``auth=True`` is now legal at
        # decoration. The mount-time check (covered in
        # ``tests/guards/test_stream_integration.py``) is the new
        # enforcement point.
        decorated = Stream("/chat", auth=True)(_fresh_ok())
        metadata = get_stream_metadata(decorated)
        assert metadata is not None
        assert metadata.auth is True

    def test_auth_false_is_default_no_op(self) -> None:
        decorated = Stream("/chat")(_fresh_ok())
        metadata = get_stream_metadata(decorated)
        assert metadata is not None
        assert metadata.auth is False

    def test_auth_non_bool_rejected(self) -> None:
        with pytest.raises(StreamConfigError, match="must be a bool"):
            Stream("/chat", auth="true")(_fresh_ok())  # pyright: ignore[reportArgumentType]


class TestHeartbeatValidation:
    def test_zero_heartbeat_raises(self) -> None:
        with pytest.raises(StreamConfigError, match="> 0"):
            Stream("/chat", heartbeat_seconds=0)(_fresh_ok())

    def test_negative_heartbeat_raises(self) -> None:
        with pytest.raises(StreamConfigError, match="> 0"):
            Stream("/chat", heartbeat_seconds=-1.5)(_fresh_ok())

    def test_none_disables_heartbeat(self) -> None:
        decorated = Stream("/chat", heartbeat_seconds=None)(_fresh_ok())
        metadata = get_stream_metadata(decorated)
        assert metadata is not None
        assert metadata.heartbeat_seconds is None

    def test_positive_float_accepted(self) -> None:
        decorated = Stream("/chat", heartbeat_seconds=0.5)(_fresh_ok())
        metadata = get_stream_metadata(decorated)
        assert metadata is not None
        assert metadata.heartbeat_seconds == pytest.approx(0.5)


class TestTargetValidation:
    def test_async_coroutine_rejected(self) -> None:
        async def coroutine() -> str:
            return "hi"

        with pytest.raises(StreamConfigError, match="async generator"):
            # Pyright sees the type mismatch; that is exactly what we test
            # against here, so the runtime check is the source of truth.
            Stream("/chat")(coroutine)  # pyright: ignore[reportArgumentType]

    def test_sync_function_rejected(self) -> None:
        def sync() -> str:
            return "hi"

        with pytest.raises(StreamConfigError, match="async generator"):
            Stream("/chat")(sync)  # pyright: ignore[reportArgumentType]

    def test_sync_generator_rejected(self) -> None:
        def gen() -> Any:
            yield "hi"

        with pytest.raises(StreamConfigError, match="async generator"):
            Stream("/chat")(gen)

    def test_stacked_stream_decorators_rejected(self) -> None:
        @Stream("/chat")
        async def respond(self: object) -> AsyncGenerator[str]:
            yield "hi"

        with pytest.raises(StreamConfigError, match="stacked"):
            Stream("/other")(respond)


def _fresh_ok() -> Any:
    """Return a fresh async generator function for each test.

    Reusing one decorated function would re-trigger the "already stamped"
    guard after the first test in a parameterised set; building a new
    function per call keeps each test isolated.
    """

    async def respond(self: object) -> AsyncGenerator[str]:
        yield "x"

    return respond
