# AJ-67 — Example: contextual RAG agent (chunking + hybrid retrieval + citations)

> Tracked in [`board.json`](../board.json) as `AJ-67`. Sibling launch examples
> live under `AJ-63` (`@MCP` on-call), `AJ-64` (`@Agent(memory=…)` + Redis),
> `AJ-65` (Tavily web research), `AJ-66` (local Ollama via the universal
> OpenAI-compatible provider). This item is the **RAG flagship**: it raises
> the bar over the `dogfood/docsbot` baseline by adding contextual chunking,
> hybrid retrieval, and inline citations enforced by the eval suite.

## Goal

Ship `examples/contextual-rag/` — a runnable, offline-by-default Ajolopy
example that demonstrates **production-grade RAG** end-to-end and is fit
to point at when answering "can Ajolopy do RAG seriously?" against
LangChain / LlamaIndex.

The example must remain:

- **Self-contained.** No external vector DB, no live embeddings, no
  network at boot. `data/source-docs/` is checked in; `data/index.jsonl`
  is checked in and reproducible by `python scripts/build_index.py`.
- **A faithful Ajolopy app.** One `@Module`, one `@Agent`, two `@Tool`s,
  one `@Stream("/chat")`, and one `@Eval` with three `@Metric`s.
- **Honest about its trade-offs.** The retriever scores hits with a
  deterministic hash-similarity stand-in for semantic similarity. The
  README and the retriever's module docstring both document the
  upgrade path to real embeddings.

## The three quality bumps over `dogfood/docsbot`

`dogfood/docsbot` (AJ-54) ships a pure keyword-overlap retriever over
paragraph chunks. This example moves three things forward:

### 1. Contextual chunking

Chunks are split by Markdown header (H2 / H3 boundaries) — not paragraph
breaks. Every chunk record carries, *in addition to its own text*:

- `title` — the parent file's first H1, so the agent knows which
  document the chunk belongs to.
- `section` — the chunk's own section heading.
- `context_summary` — a one-line hand-authored summary of the parent
  section, supplied via a sidecar dictionary inside
  `scripts/build_index.py`. The summary is prepended to the chunk's
  text whenever the tool layer hands the chunk to the LLM, so the chunk
  reads sensibly in isolation — this is what "contextual chunking" buys
  you: the retrieval surface is the chunk, but the model sees
  *chunk + parent context*.

The summaries live in code (not in the source docs) so re-running
`build_index.py` after editing a `.md` keeps the summaries intact.

### 2. Hybrid retrieval

The retriever combines two scores per chunk and picks the top `k` by the
weighted sum:

- **Keyword score** — Jaccard overlap between the lowercase query
  tokens and the chunk's `keywords` list (pre-extracted at index time).
  This catches lexical hits ("@Stream"), where a semantic vector might
  blur the signal.
- **Semantic score** — a deterministic hash-similarity between the
  query's `embedding_hash` (computed on the fly with the same hashing
  function the indexer uses) and the chunk's pre-computed
  `embedding_hash`. The hash is a stable, normalised 16-bit fingerprint
  of the chunk's content; chunks discussing similar topics share more
  bits than chunks on different topics. It is a **deterministic
  stand-in** for a real embedding, not a competitor to one — see
  "Upgrade path" below.
- **Final score** — `0.4 * keyword + 0.6 * semantic`, with both scores
  pre-normalised to `[0, 1]`. The weights bias the example toward the
  semantic dimension, which is what makes hybrid retrieval interesting
  in the first place; the keyword component is a tie-breaker for
  jargon-heavy queries.

### 3. Citations enforced by the eval

The agent has two `@Tool`s, not one:

- `retrieve_with_context(query, top_k=4)` — calls the retriever and
  returns the top hits with their `context_summary` prepended to the
  chunk text (so the model sees *chunk + parent context* in a single
  block). Each hit also reports its `path`, `section`, and combined
  `score`.
