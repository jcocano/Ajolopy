# AJ-25 — `Dataset` base class + JSONL loader

> Tracked in [`board.json`](../board.json) as `AJ-25`. Status, owner, branch, and
> dependencies live there — do not duplicate them in this file.
>
> Source of truth: Brief v4.0 §"Killer demo Paso 2" (which calls `@Eval`
> with `dataset="evals/support.jsonl"`) and `09 - Eval framework` §"Dataset
> format (JSONL)". If this file ever conflicts with the Brief, the Brief
> wins.
>
> This item is **data-layer only**: it ships the dataset abstraction +
> the JSONL concrete loader so AJ-4 (`@Eval`) has something to consume.
> No `@Eval` plumbing lands here; that's AJ-4's job.

## What

`Dataset` is the abstract base class for any source of evaluation cases.
The framework ships one concrete implementation in v0.1: `JSONLDataset`.

Concretely the layer provides:

1. A frozen `Case` dataclass holding one input/expected pair.
2. A `Dataset` ABC with two abstract iteration methods (`__iter__` AND
   `__aiter__`), so both sync and async consumers (e.g. CLI helpers,
   `@Eval` runners) work without converting between worlds.
3. A `JSONLDataset` concrete class that loads cases from a JSONL file.
   Validation runs eagerly at construction; iteration yields `Case`
   objects lazily.
4. A `resolve_dataset(spec)` helper that AJ-4 will call when the user
   passes `@Eval(dataset=...)`. v0.1 surface: accepts a path string, a
   `pathlib.Path`, a `Dataset` instance, or a `Dataset` subclass.
5. A `DatasetError` hierarchy covering file errors and schema errors,
   with line numbers for every JSONL diagnostic.

## Why

Brief v4.0 §"Killer demo Paso 2" literally writes
`dataset="evals/support.jsonl"`. The wedge user (AI Engineer at a Series
A) curates a handful of representative interactions in a JSONL file and
treats that as the regression suite for the agent. Without this layer
the eval framework cannot ship.

The "default mágico + escape hatch" rule applies:

- **Default mágico**: pass `dataset="evals/support.jsonl"` and the
  framework figures out the loader, path resolution, and validation.
- **Escape hatch**: subclass `Dataset` (Notion DB, S3 prefix, HTTP API,
  generated cases) and pass either the class or an instance.

## Public surface (v0.1)

```python
from ajolopy.eval import (
    Case,
    Dataset,
    DatasetError,
    DatasetFileError,
    DatasetSchemaError,
    JSONLDataset,
    resolve_dataset,
)
```

A user-facing example (AJ-4 will wire this into `@Eval`):

```python
ds = JSONLDataset("evals/support.jsonl")

# Sync consumption:
for case in ds:
    print(case.input, case.expected)

# Async consumption:
async for case in ds:
    await agent.run(case.input["message"])
```

### `Case`

```python
@dataclass(slots=True, frozen=True)
class Case:
    input: Mapping[str, Any]
    expected: Mapping[str, Any]
```

Frozen + slotted: metrics cannot mutate the case across iterations, and
construction is cheap (slots). Both fields are `Mapping[str, Any]` so a
`dict[str, Any]` works in the common path and other mapping types
(e.g. `MappingProxyType`) compose without coercion.

`Case` only carries the data; it has no helpers / methods. AJ-4 will
add `Result` / `Score` types on top.

### `Dataset` ABC

```python
class Dataset(abc.ABC):
    """Abstract source of evaluation cases.

    Concrete subclasses MUST implement both ``__iter__`` and
    ``__aiter__`` so consumers can iterate from either sync or async
    contexts without wrappers. The two implementations MUST yield the
    same sequence of cases in the same order — the framework treats
    cases as deterministic (Brief v4.0 §"Datasets deterministas").
    """

    @abc.abstractmethod
    def __iter__(self) -> Iterator[Case]: ...

    @abc.abstractmethod
    def __aiter__(self) -> AsyncIterator[Case]: ...
```

