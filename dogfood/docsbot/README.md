# `docsbot` — Ajolopy's own docs bot

This is the first **dogfood app** for [Ajolopy](../../README.md),
tracked as [`AJ-54`](../../board.json). The bot answers questions about
the Ajolopy framework using Ajolopy's own primitives:

- `@Agent` + `@Tool` + `@Stream` from the v0.1 surface.
- An in-memory `Retriever` subclass over the framework's `docs/`
  Markdown — the documented [`AJ-62`](../../specs/rag-retriever.md)
  escape hatch.
- `@Eval` + `@Metric` with an LLM-as-judge regression suite over a
  handful of questions a real user would ask.
- A pre-generated `Dockerfile.prod` + `fly.toml`, snapshotted from
  `ajolopy deploy docker` / `ajolopy deploy fly`.

---

## Prerequisites

- Python **3.14+**.
- [`uv`](https://docs.astral.sh/uv/) installed.
- An **`ANTHROPIC_API_KEY`** — grab one from
  [console.anthropic.com](https://console.anthropic.com/).

The dogfood app is checked into the Ajolopy repository so you do not
need a published `ajolopy` release: `pyproject.toml` points the
dependency at `../..` via `[tool.uv.sources]`.

```bash
git clone https://github.com/jcocano/Ajolopy.git
cd Ajolopy/dogfood/docsbot
uv sync
cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY
```

---

## Run the bot

```bash
ajolopy dev
```

You should see:

```
Starting Ajolopy dev server...
   App:      docsbot.main:app
   URL:      http://127.0.0.1:8000
   Watching: src, .env
   Reload:   on
```

In a second terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the @Agent decorator?"}'
```

The response streams back token by token. Under the hood:

- **`@Agent`** is wired to `claude-opus-4-7` with a fallback to
  `claude-haiku-4-5`. The system prompt instructs the model to always
  call `retrieve_docs(...)` first, ground every claim in the snippets,
  and quote source paths.
- **`@Tool` `retrieve_docs`** delegates to the in-memory retriever
  loaded from `data/docs-index.jsonl` and returns a list of
  `{path, title, text}` snippets ordered by relevance.
- **`@Stream("/chat")`** mounts the method as an SSE endpoint with
  heartbeats and disconnect cancellation.

Three more questions worth trying:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I install ajolopy?"}'

curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Which LLM providers does Ajolopy support?"}'

curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I deploy to Fly.io?"}'
```

---

## Refresh the docs index

The retriever loads from `data/docs-index.jsonl` at boot. The file is a
**snapshot** of the Ajolopy `docs/` tree at the time it was built and
is checked in so the bot boots offline.

Rebuild it any time the framework's docs change:

```bash
uv run python scripts/build_index.py
```

The script walks `../../docs/**/*.md` from this project's root, chunks
each page at paragraph boundaries, and writes one JSON object per line
to `data/docs-index.jsonl`. Each record carries `id`, `path`, `title`,
and `text`.

---

## Run the eval suite

`evals/docsbot_eval.py` ships `DocsbotEval` over the rows in
`evals/docsbot.jsonl`. Two metrics:

- **`addresses_intent`** — LLM-as-judge over the agent's answer.
  Penalises generic responses, off-topic answers, refusals to use
  `retrieve_docs`, and hallucinations.
- **`cites_docs`** — deterministic per-case scorer. Passes when the
  answer mentions at least one of the expected doc paths.

Run it:

```bash
uv run ajolopy eval --ci
```

The CI form persists each run under `.ajolopy/eval-runs/` and compares
the next run against the previous baseline — that is the regression
detection from
[`docs/tutorial/step-2-evals.md`](../../docs/tutorial/step-2-evals.md).

---

## Smoke test

The dogfood app ships a single, fast, network-free `pytest`:

```bash
uv run pytest tests/
```

It only asserts the decorators land, the retriever loads the snapshot,
and the `@Stream("/chat")` metadata is in place. No provider is called.

---

## Deploy

`Dockerfile.prod`, `.dockerignore`, and `fly.toml` are pre-generated
snapshots of the framework's `ajolopy deploy` CLI. Regenerate them at
any time:

```bash
uv run ajolopy deploy docker --force --out .
uv run ajolopy deploy fly --force --out .
```

Build and run the container locally:

```bash
docker build -f Dockerfile.prod -t docsbot:latest .
docker run -p 3000:3000 --env-file .env docsbot:latest
```

Deploy to Fly.io (requires `flyctl` installed and a Fly account):

```bash
flyctl launch --copy-config --name docsbot
flyctl secrets set ANTHROPIC_API_KEY=...
flyctl deploy
```

See [`docs/reference/cli-deploy.md`](../../docs/reference/cli-deploy.md)
for the full catalogue of `ajolopy deploy` targets.

---

## Layout

```
dogfood/docsbot/
  README.md                      ← you are here
  .env.example                   ANTHROPIC_API_KEY placeholder
  pyproject.toml                 depends on local ajolopy via [tool.uv.sources]
  Dockerfile.prod                snapshot — `ajolopy deploy docker`
  .dockerignore                  snapshot — `ajolopy deploy docker`
  fly.toml                       snapshot — `ajolopy deploy fly`
  data/
    docs-index.jsonl             snapshot — `scripts/build_index.py`
  scripts/
    build_index.py               walks ../../docs/**/*.md, writes the snapshot
  src/docsbot/
    __init__.py
    main.py                      async def app() — ajolopy dev entry point
    app_module.py                root @Module — wires DocsAgent
    retriever.py                 InMemoryDocsRetriever (AJ-62 escape hatch)
    agents/
      __init__.py
      docs.py                    DocsAgent — @Agent + @Tool + @Stream
  evals/
    docsbot.jsonl                sample rows for DocsbotEval
    docsbot_eval.py              @Eval(agent=DocsAgent) + 2 @Metrics
  tests/
    conftest.py                  sets ANTHROPIC_API_KEY=test-dummy
    test_smoke.py                decorator + retriever metadata; no provider calls
```

---

## Future enhancements

- **Embedding-based retrieval.** Swap `InMemoryDocsRetriever` for
  [`QdrantRetriever`](../../docs/reference/index.md) or
  [`PgvectorRetriever`](../../docs/reference/index.md): feed the
  `build_index.py` step a real embedding model call, store vectors in
  the backend, and remove the keyword-overlap fallback. The agent code
  stays unchanged.
- **Hot re-index.** A CI job that re-runs `build_index.py` on every
  docs push and ships `data/docs-index.jsonl` as a release artifact —
  no more manual refresh.
- **Structured citations.** Stream `{"text": ..., "citations": [...]}`
  events so the docs UI can render footnotes.
- **Memory.** `@Agent(memory="redis://...")` for multi-turn
  conversations once the docs site needs them.

---

## Where to go next

- The [reference docs](https://jcocano.github.io/Ajolopy/reference/) —
  one page per primitive used in this dogfood app.
- The [3-step killer demo tutorial](https://jcocano.github.io/Ajolopy/tutorial/)
  and its runnable companion at
  [`examples/support-agent`](../../examples/support-agent/).
- The [Ajolopy repository root README](../../README.md) for
  contributing and the project's design contract.
