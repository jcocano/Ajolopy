# `contextual-rag` — production-grade RAG with Ajolopy

A runnable Ajolopy example that answers questions about a synthetic
company handbook with three quality bumps over the
[`dogfood/docsbot`](../../dogfood/docsbot/) baseline:

1. **Contextual chunking** — every chunk carries the parent section's
   one-line summary so the LLM sees *chunk + parent context*, not the
   chunk in isolation.
2. **Hybrid retrieval** — the retriever scores hits with a weighted
   sum of a keyword-Jaccard score (0.4) and a deterministic
   embedding-hash similarity (0.6). Both components are pre-computed
   at index time, so the example boots offline with no live
   embeddings.
3. **Citations enforced by the eval** — the agent has a dedicated
   formatter tool that appends a `[path#section]` block to every
   answer; two of the three eval metrics fail when the citations are
   missing or point at the wrong section.

Tracked as [`AJ-67`](../../board.json). The sample corpus is a
deliberately tiny synthetic "Tlaltipac" handbook
([`data/source-docs/`](data/source-docs/)).

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- An **`ANTHROPIC_API_KEY`** — grab one from
  [console.anthropic.com](https://console.anthropic.com/).

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/examples/contextual-rag
uv sync
cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY
```

---

## Build the index

The retriever loads chunks from
[`data/index.jsonl`](data/index.jsonl), which is **checked into the
repo** so the example boots offline. Rebuild it any time the source
docs change:

```bash
uv run python scripts/build_index.py
```

The script walks [`data/source-docs/**/*.md`](data/source-docs/),
splits each file along H2 / H3 boundaries, and for every chunk emits:

- `path`, `chunk_id`, `title`, `section` — used for citations.
- `context_summary` — a hand-authored one-liner about the parent
  section, pulled from a sidecar dictionary inside the build script.
  The summary is prepended to the chunk text at retrieval time so the
  model never sees a snippet without its parent context.
- `keywords` — top 15 content tokens by frequency (stopwords removed),
  used by the keyword component of the hybrid score.
- `embedding_hash` — a deterministic 16-bit fingerprint of the
  chunk's token set, used by the semantic component.

Re-running the script is idempotent: reusing the same source docs
produces the exact same `data/index.jsonl`.

---

## Run the agent

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      contextual_rag.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What does the first day at Tlaltipac look like?"}'
```

The response streams back token by token. Under the hood:

- **`@Agent`** is wired to `claude-sonnet-4-7` with a fallback to
  `claude-haiku-4-5`. The system prompt instructs the model to call
  `retrieve_with_context` first, ground every claim in the retrieved
  chunks, and then call `format_answer_with_citations` so the answer
  lands with a `[path#section]` block.
- **`@Tool retrieve_with_context`** delegates to
  [`ContextualRagRetriever`](src/contextual_rag/retriever.py): for the
  user's query it computes the same embedding hash that the indexer
  used, takes a Jaccard score against each chunk's keyword list, and
  returns the top-`k` hits ranked by `0.4 * keyword + 0.6 * semantic`.
- **`@Tool format_answer_with_citations`** appends a `Sources:` block
  to the model's draft answer with `[path#section]` references.
- **`@Stream("/chat")`** mounts the method as an SSE endpoint.

A few more questions worth trying:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I get my local dev environment running?"}'

curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What happens if I accidentally leak a secret?"}'

curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How much vacation should I take per year?"}'
```

---

## Run the eval suite

[`evals/researcher_eval.py`](evals/researcher_eval.py) ships
`ResearcherEval` over the rows in
[`evals/researcher.jsonl`](evals/researcher.jsonl). Three metrics:

- **`addresses_query`** — LLM-as-judge over the agent's answer.
  Penalises generic answers, hallucinations, and refusals to use the
  retrieve tool.
- **`has_citations`** — deterministic. Passes when the answer contains
  at least one `[…]` citation. Forces the formatter tool to run.
- **`right_section`** — deterministic. Passes when the answer cites at
  least one of the `expected_sections` listed on the eval row. Forces
  the **correct** section to be cited, not just any section.

Run it:

```bash
uv run ajolopy eval --ci
```

The CI form persists each run under `.ajolopy/eval-runs/` and compares
the next run against the previous baseline — that is the regression
detection from the
[`step-2-evals.md`](../../docs/tutorial/step-2-evals.md) tutorial step.

---

## Smoke test

The example ships a single, fast, network-free `pytest`:

```bash
uv run pytest tests/
```

It asserts that the decorators land, the retriever loads the snapshot
(at least ten chunks), the hybrid weights sum to 1.0, the embedding
hash is deterministic, the `@Tool` markers are in place, and the
`@Stream("/chat")` metadata is registered. No provider is called.

---

## Deploy

[`Dockerfile.prod`](Dockerfile.prod), [`.dockerignore`](.dockerignore),
and [`fly.toml`](fly.toml) are pre-generated snapshots of the
framework's `ajolopy deploy` CLI. Regenerate them at any time:

```bash
uv run ajolopy deploy docker --force --out .
uv run ajolopy deploy fly --force --out .
```

Build and run the container locally:

```bash
docker build -f Dockerfile.prod -t contextual-rag:latest .
docker run -p 3000:3000 --env-file .env contextual-rag:latest
```

Deploy to Fly.io (requires `flyctl` installed and a Fly account):

```bash
flyctl launch --copy-config --name contextual-rag
flyctl secrets set ANTHROPIC_API_KEY=...
flyctl deploy
```

See [`docs/reference/cli-deploy.md`](../../docs/reference/cli-deploy.md)
for the full catalogue of `ajolopy deploy` targets.

---

## Upgrade path: real embeddings

The `embedding_hash` is a **deterministic stand-in** for a real
embedding. It lets the example boot offline and produces stable test
fixtures, but it is not a competitor to a real vector — two unrelated
chunks can collide by chance, and the hash carries no semantic
structure beyond token-set overlap modulo SHA-256.

When you want real semantics, two surgical changes are enough:

1. **Swap the retriever.** Replace `ContextualRagRetriever` with one
   of the production-grade backends shipped under `ajolopy.rag`:
   - `QdrantRetriever(url="qdrant://localhost:6333/handbook", embedding_model="text-embedding-3-small")`
   - `PgvectorRetriever(url="pgvector://...", embedding_model="text-embedding-3-small")`
   Both backends route through the provider layer's
   `provider.embed(...)` API and accept the same
   `Document` / `RetrievalHit` value types the example's tool already
   speaks. The agent code does not change.

2. **Re-embed at index time.** Update
   [`scripts/build_index.py`](scripts/build_index.py) to call
   `provider.embed(chunk.text)` once per chunk and pass the resulting
   vector to the backend's `index(...)` method instead of writing
   `embedding_hash` to JSONL.

The contextual chunking (`context_summary`, `section`) and the
citation formatter are unchanged by either swap — that is by design.

---

## Layout

```
examples/contextual-rag/
  README.md                            ← you are here
  .env.example                         ANTHROPIC_API_KEY placeholder
  pyproject.toml                       depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                      snapshot — `ajolopy deploy docker`
  .dockerignore                        snapshot — `ajolopy deploy docker`
  fly.toml                             snapshot — `ajolopy deploy fly`
  data/
    source-docs/handbook/*.md          synthetic Tlaltipac handbook (8 files)
    index.jsonl                        snapshot — `scripts/build_index.py`
  scripts/
    build_index.py                     header-chunks the source docs, writes index.jsonl
  src/contextual_rag/
    __init__.py
    main.py                            async def app() — ajolopy dev entry point
    app_module.py                      root @Module — wires ResearcherAgent
    retriever.py                       ContextualRagRetriever (hybrid scorer)
    scripts_runtime.py                 tokenise / embedding_hash shared with build_index
    agents/
      __init__.py
      researcher.py                    ResearcherAgent — @Agent + 2 @Tool + @Stream
  evals/
    researcher.jsonl                   5 rows for ResearcherEval
    researcher_eval.py                 @Eval(agent=ResearcherAgent) + 3 @Metrics
  tests/
    conftest.py                        sets ANTHROPIC_API_KEY=test-dummy
    test_smoke.py                      decorator + retriever metadata; no provider calls
```

---

## Future enhancements

- **Hot re-index.** A CI job that re-runs `scripts/build_index.py` on
  every handbook push and ships `data/index.jsonl` as a release
  artifact — no more manual refresh.
- **Cross-document MMR re-ranking.** Diversify the top-`k` so the
  agent does not see four near-duplicate chunks for closely-worded
  queries.
- **Streaming citations.** Emit `{"text": ..., "citations": [...]}`
  events so a frontend can render footnotes inline as the answer
  streams.
- **Multi-turn memory.** Pair this example with `@Agent(memory="redis://...")`
  (see the AJ-64 example) so follow-up questions inherit the previous
  turn's retrieved context.

---

## Where to go next

- The [reference docs](https://jcocano.github.io/Ajolopy/reference/) —
  one page per primitive used in this example.
- The [3-step killer demo tutorial](https://jcocano.github.io/Ajolopy/tutorial/)
  and its runnable companion at
  [`examples/support-agent`](../support-agent/).
- The first dogfood app at
  [`dogfood/docsbot`](../../dogfood/docsbot/) — the simpler
  keyword-overlap retriever this example builds on.
- The [Ajolopy repository root README](../../README.md) for
  contributing and the project's design contract.
