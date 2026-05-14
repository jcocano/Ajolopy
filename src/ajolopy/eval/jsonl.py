"""The :class:`JSONLDataset` concrete loader.

JSONL is the v0.1 default for evaluation datasets (Brief v4.0
§"Killer demo Paso 2"). One JSON object per line, each with at minimum
the ``input`` and ``expected`` keys. Extra keys are tolerated so users
can annotate cases with ``tags`` / ``comment`` / ``disabled`` without
the framework rejecting them — forward compatibility for v0.2 features.

Lifecycle:

- ``__init__`` runs **eager** validation. The file is opened, read in
  full, split by newlines, and every non-blank line is JSON-parsed and
  shape-checked. Any failure raises a :class:`DatasetError` subclass
  before the caller can iterate.
- ``__iter__`` / ``__aiter__`` perform **lazy** :class:`Case`
  materialisation: the parsed ``dict`` list is stored and a fresh
  :class:`Case` is built on every yield. This keeps construction cheap
  while still surfacing all schema errors before the eval runner picks
  up the first case.
"""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

from .case import Case
from .dataset import Dataset
from .errors import DatasetFileError, DatasetSchemaError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


class JSONLDataset(Dataset):
    """Load evaluation cases from a JSON Lines file.

    The constructor resolves ``path`` against :func:`os.getcwd` (if
    relative) and eagerly validates the file's contents. Iteration
    yields :class:`Case` instances in file order via both the sync and
    async protocols.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        try:
            resolved = Path(os.fspath(path)).resolve()
        except (TypeError, ValueError, OSError) as exc:
            raise DatasetFileError(f"Could not resolve dataset path {path!r}: {exc}") from exc

        try:
            text = resolved.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise DatasetFileError(f"Dataset file not found: {resolved}") from exc
        except IsADirectoryError as exc:
            raise DatasetFileError(f"Dataset path is a directory, not a file: {resolved}") from exc
        except PermissionError as exc:
            raise DatasetFileError(f"Dataset file is not readable: {resolved}") from exc
        except OSError as exc:
            raise DatasetFileError(f"Could not read dataset file {resolved}: {exc}") from exc

        records: list[dict[str, Any]] = []
        for line_no, raw_line in enumerate(text.split("\n"), start=1):
            # Blank / whitespace-only lines are skipped but DO advance the
            # line counter so diagnostics match the editor view (e.g. a
            # trailing newline at EOF is silent, not flagged).
            if raw_line.strip() == "":
                continue
            records.append(_validate_line(raw_line, line_no))

        if not records:
            raise DatasetSchemaError("dataset is empty", line=None)

        self._path: Path = resolved
        self._records: list[dict[str, Any]] = records

    @property
    def path(self) -> Path:
        """Absolute path to the JSONL file (resolved at construction)."""
        return self._path

    def __len__(self) -> int:
        return len(self._records)

    @override
    def __iter__(self) -> Iterator[Case]:
        for record in self._records:
            yield Case(input=record["input"], expected=record["expected"])

    @override
    async def __aiter__(self) -> AsyncIterator[Case]:
        for record in self._records:
            yield Case(input=record["input"], expected=record["expected"])


def _validate_line(raw_line: str, line_no: int) -> dict[str, Any]:
    """Parse and shape-check a single non-blank JSONL line.

    Returns the validated ``dict`` (with ``input`` and ``expected``
    keys guaranteed to be ``dict`` instances). Extra keys on the case
    are preserved but ignored by the iterator.
    """
    try:
        parsed = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise DatasetSchemaError(f"line {line_no}: invalid JSON: {exc.msg}", line=line_no) from exc

    if not isinstance(parsed, dict):
        raise DatasetSchemaError(
            f"line {line_no}: case must be a JSON object",
            line=line_no,
        )

    record = cast("dict[str, Any]", parsed)
    for key in ("input", "expected"):
        if key not in record:
            raise DatasetSchemaError(
                f"line {line_no}: missing required key {key!r}",
                line=line_no,
            )
        if not isinstance(record[key], dict):
            raise DatasetSchemaError(
                f"line {line_no}: {key!r} must be a JSON object",
                line=line_no,
            )

    return record


__all__ = ["JSONLDataset"]
