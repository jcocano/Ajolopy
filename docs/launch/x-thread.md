# X / Bluesky launch thread

Twelve posts. Numbered for ordering; the maintainer pastes them one at
a time and replies in chain. Each post fits inside 280 characters
(verify before posting — paste into a counter).

The thread is identical on X and Bluesky; tweak hashtags if you care
about the platform-native ones.

---

## 1 / 12 — the hook

> Ajolopy v0.1 ships today.
>
> A Python framework for AI-native production apps. Ten decorators. One
> opinion: `@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Workflow`, `@MCP`
> as primitives — not as an addon to FastAPI.
>
> Why a new framework? 👇

---

## 2 / 12 — the problem

> Building a production AI app in Python today = stitching together a
> web framework, an LLM SDK, streaming layer, function-call dispatcher,
> eval harness, prompt cache, MCP transports, OTel exporters.
>
> Each is fine alone. The integration tax is what burns out the
> Series-A AI Engineer.

---

## 3 / 12 — the killer demo, part 1

> Twelve lines:
>
> ```python
> @Agent(
>     model="claude-sonnet-4-7",
>     system="You are Acme Support.",
>     fallback="claude-haiku-4-5",
> )
> class Support:
>     @Tool
>     async def lookup_order(self, id: str) -> dict: ...
>
>     @Stream("/chat")
>     async def respond(self, body): ...
> ```

---

## 4 / 12 — what those 12 lines hide

> What's in those 12 lines, for free:
>
> • function-calling loop (no hand-rolled JSON schema)
> • SSE streaming + heartbeats + cancel-on-disconnect
> • cross-provider fallback (Sonnet → Haiku on retriable failure)
> • env-var validation at boot
> • one OTel span per call, with `gen_ai.cost_usd`
>
> Equivalent ad-hoc: ~150 lines, 4 deps.

---

## 5 / 12 — the 10 primitives

> The surface is **locked at ten**.
>
> AI (7): `@Agent`, `@Tool`, `@Stream`, `@Eval`, `@Metric`,
> `@Workflow`, `@MCP`
>
> Framework (3): `@Module`, `@Injectable`, `@Controller`
>
> Anything that needs an 11th decorator goes to v0.2+. Small surface,
> on purpose.

---

## 6 / 12 — evals block PRs

> The model upgrade that quietly breaks safety should be visible in
> CI, not in production:
>
> ```python
> @Eval(agent=Support, dataset="evals/cases.jsonl", threshold=0.85)
> class SupportEval:
>     @Metric
>     async def helpful(self, output, expected): ...
>     @Metric(aggregator="min", pass_threshold=1.0)
>     def safe(self, output, expected): ...
> ```
>
> `ajolopy eval --ci` exits non-zero on regression.

---

## 7 / 12 — multi-agent + MCP

> When one prompt stops fitting one agent:
>
> ```python
> @Workflow(
>     coordinator="claude-sonnet-4-7",
>     agents=[Triage, Billing, Technical],
>     integrations=[Integrations],
> )
> class SupportTeam: ...
> ```
>
> An LLM coordinator routes each message. Same `/chat` contract.
> Same client code.

---

## 8 / 12 — multi-provider

> Switching providers is a kwarg, not a rewrite:
>
> `model="claude-sonnet-4-7"` →
> `model="gpt-4o"` →
> `model="gemini-2.5-pro"` →
> `model="ollama:llama3.3"`
>
> Ajolopy ships native Anthropic / OpenAI / Gemini providers and a
> universal OpenAI-compatible client (Ollama / Groq / Together /
> DeepSeek / OpenRouter / Bedrock / Azure).

---

## 9 / 12 — multi-deploy

> `ajolopy deploy <target>` generates the right manifest:
>
> • `fly.toml` for Fly.io
> • `railway.json` for Railway
> • `render.yaml` for Render
> • `vercel.json` (with warnings about serverless limitations)
> • `Dockerfile.prod` for k8s / VPS / ECS / on-prem
>
> One command per platform.

---

## 10 / 12 — observability

> OpenTelemetry on by default. Every primitive emits `gen_ai.*`
> attributes including `gen_ai.cost_usd` per span.
>
> Five recipes documented, one exporter:
> Langfuse · Sentry · Grafana stack · Honeycomb · Datadog
>
> Install `ajolopy[otel]`, set the OTLP endpoint env vars, ship.

---

## 11 / 12 — dogfood

> Ajolopy's own docs bot lives in the repo at `dogfood/docsbot/` and
> answers questions about the framework — using an in-memory
> `Retriever` subclass over the project's own `docs/` tree.
>
> Eats its own dog food. Deploys in one `fly deploy`.

---

## 12 / 12 — install + links

> v0.1 is on PyPI:
>
>   pip install ajolopy
>
> 📚 docs: https://jcocano.github.io/Ajolopy
> 🚀 quickstart: 5 min
> 📖 tutorial: 55-line killer-demo arc
> 🐙 https://github.com/jcocano/Ajolopy
>
> Python 3.14+. MIT licensed. Built for the AI Engineer who's tired
> of integration tax.

---

## Notes for posting

- Schedule a 2-hour block after posting. The first replies decide the
  thread's reach; engage in real time.
- If a reply asks about LangChain / LlamaIndex / FastAPI positioning,
  quote-reply with the relevant section of [the HN talking
  points](hn-post.md#talking-points-for-replies).
- Bluesky has no 280-char limit but keep the same posts for parity —
  cross-platform analytics is easier.