- `format_answer_with_citations(answer, chunks)` — appends a
  `Sources:` block to the answer with `[path#section]` style links for
  every chunk in the list.

The agent's system prompt biases hard toward calling **both** tools per
turn — `retrieve_with_context` first, then `format_answer_with_citations`
to land the citation block before the model returns control.

The eval suite has three metrics, each codifying a property of a
"production-grade" RAG answer:

- `addresses_query` — LLM-as-judge, scored 0..1. Penalises generic
  answers, refusals to use the retrieve tool, and hallucinations.
- `has_citations` — deterministic (0 / 1). Passes when the answer
  contains at least one `[path#section]` reference. Forces the
  formatter tool to actually run.
- `right_section` — deterministic (0 / 1). Passes when the answer
  cites at least one of the `expected_sections` listed on the eval
  case. Forces the *correct* source to be cited, not just any source.

## Index file format

`data/index.jsonl` is one JSON object per line:

```json
{
  "path": "onboarding/dev-environment.md",
  "chunk_id": "onboarding/dev-environment.md#getting-set-up",
  "title": "Developer environment setup",
  "section": "Getting set up",
  "context_summary": "Step-by-step onboarding for a new engineer's first week.",
  "text": "On day one, install ...",
  "keywords": ["python", "uv", "pre-commit", "install", ...],
  "embedding_hash": "1100110010101111"
}
```

Fields:

| Field | Source | Used by |
|---|---|---|
| `path` | relative posix path under `data/source-docs/` | citations |
| `chunk_id` | stable `<path>#<slugified-section>` | de-dup, citations |
| `title` | first H1 of the parent file | display + context |
| `section` | this chunk's heading (H2/H3) | citations + context |
| `context_summary` | hand-authored in `build_index.py` | prepended to `text` at retrieval time |
| `text` | the chunk's body, stripped | retrieval body |
| `keywords` | top tokens by frequency, lowercased, stopword-stripped | keyword score |
| `embedding_hash` | deterministic content fingerprint (16 chars of "01") | semantic score |

## Upgrade path to real embeddings (binding maintainer note)

The deterministic hash is a v0.1 demo choice. The example is structured
so that any maintainer can plug a real backend in two steps:

1. Replace `ContextualRagRetriever` with a `QdrantRetriever` or
   `PgvectorRetriever` (both already shipped under `ajolopy.rag`).
   These backends already require an `embedding_model` and route through
   the provider layer's `provider.embed(...)` API.
2. Change `scripts/build_index.py` to call `provider.embed(chunk.text)`
   once per chunk and store the resulting vector in the backend instead
   of `embedding_hash` in a JSONL file.

The `@Tool` layer (`retrieve_with_context`,
`format_answer_with_citations`) and the agent's system prompt stay
unchanged — the tool already speaks the abstract `Retriever` interface
(`document.text`, `document.metadata["path"]`, etc.).

This is also why the example does **not** rely on
`@Agent(retriever=…)`: that kwarg lands in v0.2 (per AJ-62 spec). For
now the agent wires the retriever inside the tool method.

## Eval suite

`evals/researcher.jsonl` — 5 rows. Each row carries:

- `input` — the user's question.
- `expected.topic` — short topic label for the judge.
- `expected.expected_sections` — list of `[path#section]` strings the
  answer should cite at least one of.

`evals/researcher_eval.py` — `@Eval(agent=ResearcherAgent, …)` with
three `@Metric` methods (`addresses_query`, `has_citations`,
`right_section`), threshold `0.65`, concurrency 3.

## Tests (network-free)

`tests/test_smoke.py` covers:

- The agent class survives import and exposes `run` / `stream`.
- Both `@Tool` methods carry the `__ajolopy_tool__` marker.
- The retriever subclasses `ajolopy.rag.Retriever`.
- The retriever loads at least N chunks from `data/index.jsonl`.
- A known query returns at least one hit with a positive score.
- The `@Stream("/chat")` route is registered with `path=/chat`,
  `method=POST`.
