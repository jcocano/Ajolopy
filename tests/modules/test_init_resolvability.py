"""Acceptance: __init__ resolvability — early check, HTTP marker skip."""

from typing import Annotated

import pytest

from ajolopy import Module, compile_module
from ajolopy.http import Body, Param, Query
from ajolopy.modules import ModuleVisibilityError


class Db:
    pass


def test_unresolvable_dependency_raises_before_resolve() -> None:
    """A provider depending on a token outside its visibility set fails
    at compile time, not at first resolve()."""

    class Service:
        def __init__(self, db: Db) -> None:
            self.db = db

    @Module(providers=[Service])  # Db not provided anywhere
    class M:
        pass

    with pytest.raises(ModuleVisibilityError) as info:
        compile_module(M)
    msg = str(info.value)
    assert "Service" in msg
    assert "Db" in msg


def test_annotated_http_markers_are_skipped() -> None:
    """HTTP layer markers belong to AJ-15, not DI; the compiler treats
    them as runtime-resolved (no visibility check)."""

    class FakeDto:
        pass

    class Controller:
        # Mix DI (Db) with HTTP markers; Db must be visible, the markers
        # must NOT trigger a visibility error.
        def __init__(
            self,
            db: Db,
            body: Annotated[FakeDto, Body()],
            page: Annotated[int, Query()] = 1,
            user_id: Annotated[str, Param()] = "",
        ) -> None:
            self.db = db
            self.body = body
            self.page = page
            self.user_id = user_id

    @Module(providers=[Db, Controller])
    class M:
        pass

    # No visibility error — markers skipped, only Db gated.
    compiled = compile_module(M)
    assert isinstance(compiled.container.resolve(Db), Db)


def test_provider_without_init_compiles() -> None:
    """A bare class with no __init__ (object.__init__) has no deps."""

    class Simple:
        pass

    @Module(providers=[Simple])
    class M:
        pass

    compiled = compile_module(M)
    assert isinstance(compiled.container.resolve(Simple), Simple)