Both methods are abstract. We intentionally do NOT default one in terms
of the other:

- Synchronous wrappers around `__aiter__` deadlock inside an active
  event loop.
- Asynchronous wrappers around `__iter__` are trivial but mask the fact
  that the underlying source is sync — implementers should KNOW they
  are doing blocking I/O on the event loop.

The contract is "both yield the same cases in the same order". AJ-4
chooses which one to call based on its own execution model.

### `JSONLDataset`

```python
class JSONLDataset(Dataset):
    def __init__(self, path: str | os.PathLike[str]) -> None: ...

    def __iter__(self) -> Iterator[Case]: ...

    def __aiter__(self) -> AsyncIterator[Case]: ...

    @property
    def path(self) -> Path: ...

    def __len__(self) -> int:  # number of cases
        ...
```

Semantics:

1. **Path resolution at construction.** `path` is wrapped in
   `pathlib.Path`. Relative paths resolve via `Path(path).resolve()`
   against `os.getcwd()`. Absolute paths pass through.
2. **Eager file open + JSON parse at construction.** The file is
   read in full, split by newlines, and each line is parsed via
   `json.loads(line)`. Empty lines and pure-whitespace lines are
   skipped (NOT counted as cases) so editors that auto-append a final
   newline don't trigger a schema error.
3. **Eager shape validation.** Each parsed JSON value must be a
   `dict` with `input` and `expected` keys, both of which must
   themselves be `dict` objects. Extra keys are allowed (forward-compat
   for user-defined annotations).
4. **Lazy `Case` materialisation.** The parsed `dict` list is stored;
   `Case` instances are built on each iteration (sync or async). This
   matches the "eager validation + lazy yield" decision from the spec
   round.
5. **Both iterators yield identical cases in identical order**, file
   line order.
6. **`__len__` is the number of valid cases**, useful for AJ-4 progress
   reporting.

Failure modes (all `DatasetError` subclasses):

- File missing → `DatasetFileError` with the resolved path.
- File not a file (e.g. a directory) → `DatasetFileError`.
- File unreadable (permission denied, IO error) → `DatasetFileError`.
- Empty file (no valid cases) → `DatasetSchemaError("dataset is empty")`.
- Malformed JSON on line N → `DatasetSchemaError("line N: invalid JSON: <reason>")`.
- Top-level non-object on line N (e.g. `["x"]`) →
  `DatasetSchemaError("line N: case must be a JSON object")`.
- Missing `input` or `expected` key on line N →
  `DatasetSchemaError("line N: missing required key 'input'")`.
- `input` or `expected` not a JSON object →
  `DatasetSchemaError("line N: 'input' must be a JSON object")`.

Line numbers count from 1 and match the file (skipped blank lines DO
advance the counter so the diagnostic points at the actual line in the
editor).

### `resolve_dataset(spec)`

```python
def resolve_dataset(
    spec: str | os.PathLike[str] | Dataset | type[Dataset],
) -> Dataset: ...
```

Accepted forms (used by AJ-4 to coerce the `@Eval(dataset=...)` kwarg):

| Form                       | Behaviour                                        |
|----------------------------|--------------------------------------------------|
| `str` / `os.PathLike`      | Wrap in `JSONLDataset(spec)`.                     |
| `Dataset` instance         | Return verbatim.                                  |
| `type[Dataset]` subclass   | Instantiate with `Cls()`; required-arg `__init__` raises `DatasetError`. |

Anything else (`int`, `list`, etc.) → `DatasetError` with the accepted
forms listed. The helper is the SINGLE entry point AJ-4 will call —
keeping the coercion logic out of `@Eval` itself so v0.2 can extend
(e.g. URL strings → HTTP loader) without re-touching the eval surface.

### Error hierarchy

```python
class DatasetError(Exception):
    """Base for any error related to a Dataset."""

class DatasetFileError(DatasetError):
    """File missing, unreadable, or not a file."""

class DatasetSchemaError(DatasetError):
    """Dataset contents do not match the {input, expected} contract."""
```

