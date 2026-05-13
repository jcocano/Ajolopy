"""Edge-case errors that should surface at config / mount time."""

import pytest

from ajolopy.http import HttpHandlerConfigError, create_app
from ajolopy.routes import Get, mount_routes


class _BadParamAnnotation:
    @Get("/x")
    async def handler(self, missing_annotation) -> dict[str, str]:
        # ``missing_annotation`` deliberately lacks an annotation — that
        # is the misconfiguration this test exercises.
        return {"ok": str(missing_annotation)}


def test_missing_annotation_propagates_as_http_handler_config_error() -> None:
    """AJ-15's introspector rejects unannotated params verbatim."""
    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="no type annotation"):
        mount_routes(app, [_BadParamAnnotation])


def test_handler_with_unsupported_body_type_propagates() -> None:
    """Unsupported ``Body()`` types raise the AJ-15 error verbatim."""
    from typing import Annotated

    from ajolopy.http import Body

    class Bad:
        @Get("/x")
        async def handler(self, body: Annotated[object, Body()]) -> dict[str, str]:
            return {"ok": "yes"}

    app = create_app()
    with pytest.raises(HttpHandlerConfigError, match="unsupported Body"):
        mount_routes(app, [Bad])
