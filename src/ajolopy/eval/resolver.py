"""The :func:`resolve_dataset` coercion helper.

Lives in its own module to keep ``ajolopy.eval.dataset`` cycle-free:
``dataset.py`` cannot import :class:`~ajolopy.eval.jsonl.JSONLDataset`
without inducing a ``dataset → jsonl → dataset`` cycle (CodeQL flags
the lazy in-function import as a cycle anyway). Concentrating the
imports in this small module keeps the topology readable.

:func:`resolve_dataset` is the single entry point AJ-4 will call when
coercing the ``@Eval(dataset=...)`` kwarg. v0.2 grows the accepted
forms (URL strings → HTTP loader, manifest files, generated datasets)
by extending this module without re-touching the eval surface.
"""

import os

from .dataset import Dataset
from .errors import DatasetError
from .jsonl import JSONLDataset


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
        return JSONLDataset(spec)
    raise DatasetError(
        "@Eval(dataset=) accepts str, os.PathLike, a Dataset instance, "
        f"or a Dataset subclass; got {type(spec).__name__}."  # pyright: ignore[reportUnreachable]
    )


__all__ = ["resolve_dataset"]