`DatasetSchemaError` instances carry a `.line` attribute (`int | None`)
so future tooling (`ajolopy eval --validate`) can surface line numbers
without re-parsing the message.

### Future-proofing notes

- **Streaming datasets** (HTTP, DB): the async iterator is the design
  hook. v0.1 ships only the sync-backed `JSONLDataset`, but
  `Dataset.__aiter__` exists so v0.2 backends slot in without breaking
  the `@Eval` surface.
- **Generators** (LLM-synthesised cases): out of scope for v0.1
  (Brief v0.2 line).
- **Manifest files** (`dataset="evals/manifest.yaml"` pointing at
  multiple JSONLs): not in v0.1. The resolver only handles single
  JSONL paths.

## Design rules

- **Pure data layer**: no observability spans, no factory integration,
  no DI. The Dataset class is constructed where it is used; lifecycle
  is the consumer's problem.
- **Deterministic ordering**: both iterators yield in file order.
  Brief v4.0 §"Datasets deterministas" requires this; AJ-4's metrics
  depend on it for `--compare-with` regression detection (AJ-27).
- **Forward-compatible JSONL shape**: extra keys on each case (like
  `tags` / `comment` / `disabled`) are TOLERATED. v0.1 ignores them;
  v0.2 can grow features without invalidating existing datasets.
- **No magic on Case fields**: `input` and `expected` stay as raw
  `Mapping[str, Any]`. AJ-4 / `@Metric` will read keys they care
  about. We do NOT enforce a schema on the inner dicts.

## Out of scope for this item

- `@Eval` decorator → AJ-4.
- `@Metric` decorator → AJ-5.
- Built-in metric library (`exact_match`, `intent_match`, etc.) →
  AJ-26 / AJ-4 implementation notes.
