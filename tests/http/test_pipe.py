"""Tests for the ``Pipe`` ABC + ``ValidationPipe`` default + escape hatch."""

from typing import Annotated, override

from starlette.testclient import TestClient

from ajolopy.http import Pipe, Query, ResolvedParam, ValidationPipe, add_route, create_app


def test_pipe_abc_cannot_be_instantiated_directly():
    import pytest

    with pytest.raises(TypeError, match="abstract"):
        Pipe()  # type: ignore[abstract]


def test_validation_pipe_is_concrete_pipe():
    assert isinstance(ValidationPipe(), Pipe)


def test_default_pipe_is_validation_pipe_instance():
    app = create_app()
    assert isinstance(app.state.ajolopy_pipe, ValidationPipe)


def test_custom_pipe_overrides_default_validation():
    class FixedPipe(Pipe):
        """Return a hardcoded value for every query parameter."""

        @override
        async def transform(self, value: object, *, param: ResolvedParam) -> object:
            return 99 if param.source.value == "query" else value

    async def handler(page: Annotated[int, Query()]) -> dict[str, int]:
        return {"page": page}

    app = create_app(pipe=FixedPipe())
    add_route(app, "GET", "/x", handler)
    response = TestClient(app).get("/x?page=1")

    # The custom pipe ignores the input and returns 99.
    assert response.json() == {"page": 99}
