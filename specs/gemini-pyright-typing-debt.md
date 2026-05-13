# AJ-59 — Remove `_aio_models` Any-cast workaround in `GeminiProvider`

> Tracked in [`board.json`](../board.json) as `AJ-59`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Type: `chore` (tech-debt cleanup). Milestone: post-v0.1.

## What

Remove the `_aio_models` property workaround from
`src/ajolopy/providers/gemini/provider.py` that AJ-21 shipped to satisfy
`pyright --strict`. The property currently returns
`cast("Any", self._client.aio.models)` so the rest of the provider can
read `self._aio_models.generate_content(...)` /
`generate_content_stream(...)` / `embed_content(...)` / `count_tokens(...)`
without strict-typing failures.

When `google-genai` improves the typing on the
`client.aio.models.<method>(...)` surface so that pyright can narrow
the union (or when we can switch to a Protocol-based abstraction), this
item drops the cast and re-types every call site against the real SDK
signatures.

## Why

`google-genai` 2.2.0 (the version AJ-21 pinned) declares the `contents=`
parameter as a sprawling union:

```
ContentListUnion = (
    list[Content] | list[ContentDict] | Content | ContentDict
    | list[PartUnion] | list[PartUnionDict] | PartUnion | PartUnionDict
    | str
)
```

…where `PartUnionDict` itself decomposes into a further dozen-or-so
shapes (`PartDict`, `BlobDict`, `FileDataDict`, `FunctionCallDict`,
`FunctionResponseDict`, etc.). The framework builds a *concrete*
`list[Content]` shape — well-typed at our boundary — but pyright cannot
prove our value is assignable to the union without type-narrowing
information the SDK does not surface.

The AJ-21 spec already commits to "pyright strict must pass". Rather
than scatter `# pyright: ignore[reportArgumentType]` comments across
every SDK call, AJ-21 isolated the loss-of-typing in a single
`_aio_models` property cast to `Any` (`provider.py:184-194`). The rest
of the implementation reads cleanly and the strict checker stays
focused on framework boundaries instead of SDK internals.

This is a workaround, not a long-term design. When the upstream SDK
improves its typing or when a stable Protocol-based abstraction
emerges, the cast should disappear so callers get real type checking
all the way to the SDK boundary.

## Trigger conditions (when to claim this item)

Any one of the following:

1. `google-genai` publishes a release that narrows the `contents=`,
   `tools=`, `config=`, and tool-call return types enough that pyright
   strict resolves them without the cast. (Easiest signal: try
   removing the cast in a worktree and run `uv run pyright`.)
2. The framework introduces an internal Protocol or typed adapter
   layer over LLM providers (e.g. an extension of AJ-18's
   `LLMProvider` ABC that carries narrowed message / part types) that
   the Gemini provider can use as its boundary instead of leaning on
   the SDK's types directly.
3. A maintainer decides the cost of the cast (one source of
   "unknown" type narrowness in the codebase) exceeds the cost of
   inlining `# pyright: ignore[...]` justifications at each call site.

## Out of scope

- Replacing `google-genai` with a different Gemini SDK.
- Adding alternative type definitions for `google-genai` (a stub
  package). The cleanup expects upstream improvements, not a parallel
  type-stubs project.
- Touching any other provider (Anthropic, OpenAI, Universal OpenAI) —
  none of them have an equivalent workaround.

## Acceptance criteria

- [ ] Remove `_aio_models` property and inline call sites to read
      `self._client.aio.models.<method>(...)` directly.
- [ ] All five existing call sites in `provider.py` (the `complete`,
      `stream`, `embed`, and `count_tokens` paths) type-check under
      `pyright --strict` with NO `# pyright: ignore[...]` comments.
- [ ] The existing test suite (`tests/providers/gemini/`) stays green
      without modification — types are an internal concern; behaviour
      does not change.
- [ ] `uv run ruff check` / `ruff format --check` clean.
- [ ] The `## Implementation notes` section of `specs/gemini-provider.md`
      gets a follow-up entry noting AJ-59 closed and the cast was
      removed against `google-genai` version X.Y.Z.

## Implementation pointers

- File to edit: `src/ajolopy/providers/gemini/provider.py`.
- Remove the `_aio_models` property and the `Any` import if no longer
  needed elsewhere.
- Re-type every call site: `await self._client.aio.models.generate_content(...)`,
  `self._client.aio.models.generate_content_stream(...)`, and the
  paired `embed_content` / `count_tokens` calls.
- Pay attention to the stream call — the existing code casts the
  iterator separately (`cast("AsyncIterator[Any]", sdk_stream)`); if
  the SDK now returns a typed iterator, drop that cast too.
- Verify the dependency bump is intentional: when google-genai
  publishes a typing improvement, `uv lock --upgrade-package google-genai`
  + run the trigger check. Pin the new version in `pyproject.toml`
  before opening the PR.

## Implementation notes

<!-- Filled when this item ships. Record the google-genai version that
unblocked the cleanup, any leftover ignores, and link back to the
spec entry in gemini-provider.md. -->
