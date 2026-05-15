# Quickstart — 5 minutes to your first agent

This guide takes you from a blank shell to a streaming agent answering
`curl` requests in **five minutes**. Every command below is real — no
pseudo-code.

!!! note "Prerequisites"
    - Python **3.14+**.
    - [`uv`](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
    - An **`ANTHROPIC_API_KEY`** — grab one from
      [console.anthropic.com](https://console.anthropic.com/).

---

## 1. Install Ajolopy (30 seconds)

```bash
uv pip install ajolopy
```

This pulls the core framework only. Optional extras (observability, MCP,
memory backends) are opt-in — see [Install](install.md) for the full
matrix.

## 2. Create a project (1 minute)

```bash
ajolopy new my-agent
cd my-agent
uv sync
```

The wizard prompts four questions; the defaults
(`anthropic` / `agent` / `y` / `y`) match this guide. Pass `--yes` to
skip the prompts:

```bash
ajolopy new my-agent --yes
```

You now have a NestJS-style project layout:

```
my-agent/
  pyproject.toml
  .env.example
  src/my_agent/
    main.py            # ASGI entry point
    app_module.py      # @Module root wiring
    agents/
      support.py       # sample @Agent with @Tool + @Stream
  evals/
    support_eval.py    # sample @Eval suite
    datasets/support.jsonl
  tests/
    test_support.py
```

!!! tip "Inspect the generated agent"
    Open `src/my_agent/agents/support.py`. You will see:

    ```python
    from ajolopy import Agent, Stream, Tool


    @Agent(
        model="claude-sonnet-4-7",
        system="You are MyAgent, a helpful assistant.",
    )
    class Support:
        """The on-call assistant."""

        @Tool
        def echo(self, text: str) -> str:
            """Return the input unchanged. Replace with real logic."""
            return text

        @Stream("/chat")
        async def respond(self, message: str):
            """Stream a reply for `message` over the /chat endpoint."""
            async for chunk in self.stream(message):
                yield chunk
    ```

    That is the **default magical** form of the three core primitives
    you will use every day: `@Agent`, `@Tool`, `@Stream`.

## 3. Set your API key (30 seconds)

```bash
cp .env.example .env
```

Edit `.env` and fill in your key:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
APP_ENV=development
LOG_LEVEL=debug
```

!!! warning "Never commit `.env`"
    `.env` is in the generated `.gitignore`. Commit `.env.example`
    only — that file declares the *shape* of your config without
    secrets.

## 4. Run the dev server (1 minute)

```bash
ajolopy dev
```

You should see something like:

```
Starting Ajolopy dev server...
   App:     my_agent.main:app
   URL:     http://127.0.0.1:8000
   Watching: src/, .env
   Reload:  on

INFO:     Application startup complete.
```

`ajolopy dev` wraps `uvicorn --reload`, auto-detects the entry point
via the `src/<package>/main.py:app` convention, and watches `.env` for
changes alongside your source tree.

!!! tip "Override the entry point"
    If your app lives somewhere non-standard, pass `--app`:

    ```bash
    ajolopy dev --app my_pkg.submodule:my_asgi_app
    ```

## 5. Talk to it (2 minutes)

In a second terminal, hit the `@Stream("/chat")` endpoint that `Support`
declared:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello in one sentence."}'
```

You will see the response **stream back token by token**. The `-N`
flag disables curl's buffering so you can watch the stream as it
arrives.

That is the round trip:

1. `@Agent` registered `Support` with the DI container.
2. `@Stream("/chat")` exposed `respond()` as an ASGI route.
3. `self.stream(message)` ran the prompt against
   `claude-sonnet-4-7` and yielded chunks as the model produced them.
4. The framework serialised the async generator into a streaming HTTP
   response.

---

## What just happened

You wrote (well, scaffolded) **three primitives** and got production-grade
behaviour for free:

| Primitive | Default magical form | What it bought you |
| --- | --- | --- |
| `@Agent` | A class with a `model=` string | LLM provider wiring, DI registration, an `.stream()` helper |
| `@Tool` | A method decorated with `@Tool` | Auto-derived JSON schema, dispatch into the agent loop |
| `@Stream("/chat")` | An async generator method | ASGI route, streaming response, content-negotiation |

The same `model="claude-sonnet-4-7"` string works with `openai`,
`gemini`, and any OpenAI-compatible provider — switch by passing
`--llm` to `ajolopy new`, or by editing `model=` directly.

## Where to go next

- **[Install](install.md)** — pick the optional extras you need
  (`otel`, `mcp`, `redis`, `postgres`, `mongo`).
- **[Next steps](next-steps.md)** — tutorial arc, reference docs,
  example projects, and how to contribute.
