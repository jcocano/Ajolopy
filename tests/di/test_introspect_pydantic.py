"""Container introspection works for pydantic-settings ``BaseSettings``.

``BaseSettings.__init__`` uses ``__pydantic_self__`` as the implicit
first parameter (lets users declare a field named "self") and several
``_``-prefixed configuration kwargs. The container must skip both
conventions so any ``BaseConfig`` subclass resolves cleanly.

The env var names are intentionally lowercase: ``BaseConfig`` sets
``case_sensitive=True`` so the env key must match the field name
verbatim. ``# noqa: SIM112`` is needed on every line that reads or
writes ``os.environ`` for those keys.
"""

import os

from ajolopy.config import BaseConfig
from ajolopy.di import Container


class _CfgWithRequiredField(BaseConfig):
    """Subclass with one required env var so the resolve actually loads."""

    test_introspect_var: str


def test_container_resolves_baseconfig_subclass() -> None:
    """A ``BaseConfig`` subclass with required env vars resolves cleanly."""
    os.environ["test_introspect_var"] = "hello"  # noqa: SIM112 — case-sensitive field
    try:
        container = Container()
        container.register(_CfgWithRequiredField)
        instance = container.resolve(_CfgWithRequiredField)
        assert instance.test_introspect_var == "hello"
    finally:
        del os.environ["test_introspect_var"]  # noqa: SIM112 — case-sensitive field


def test_container_resolves_class_consuming_baseconfig() -> None:
    """A regular ``@Injectable``-style class can take a BaseConfig dep."""
    os.environ["test_introspect_var"] = "wired"  # noqa: SIM112 — case-sensitive field
    try:

        class Consumer:
            def __init__(self, cfg: _CfgWithRequiredField) -> None:
                self.cfg = cfg

        container = Container()
        container.register(_CfgWithRequiredField)
        container.register(Consumer)
        consumer = container.resolve(Consumer)
        assert consumer.cfg.test_introspect_var == "wired"
    finally:
        del os.environ["test_introspect_var"]  # noqa: SIM112 — case-sensitive field


def test_introspect_skips_underscore_prefixed_params() -> None:
    """A class whose ``__init__`` has underscore params is resolvable."""
    from ajolopy.di._introspect import introspect_dependencies

    class WithPrivate:
        def __init__(self, db: object, _internal: str = "default") -> None:
            self.db = db
            self.internal = _internal

    deps = introspect_dependencies(WithPrivate)
    # Only ``db`` is collected; ``_internal`` is treated as private and
    # skipped (the class keeps its default).
    assert list(deps.keys()) == ["db"]


def test_introspect_skips_pydantic_self_alias() -> None:
    """``__pydantic_self__`` is treated like ``self`` and skipped."""
    from ajolopy.di._introspect import introspect_dependencies

    class FakePydantic:
        # Match pydantic-settings's signature shape — ``__pydantic_self__``
        # in place of ``self``, a real dep param next to it.
        def __init__(__pydantic_self__, db: object) -> None:  # noqa: N805 — mirroring pydantic's convention  # pyright: ignore[reportSelfClsParameterName]
            __pydantic_self__.db = db

    deps = introspect_dependencies(FakePydantic)
    assert list(deps.keys()) == ["db"]
