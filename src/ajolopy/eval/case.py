"""The :class:`Case` dataclass — one ``{input, expected}`` pair.

``Case`` is the minimal data carrier shared by every ``Dataset``
implementation. It is intentionally tiny:

- ``input`` and ``expected`` are :class:`~collections.abc.Mapping`
  values so concrete ``dict[str, Any]`` works in the common path and
  other mapping types (e.g. :class:`types.MappingProxyType`) compose
  without coercion.
- The dataclass is ``frozen=True`` so metrics cannot accidentally
  mutate a case mid-iteration; the eval framework treats datasets as
  deterministic (Brief v4.0 §"Datasets deterministas").
- ``slots=True`` keeps construction cheap — a large eval suite may
  build thousands of cases per run.

``Case`` has no helpers / methods on purpose; AJ-4 will layer
``Result`` and ``Score`` types on top.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(slots=True, frozen=True)
class Case:
    """One evaluation case: an input mapping and the expected outcome."""

    input: Mapping[str, Any]
    expected: Mapping[str, Any]


__all__ = ["Case"]
