"""The :class:`Dataset` ABC + the :func:`resolve_dataset` coercion helper.

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

:func:`resolve_dataset` is the single entry point AJ-4 will call when
coercing the ``@Eval(dataset=...)`` kwarg. Keeping the coercion logic
here means v0.2 can grow the accepted forms (URL strings → HTTP loader,
manifest files, generated datasets) without re-touching the eval
surface.
"""

import abc
import os
from typing import TYPE_CHECKING

from .errors import DatasetError

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


def resolve_dataset(
    spec: str | os.PathLike[str] | Dataset | type[Dataset],
) -> Dataset:
    """Coerce ``spec`` into a concrete :class:`Dataset` instance.

    Accepted forms:

    - A :class:`Dataset` instance is returned verbatim.
    - A :class:`Dataset` subclass is instantiated with zero arguments;
      a required-arg ``__init__`` raises :class:`DatasetError` with a
      hint to pass an instance instead.
    - A ``str`` or :class:`os.PathLike` is wrapped in
      :class:`~ajolopy.eval.jsonl.JSONLDataset`.

    Anything else raises :class:`DatasetError` listing the accepted
    forms — this is the single chokepoint AJ-4 uses to validate the
    ``@Eval(dataset=...)`` kwarg, so a clear error message here saves
    the user a stack trace later.
    """
    # Order matters: a ``type[Dataset]`` is also callable, so check it
    # before the path-like branch — otherwise passing ``JSONLDataset``
    # (the class) would be silently coerced into a path string and fail
    # with an unrelated file-not-found error. Pyright sees the union
    # already narrowed by the static type, but at runtime callers can
    # pass any object; the defensive checks stay.
    if isinstance(spec, Dataset):
        return spec
    if isinstance(spec, type) and issubclass(spec, Dataset):  # pyright: ignore[reportUnnecessaryIsInstance]
        try:
            return spec()
        except TypeError as exc:
            raise DatasetError(
                f"{spec.__name__} requires constructor arguments; pass an "
                f"instance instead (e.g. {spec.__name__}(...))."
            ) from exc
    if isinstance(spec, (str, os.PathLike)):  # pyright: ignore[reportUnnecessaryIsInstance]
        from .jsonl import JSONLDataset

        return JSONLDataset(spec)
    raise DatasetError(
        "@Eval(dataset=) accepts str, os.PathLike, a Dataset instance, "
        f"or a Dataset subclass; got {type(spec).__name__}."  # pyright: ignore[reportUnreachable]
    )


__all__ = ["Dataset", "resolve_dataset"]
