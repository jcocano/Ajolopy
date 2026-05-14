"""The :class:`Dataset` ABC.

``Dataset`` is the abstract source of evaluation cases. Concrete
subclasses MUST implement both ``__iter__`` AND ``__aiter__``: AJ-4's
``@Eval`` runner picks the protocol that matches its own execution
model, and the framework treats both as the authoritative iteration
surface.

We intentionally do NOT default one in terms of the other:

- A synchronous wrapper around ``__aiter__`` deadlocks inside an
  active event loop.
- An asynchronous wrapper around ``__iter__`` is trivial but hides
  the fact that the underlying source performs blocking I/O on the
  event loop. Implementers should KNOW they are doing that.

The contract is "both iterators yield the same cases in the same
order" — this is what AJ-27's regression detection (``--compare-with``)
relies on.

The :func:`resolve_dataset` coercion helper lives in the sibling
``resolver`` module to keep this file cycle-free: importing
``JSONLDataset`` here would induce a ``dataset → jsonl → dataset``
cycle that CodeQL flags even when the import is lazy.
"""

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from .case import Case


class Dataset(abc.ABC):
    """Abstract source of evaluation cases.

    Concrete subclasses MUST implement both ``__iter__`` and
    ``__aiter__`` so consumers can iterate from either sync or async
    contexts without wrappers. The two implementations MUST yield the
    same sequence of cases in the same order — the framework treats
    cases as deterministic (Brief v4.0 §"Datasets deterministas").

    Why both, instead of defaulting one in terms of the other? A sync
    wrapper around ``__aiter__`` deadlocks inside an active event loop;
    an async wrapper around ``__iter__`` is trivial but hides the fact
    that the underlying source is blocking. Forcing both keeps the
    cost-of-blocking-I/O visible at the implementer's call site.
    """

    @abc.abstractmethod
    def __iter__(self) -> Iterator[Case]:
        """Return a synchronous iterator over the dataset's cases."""

    @abc.abstractmethod
    def __aiter__(self) -> AsyncIterator[Case]:
        """Return an asynchronous iterator over the dataset's cases."""


__all__ = ["Dataset"]
