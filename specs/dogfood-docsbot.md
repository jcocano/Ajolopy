# AJ-54 — Dogfood app #1: Ajolopy docs bot (in-memory RAG)

> Status: backlog → ready · Type: story · Priority: p1 · Milestone: v0.1
> Blocks: AJ-57 (public v0.1 launch).
> Blocked by: AJ-1, AJ-2, AJ-3, AJ-19, AJ-24, AJ-28, AJ-33 — all `done`.

## Goal

Ship the **first runnable dogfood app** referenced in
[`Brief v4.0` §12](https://github.com/jcocano/Ajolopy/blob/main/board.json):
a chat bot that answers questions about Ajolopy itself, built on the
framework's own primitives. The bot exercises the full v0.1 happy path
(`@Agent` + `@Tool` + `@Stream` + `@Module` + DI + OTel + `@Eval`) end
to end, against the framework's own `docs/` corpus.

After this lands, a reader can:

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/dogfood/docsbot
uv sync
cp .env.example .env  # paste ANTHROPIC_API_KEY
ajolopy dev
```

…and `POST /chat` with a question like
*"How do I install ajolopy?"* and get a streamed, doc-grounded answer.

AJ-54 is the last hard blocker for [`AJ-57`](../board.json) (public v0.1
launch). Only [`AJ-56`](../board.json) (PyPI publish) sits between v0.1
and shipping after this lands.

## Why this matters

- Eats the framework's own dog food on a real corpus.
- Marketing-grade demo from day 1: the bot lives in the docs site.
- Surfaces the basics of the v0.1 stack (streaming SSE, retries, tool
  errors, doc grounding) before the bigger App #2 (code-review agent,
  AJ-55) layers on `@Workflow` + `@MCP`.
- Validates the AJ-62 retriever `Retriever` ABC under the **escape-hatch
  pattern** — a subclass overrides `query` / `index` with a pure-Python
  keyword-overlap implementation, so the demo runs offline.

## Structure

The app lives under `dogfood/docsbot/` at the repository root, alongside
(not inside) `examples/`. The split is deliberate:

- `examples/support-agent/` — the tutorial companion (AJ-50). Tracks the
  three-step killer demo verbatim.
- `dogfood/docsbot/` — a self-contained Ajolopy product. Same conventions
  (`[tool.uv.sources]` mounting the local framework, src layout, smoke
  tests, eval suite) but with its own purpose.

```
dogfood/docsbot/
  README.md                          install / env / run / eval / deploy
  .env.example                       ANTHROPIC_API_KEY placeholder
  pyproject.toml                     depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                    snapshot — `uv run ajolopy deploy docker`
  .dockerignore                      snapshot — `uv run ajolopy deploy docker`
  fly.toml                           snapshot — `uv run ajolopy deploy fly`
  data/
    docs-index.jsonl                 snapshot — `scripts/build_index.py` against the current docs/
  scripts/
    build_index.py                   walks ../../docs/**/*.md, chunks, writes data/docs-index.jsonl
  src/docsbot/
    __init__.py                      provider side-effect import
    main.py                          async def app() — `ajolopy dev` entry point
    app_module.py                    root @Module wiring DocsAgent
    retriever.py                     in-memory Retriever subclass (escape hatch)
    agents/
      __init__.py
      docs.py                        DocsAgent — @Agent + @Tool + @Stream
  evals/
    docsbot.jsonl                    3-5 sample rows
    docsbot_eval.py                  @Eval(agent=DocsAgent) + 2 @Metrics
  tests/
    conftest.py                      sets ANTHROPIC_API_KEY=test-dummy before collection
    test_smoke.py                    decorator + retriever metadata; no provider calls
```

## Indexed sources

The bot answers questions about the framework. The corpus is the
project's own `docs/` tree at build time:

- `docs/index.md`, `docs/install.md`, `docs/quickstart.md`,
  `docs/next-steps.md`
- `docs/tutorial/*.md`
- `docs/reference/*.md`
- `docs/recipes/observability/*.md`

`scripts/build_index.py` walks `../../docs/**/*.md` from the docsbot
project root, splits each page into paragraph-level chunks (separated
by blank lines), and writes one JSON object per line to
`data/docs-index.jsonl`. Each row has the shape:

```json
{
  "id": "reference/agent.md#3",
  "path": "reference/agent.md",
  "title": "@Agent",
  "text": "…paragraph contents…"
}
```

The script is deterministic and reproducible — the README documents how
to refresh `data/docs-index.jsonl` after docs change.

## The in-memory retriever (escape hatch over AJ-62)

`src/docsbot/retriever.py` ships an
`InMemoryDocsRetriever(Retriever)` subclass. It is the documented
**escape hatch** of the AJ-62 design:

- `index(documents)` stores the full `Document` list in a Python list.
- `query(text, k=5)` scores every document by **lowercase-tokenised
  bag-of-words overlap** with the query (Jaccard-style:
  `|q ∩ d| / max(1, |q|)`), then returns the top `k` `RetrievalHit`s
  ordered by score desc.
- `clear()` empties the internal list.

Pure Python, zero dependencies, deterministic. Loads from the
JSONL snapshot at boot via a `from_jsonl(path)` classmethod, so the
demo never embeds anything and never calls a vector DB.

Trade-off: the keyword score is enough to answer questions whose
wording overlaps with the docs (the v0.1 demo target), but it cannot
answer paraphrased questions where no token overlaps. The README's
"Future enhancements" section points at the post-v0.1 upgrade path
(swap to `QdrantRetriever` or `PgvectorRetriever`, generate
embeddings at index time).

## The agent

`src/docsbot/agents/docs.py` decorates `DocsAgent`:

```python
@Agent(
    model="claude-sonnet-4-7",
    system=(
        "You are the Ajolopy docs assistant. "
        "Always call retrieve_docs(...) before answering. "
        "Quote from the docs verbatim where it helps. "
        "If the docs do not cover a question, say so plainly."
    ),
    fallback="claude-haiku-4-5",
)
class DocsAgent:
    @Tool
    async def retrieve_docs(self, query: str) -> list[dict[str, str]]: ...

    @Stream("/chat")
    async def respond(self, body: Annotated[ChatRequest, Body()]) -> AsyncGenerator[str]: ...
```

The `@Tool` body delegates to the singleton `InMemoryDocsRetriever`
(injected via the module), passes the user's query, and returns the top
`k` hits as a list of `{path, title, text}` dicts. The agent's
function-calling loop folds the retrieved snippets into the streamed
answer.

The `@Stream` body matches the tutorial pattern: `Annotated[ChatRequest,
Body()]` with `ChatRequest(BaseModel)` carrying a `message: str` field.

## The eval suite

`evals/docsbot_eval.py` wires `@Eval(agent=DocsAgent,
dataset="evals/docsbot.jsonl", threshold=0.6)` with two metrics:

- **`addresses_intent`** — LLM-as-judge via
  `ajolopy.eval.metrics.llm_judge(output.text, criterion="...",
  model="claude-sonnet-4-7", cache=True)`. The criterion encodes
  "answer is grounded in Ajolopy docs and addresses the question".
- **`cites_docs`** — deterministic. Checks the answer text mentions one
  of the expected doc paths from the dataset row's `expected.paths`
  list. Per-case binary (0.0 / 1.0); the suite aggregates via `mean`.

The dataset (`evals/docsbot.jsonl`) ships with 3-5 representative
questions — at minimum: *"What is `@Agent`?"*, *"How do I install
ajolopy?"*, *"Which providers does Ajolopy support?"*.

## Deploy story

The Dockerfile + Fly manifest are pre-generated **snapshots**:

```bash
cd dogfood/docsbot
uv run ajolopy deploy docker --force --out .
uv run ajolopy deploy fly --force --out .
```

Both files are checked in so a reader can `docker build` or
`fly deploy` without first running the deploy CLI. The README explains
they are a snapshot and can be regenerated.

## Tests

`tests/test_smoke.py` exercises the decoration-time contract:

- `DocsAgent` carries `_agent_runtime`; `run` / `stream` are callable.
- `DocsAgent.retrieve_docs` carries the `__ajolopy_tool__` marker.
- `InMemoryDocsRetriever` is a `Retriever` subclass.
- `InMemoryDocsRetriever.from_jsonl(...)` loads `>= 1` documents from
  the checked-in snapshot.
- A `query("agent")` returns at least one hit when the snapshot is
  populated.
- The `@Stream("/chat")` route is registered on the class.

No provider calls. `conftest.py` sets `ANTHROPIC_API_KEY=test-dummy`
before any module is imported (same pattern as `examples/support-agent`).

## Acceptance criteria

- [ ] `dogfood/docsbot/` exists with the structure documented above.
- [ ] `dogfood/docsbot/pyproject.toml` uses
      `[tool.uv.sources] ajolopy = { path = "../..", editable = true }`
      so the dogfood app never depends on a published PyPI release.
- [ ] `src/docsbot/__init__.py` imports `ajolopy.providers.anthropic`
      for its registration side-effect.
- [ ] `src/docsbot/main.py` exposes `async def app() -> object` that
      returns `await AjolopyFactory.create(AppModule)`.
- [ ] `src/docsbot/app_module.py` declares an `AppModule` `@Module`
      that lists `DocsAgent` under `agents=[...]`.
- [ ] `src/docsbot/retriever.py` declares
      `InMemoryDocsRetriever(Retriever)` with `index` / `query` /
      `clear` implementations and a `from_jsonl(path)` classmethod.
- [ ] `src/docsbot/agents/docs.py` declares `DocsAgent` as
      `@Agent(model="claude-sonnet-4-7", system=..., fallback="claude-haiku-4-5")`
      with one `@Tool` (`retrieve_docs`) and one `@Stream("/chat")`
      handler whose body is `Annotated[ChatRequest, Body()]`.
- [ ] `scripts/build_index.py` walks `../../docs/**/*.md`, chunks each
      page at paragraph boundaries, and writes
      `data/docs-index.jsonl`.
- [ ] `data/docs-index.jsonl` is checked in; the README explains how to
      refresh it.
- [ ] `evals/docsbot.jsonl` ships with 3-5 representative cases that
      match the dataset shape the metrics consume.
- [ ] `evals/docsbot_eval.py` wires `@Eval(agent=DocsAgent,
      dataset="evals/docsbot.jsonl", threshold=0.6)` with two
      `@Metric` methods: an LLM-judge `addresses_intent` and a
      deterministic `cites_docs`.
- [ ] `tests/conftest.py` sets `ANTHROPIC_API_KEY=test-dummy` before
      any `docsbot.*` module is imported.
- [ ] `tests/test_smoke.py` asserts the decoration-time + retriever
      contract listed under "Tests" above. No provider calls.
- [ ] `Dockerfile.prod`, `.dockerignore`, and `fly.toml` are checked in
      as snapshots of `ajolopy deploy docker` / `ajolopy deploy fly`.
- [ ] `README.md` walks the reader through install / set env / run /
      eval / deploy. Voice matches `examples/support-agent/README.md`.
- [ ] Repository root `README.md` lists the dogfood app alongside the
      support-agent example under "Examples".
- [ ] `docs/next-steps.md` mentions the dogfood docs bot under
      "Read real projects".
- [ ] Root `pyproject.toml` extends `[tool.pyright]
      executionEnvironments` to cover `dogfood/docsbot/` (and its
      `tests/`) and `[tool.ruff.lint.per-file-ignores]` to relax
      `dogfood/**/tests/**` the same way `examples/**/tests/**` is.
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run
      pyright`, and `uv run pytest` are green at the repo root.
- [ ] `cd dogfood/docsbot && uv sync && uv run pytest` is green.
- [ ] `uv run --group docs mkdocs build --strict` is green.

## Out of scope (v0.1)

- Real production hosting — we ship the Fly + Docker manifests, not a
  deployed instance.
- Hot-reload of the docs index when docs change — manual re-index via
  `scripts/build_index.py` is enough for v0.1.
- Per-user chat memory — single-tenant, ephemeral.
- Citation rendering on the wire — v0.1 returns plain text; structured
  citations land in v0.2.
- Embedding-based retrieval — the keyword-overlap fallback covers the
  demo. The Qdrant / pgvector upgrade path is documented in the README.
- Authentication on `/chat` — public endpoint; `@UseGuards` can layer
  on later.

## Future enhancements (post-v0.1)

- Swap `InMemoryDocsRetriever` for `QdrantRetriever` or
  `PgvectorRetriever`: feed `scripts/build_index.py` an embedding model
  call, store vectors in the backend, and remove the keyword fallback.
- Hot re-index: a CI job re-builds `data/docs-index.jsonl` on every
  docs push and ships it as a release artifact.
- Structured citations: return `{"text": ..., "citations": [...]}`
  events on the stream so the docs UI can render footnotes.
- Memory: `@Agent(memory="redis://...")` for multi-turn conversations.

## NOTES

None — straight-line implementation against the existing v0.1 surface.
