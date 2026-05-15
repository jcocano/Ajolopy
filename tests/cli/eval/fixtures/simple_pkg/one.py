"""Submodule fixture exposing one extra ``@Eval`` class."""

from ajolopy.eval.eval_decorator import EVAL_MARKER
from tests.cli.eval.fixtures.simple_pkg import _make_metadata, _PkgAgent


class SubmoduleSuite:
    """Submodule-level suite (declaration order: 3rd)."""


setattr(SubmoduleSuite, EVAL_MARKER, _make_metadata(SubmoduleSuite, _PkgAgent))
