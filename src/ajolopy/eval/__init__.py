"""Public surface of the ``ajolopy.eval`` dataset layer.

AJ-25 ships the data-layer pieces that AJ-4 (``@Eval`` decorator) will
consume:

- :class:`Case` — one ``{input, expected}`` pair.
- :class:`Dataset` — the abstract source ABC.
- :class:`JSONLDataset` — the v0.1 concrete loader.
- :func:`resolve_dataset` — coerce ``str``/``Path``/instance/subclass
  forms into a :class:`Dataset`.
- The :class:`DatasetError` hierarchy.

No top-level re-exports are added to :mod:`ajolopy`; AJ-4 will decide
whether ``@Eval`` deserves a top-level alias.
"""

from .case import Case
from .dataset import Dataset, resolve_dataset
from .errors import DatasetError, DatasetFileError, DatasetSchemaError
from .jsonl import JSONLDataset

__all__ = [
    "Case",
    "Dataset",
    "DatasetError",
    "DatasetFileError",
    "DatasetSchemaError",
    "JSONLDataset",
    "resolve_dataset",
]
