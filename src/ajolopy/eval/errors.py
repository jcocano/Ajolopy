"""Errors raised by the ``ajolopy.eval`` dataset layer.

All errors derive from :class:`DatasetError` so callers catch the
framework with a single ``except``. Subclasses signal distinct failure
modes:

- :class:`DatasetFileError` — the dataset file is missing, unreadable,
  or not a regular file (e.g. a directory was passed in by mistake).
- :class:`DatasetSchemaError` — the file was readable but its contents
  do not match the ``{input, expected}`` JSONL contract. Carries a
  ``.line`` attribute (``int | None``) so future tooling (e.g.
  ``ajolopy eval --validate``) can surface the offending line without
  re-parsing the message string. ``.line`` is ``None`` for whole-file
  errors such as "dataset is empty".
"""


class DatasetError(Exception):
    """Base class for any error raised by the dataset layer."""


class DatasetFileError(DatasetError):
    """The dataset file is missing, not a file, or unreadable."""


class DatasetSchemaError(DatasetError):
    """The dataset contents do not match the ``{input, expected}`` contract.

    ``line`` is the 1-based file line where the problem was detected, or
    ``None`` for whole-file errors (empty dataset).
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line: int | None = line


__all__ = [
    "DatasetError",
    "DatasetFileError",
    "DatasetSchemaError",
]
