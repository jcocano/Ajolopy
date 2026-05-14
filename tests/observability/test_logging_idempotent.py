"""configure_logging must be idempotent; second calls are no-ops."""

import logging

from ajolopy.observability.logging import (
    _reset_for_tests as reset_logging,
)
from ajolopy.observability.logging import configure_logging


def test_second_call_does_not_double_install_handler() -> None:
    root = logging.getLogger()
    baseline = len(root.handlers)

    configure_logging("production")
    after_first = len(root.handlers)
    assert after_first == baseline + 1

    configure_logging("production")
    after_second = len(root.handlers)
    assert after_second == after_first, (
        f"second configure_logging call attached an extra handler: {after_first} -> {after_second}"
    )


def test_second_call_does_not_swap_renderer_or_threshold() -> None:
    configure_logging("production", log_level="ERROR")
    initial_handlers = list(logging.getLogger().handlers)
    initial_level = logging.getLogger().getEffectiveLevel()

    # A subsequent call requesting development+DEBUG must be ignored — the
    # first call wins. The "escape hatch" is `_reset_for_tests` (private).
    configure_logging("development", log_level="DEBUG")

    assert logging.getLogger().handlers == initial_handlers
    assert logging.getLogger().getEffectiveLevel() == initial_level


def test_reset_for_tests_undoes_install_and_re_enables_configure() -> None:
    root = logging.getLogger()
    baseline = len(root.handlers)

    configure_logging("production")
    assert len(root.handlers) == baseline + 1

    reset_logging()
    assert len(root.handlers) == baseline

    # After reset, a fresh configure_logging call must install again.
    configure_logging("development")
    assert len(root.handlers) == baseline + 1