- Round-trip: `index` then `query` returns the indexed document.

`tests/conftest.py` seeds `ANTHROPIC_API_KEY=test-dummy` before any
example module is imported.

## Acceptance criteria

- [ ] `examples/contextual-rag/` exists with the project layout
      mirrored from `examples/support-agent/`.
- [ ] `data/source-docs/` ships 6–10 short synthetic handbook files
      covering HR, onboarding, dev environment, security, deployment.
- [ ] `scripts/build_index.py` walks `data/source-docs/**/*.md`,
      header-chunks each file, enriches with `context_summary` from a
      sidecar dict, and writes `data/index.jsonl`. Idempotent.
- [ ] `data/index.jsonl` is checked in, generated by
      `scripts/build_index.py`.
- [ ] `src/contextual_rag/retriever.py` defines
      `ContextualRagRetriever`, an `ajolopy.rag.Retriever` subclass
      that loads `data/index.jsonl` at construction and scores via
      `0.4 * keyword_jaccard + 0.6 * embedding_hash_similarity`.
- [ ] `src/contextual_rag/agents/researcher.py` defines
      `ResearcherAgent` (`@Agent(model="claude-sonnet-4-7",
      fallback="claude-haiku-4-5")`) with two `@Tool` methods
      (`retrieve_with_context`, `format_answer_with_citations`) and a
      `@Stream("/chat")` endpoint.
- [ ] System prompt biases the model to call both tools per turn.
- [ ] `evals/researcher.jsonl` ships 5 rows. `researcher_eval.py`
      ships three metrics.
- [ ] `tests/test_smoke.py` runs network-free and passes the smoke
      properties above.
- [ ] `Dockerfile.prod`, `.dockerignore`, `fly.toml` are pre-generated
      and checked in.
- [ ] `README.md` walks install → `scripts/build_index.py` → run →
      curl → eval → deploy and documents the upgrade path.
- [ ] Root `pyproject.toml` adds the example to the pyright
      `executionEnvironments` and the ruff `per-file-ignores`.
- [ ] Root `README.md` and `docs/next-steps.md` list the example
      under "Examples".
- [ ] `uv run ruff check` / `uv run ruff format --check` /
      `uv run pyright` / `uv run pytest` are clean.
- [ ] `uv run python tools/board.py validate` is clean.

## Out of scope

- **No embedding API call in v0.1.** The example must boot offline; the
  `embedding_hash` is a deterministic stand-in. A real-embedding
  variant lands when AJ-62's `@Agent(retriever=…)` ships.
- **No streaming chunked retrieval.** The retriever returns a list; SSE
  only carries the LLM's answer.
- **No cross-document re-ranking** (e.g. MMR, learned rerankers). The
  weighted hybrid score is the final ranking.
- **No multi-turn memory.** Each `/chat` request is independent. The
  memory-backed assistant is its own example (AJ-64).
- **No CLI scaffolding** for "new RAG project". Generators are tracked
  separately under the CLI items.

## Implementation notes

- The retriever singleton is a module-level lazy instance keyed off the
  JSONL snapshot path, same pattern as `dogfood/docsbot/agents/docs.py`.
  The `@Stream` mount instantiates the agent with `cls()` so the agent
  class must remain zero-arg.
- The `embedding_hash` function: lowercase + tokenise → sorted set →
  SHA-256 over the joined tokens → first 16 hex chars → expanded to a
  64-bit integer → top 16 bits emitted as a `"0"`/`"1"` string. Two
  chunks share bits in proportion to how much their token sets overlap
  modulo SHA-256's avalanche effect — good enough as a stable demo
  surrogate, terrible as a real embedding (which is the point).
- The semantic score between two 16-bit hashes is
  `1 - hamming_distance / 16`, so it lands in `[0, 1]`.
- Keyword extraction at index time: tokenise the chunk's text, drop a
  small built-in stopword list, count occurrences, take the top 15 by
  frequency.
