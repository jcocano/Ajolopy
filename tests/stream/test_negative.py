"""Edge-case errors that should surface at config / mount time."""

from collections.abc import AsyncGenerator
from typing import Annotated

import pytest

from ajolopy.http import Body, HttpHandlerConfigError, create_app
from ajolopy.stream import Stream, StreamConfigError


class _Bad:
    @Stream("/chat")
    async def respond(self, body: Annotated[object, Body()]) -> AsyncGenerator[str]:
        yield "ok"


def test_unsupported_body_type_raises_at_mount() -> None:
    with pytest.raises(HttpHandlerConfigError, match="unsupported Body"):
        create_app(streams=[_Bad])


def test_duplicate_decorator_on_same_method_raises() -> None:
    async def double(self: object) -> AsyncGenerator[str]:
        yield "x"

    inner = Stream("/b")(double)
    with pytest.raises(StreamConfigError, match="stacked"):
        Stream("/a")(inner)