- `ajolopy eval` CLI → AJ-35.
- Regression detection / `--compare-with` → AJ-27.
- LLM-synthesised dataset generators → v0.2.
- Multi-file manifest loaders → v0.2.
- Schema validation of `input` / `expected` against a user-provided
  Pydantic model → v0.2 (when `@Eval` has the agent's input signature
  available).

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`.

### `Case`

- [ ] `Case(input={"x": 1}, expected={"y": 2})` constructs successfully.
- [ ] `Case` is frozen: mutating `case.input` raises (frozen dataclass
      behaviour) — verified by attempting `case.input = ...` and
      catching `dataclasses.FrozenInstanceError`.
- [ ] `Case` has `__slots__` (verified via `hasattr(Case, "__slots__")`
      and `"__dict__" not in Case.__slots__`).
- [ ] Two `Case` instances with equal fields compare equal
      (dataclass `__eq__`).

### `Dataset` ABC

- [ ] `Dataset` cannot be instantiated directly (`TypeError` due to
      abstract methods).
- [ ] A subclass implementing only `__iter__` cannot be instantiated
      (still abstract on `__aiter__`).
- [ ] A subclass implementing only `__aiter__` cannot be instantiated.
- [ ] A subclass implementing both is instantiable and iterates
      correctly via both protocols.

### `JSONLDataset` — happy paths

- [ ] Loading `tests/eval/fixtures/support.jsonl` (3 valid cases)
      produces three `Case` objects in file order via sync iteration.
- [ ] Async iteration over the same fixture yields the same three
      cases in the same order.
- [ ] `len(ds)` returns 3 for the fixture.
- [ ] `ds.path` returns an absolute `Path` matching the resolved
      file path.
- [ ] A JSONL file with extra keys per case (e.g. `tags`, `comment`)
      loads cleanly; extra keys are silently ignored.
- [ ] Blank lines and whitespace-only lines are skipped during
      validation; subsequent line numbers in error messages still
      match the editor view.
- [ ] A JSONL file with trailing newline at EOF loads cleanly (the
      final blank line is skipped, not flagged).
- [ ] Relative path strings resolve against `os.getcwd()`
      (verified by `monkeypatch.chdir(...)`).
- [ ] Absolute paths pass through verbatim.

### `JSONLDataset` — error paths

- [ ] Non-existent file → `DatasetFileError` whose message contains
      the resolved path.
- [ ] Path that is a directory → `DatasetFileError`.
- [ ] Empty file (zero bytes) or file with only blank lines →
      `DatasetSchemaError("dataset is empty")`.
- [ ] Malformed JSON on line 2 (e.g. `{not valid}`) →
      `DatasetSchemaError` whose `.line == 2` and whose message
      includes `"line 2"` and the parser error.
- [ ] Top-level array on line 1 (`["nope"]`) → `DatasetSchemaError`
      with `.line == 1` and message
      `"line 1: case must be a JSON object"`.
- [ ] Missing `input` key on line 3 → `DatasetSchemaError` with
      `.line == 3` and `"line 3: missing required key 'input'"`.
- [ ] Missing `expected` key → analogous error.
- [ ] `input` not an object (e.g. `"input": "string"`) →
      `DatasetSchemaError` with `"line N: 'input' must be a JSON object"`.
- [ ] Unreadable file (e.g. permission denied — simulated with
      `chmod 000` in a tmp_path fixture) → `DatasetFileError`.

### `resolve_dataset(spec)`

- [ ] `resolve_dataset("evals/support.jsonl")` returns a
      `JSONLDataset` whose `.path` resolves against cwd.
- [ ] `resolve_dataset(Path("evals/support.jsonl"))` works the
      same way.
- [ ] `resolve_dataset(JSONLDataset(...))` returns the input
      verbatim (`is` identity).
- [ ] `resolve_dataset(JSONLDataset)` (a class, not an instance)
      raises `DatasetError` because `JSONLDataset` itself has a
      required-arg `__init__`.
- [ ] A user-defined zero-arg `Dataset` subclass class is
      instantiated and returned.
- [ ] A user-defined subclass with required-arg `__init__` raises
      `DatasetError` with a hint to pass an instance.
- [ ] `resolve_dataset(42)` raises `DatasetError` listing accepted
      forms.

### Public re-exports

- [ ] `from ajolopy.eval import Case, Dataset, DatasetError,
      DatasetFileError, DatasetSchemaError, JSONLDataset,
      resolve_dataset` works.
- [ ] `ajolopy.eval.__all__` includes those names.
- [ ] `ajolopy/__init__.py` is **not** modified by this item — these
      are eval-internal types, not top-level primitives. AJ-4 will
      decide whether `@Eval` gets a top-level re-export.

## Implementation pointers

- Source: `src/ajolopy/eval/` (new package).
  - `__init__.py` — public re-exports of the symbols listed above.
  - `case.py` — `Case` dataclass.
  - `errors.py` — `DatasetError`, `DatasetFileError`, `DatasetSchemaError`.
  - `dataset.py` — `Dataset` ABC + `resolve_dataset` helper.
  - `jsonl.py` — `JSONLDataset` concrete implementation.
- Tests: `tests/eval/` (new).
  - `fixtures/` — small JSONL files for happy- and error-path tests.
    - `support.jsonl` — 3 valid cases (the Brief example, paraphrased).
    - `extra_keys.jsonl` — valid case with extra `tags` key.
    - `with_blanks.jsonl` — valid cases interleaved with blank lines.
    - `bad_json.jsonl` — malformed JSON on line 2.
    - `top_level_array.jsonl` — line 1 is `["nope"]`.
    - `missing_input.jsonl` — line 3 has no `input`.
    - `input_string.jsonl` — `input` is a string, not an object.
  - `test_case.py`
  - `test_dataset_abc.py`
  - `test_jsonl_dataset.py`
  - `test_resolve_dataset.py`
  - `test_public_api.py`
- Runtime deps: none new (stdlib `json`, `pathlib`, `dataclasses`, `abc`,
  `typing`).
- Dev deps: none new.

## Implementation notes

(Empty — populated by the implementation PR.)
