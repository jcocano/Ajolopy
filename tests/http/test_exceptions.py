"""Tests for the ``HttpException`` hierarchy."""

import pytest

from ajolopy.http import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    HttpException,
    InternalServerErrorException,
    NotFoundException,
    UnauthorizedException,
    UnprocessableEntityException,
)


def test_base_exception_defaults_to_500_and_carries_message():
    exc = HttpException("boom")

    assert isinstance(exc, Exception)
    assert exc.status == 500
    assert exc.message == "boom"
    assert exc.details is None


def test_base_exception_accepts_ad_hoc_status_and_details():
    exc = HttpException("teapot", status=418, details={"hint": "tea"})

    assert exc.status == 418
    assert exc.message == "teapot"
    assert exc.details == {"hint": "tea"}


@pytest.mark.parametrize(
    ("exc_cls", "expected_status"),
    [
        (BadRequestException, 400),
        (UnauthorizedException, 401),
        (ForbiddenException, 403),
        (NotFoundException, 404),
        (ConflictException, 409),
        (UnprocessableEntityException, 422),
        (InternalServerErrorException, 500),
    ],
)
def test_canonical_subclasses_preset_status(exc_cls, expected_status):
    exc = exc_cls("oh no")

    assert exc.status == expected_status
    assert exc.message == "oh no"
    assert exc.details is None
    assert isinstance(exc, HttpException)


def test_subclass_can_carry_details():
    exc = NotFoundException("user gone", details={"user_id": "u_1"})

    assert exc.status == 404
    assert exc.details == {"user_id": "u_1"}


def test_user_can_define_custom_subclass_with_class_level_status():
    class TeapotException(HttpException):
        status: int = 418

    exc = TeapotException("short and stout")

    assert exc.status == 418
    assert isinstance(exc, HttpException)


def test_subclass_raised_is_catchable_as_base():
    def _raise_not_found() -> None:
        raise NotFoundException("x")

    # Wrapping the ``raise`` in a helper keeps CodeQL's flow analysis happy:
    # it does not model ``pytest.raises`` as catching, so a bare ``raise``
    # directly inside the ``with`` body trips its "unreachable code" check.
    with pytest.raises(HttpException) as info:
        _raise_not_found()

    assert info.value.status == 404


def test_repr_includes_class_status_and_message():
    rep = repr(NotFoundException("missing"))

    assert "NotFoundException" in rep
    assert "404" in rep
    assert "missing" in rep
