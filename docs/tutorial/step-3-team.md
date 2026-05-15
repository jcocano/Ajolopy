# Step 3 — Equipo: multi-agent + MCP, no rewrites

> "Scale without throwing away what already works."

The agent from [Step 1](step-1-hello.md) is great for "where is my order"
and "issue a refund". But your support team handles **billing**,
**technical**, and **general triage** — and the prompt that handles all
three at once becomes a mess very quickly.

In this step you split `Support` into three specialists, give them shared
access to your real-world tooling via the [Model Context
Protocol](https://modelcontextprotocol.io/), and let an LLM **coordinator**
route each message to the right specialist — without touching the
`@Stream` contract clients already use.

## What you build

Three small `@Agent`s (`Triage`, `Billing`, `Technical`), one `@MCP` block
that pulls in real GitHub tools via stdio, one `@Workflow` that wires the
specialists behind a coordinator model, and a workflow-level `@Eval` that
asserts routing correctness on top of the per-agent metrics from
[Step 2](step-2-evals.md).

## The specialists

Create `src/acme_support/agents/team.py`:

```python
from ajolopy import Agent, Tool


@Agent(
    model="claude-haiku-4-5",
    system=(
        "You triage incoming support messages. "
        "Classify each message into exactly one of: billing, technical, general."
    ),
)
class Triage:
    """Cheap, fast classifier that decides who answers."""


@Agent(
    model="claude-sonnet-4-7",
    system="You handle billing: refunds, invoices, subscriptions.",
)
class Billing:
    """Refunds, invoices, subscriptions."""

    @Tool
    async def issue_refund(self, order_id: str, reason: str) -> dict[str, str]:
        """Issue a refund for an order."""
        return {"order_id": order_id, "reason": reason, "status": "ok"}


@Agent(
    model="claude-sonnet-4-7",
    system="You handle technical issues: bugs, errors, integration help.",
)
class Technical:
    """Bugs, errors, integration help."""
```

Three agents, three system prompts, two models. Notice:

- `Triage` runs on the **cheap** model — classification is short, doesn't
  need Sonnet.
- `Billing` is the only one with a tool here. In a real system each
  specialist owns the tools relevant to its domain.
- None of them care about routing. That is the coordinator's job.

## The MCP integration block

Real support work needs to hit external systems: search GitHub for
related issues, look up Linear tickets, query Stripe for charge state.
Each of those exposes a Model Context Protocol server — and Ajolopy
consumes them through a single decorated declaration.

Add this to the same file:

```python
from ajolopy import MCP


@MCP(
    servers={
        "github": "stdio:npx -y @modelcontextprotocol/server-github",
    },
    auth={
        "github": {"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}},
    },
)
class Integrations:
    """External MCP servers shared across the support team."""
```

Three things worth pointing at:

- The `servers=` dict maps a **namespace key** (`github`) to a
  **transport-prefixed string**. `stdio:` spawns the named process; HTTP
  URLs connect over the HTTP transport. The [`@MCP`
  reference](../reference/mcp.md) covers every supported scheme.
- Auth uses `${ENV_VAR}` substitution at boot — you put `GITHUB_TOKEN` in
  your `.env`, the framework expands it before connecting. Missing vars
  mark the server unhealthy, they do not crash the app.
- The class body is **empty on purpose**. `@MCP` is a declaration. No
  processes are spawned until the factory boots; tools are discovered
  once and injected wherever they are referenced by `integrations=`.

!!! note "The mcp extra"
    Connecting to MCP servers requires the optional extra:
    `pip install ajolopy[mcp]`. Without it, the import still works but
    boot raises `MCPDependencyError` — see the [`@MCP` reference](../reference/mcp.md).

## The workflow

Now the orchestrator. Add this to the same file:

```python
from typing import Annotated

from pydantic import BaseModel

from ajolopy import Stream, Workflow
from ajolopy.http import Body


class ChatRequest(BaseModel):
    """Same wire shape as Step 1 — clients do not need to know about the team."""

    message: str
    user_id: str | None = None


@Workflow(
    coordinator="claude-sonnet-4-7",
    agents=[Triage, Billing, Technical],
    integrations=[Integrations],
    max_steps=8,
)
class SupportTeam:
    """Route a support request to the right specialist."""

    @Stream("/chat")
    async def handle(self, body: Annotated[ChatRequest, Body()]):
        """Stream the team's response as SSE JSON events."""
        async for event in self.stream(body.message, user_id=body.user_id):
            yield event
```

The `@Workflow` decorator does the heavy lifting:

- `coordinator=` is a model string. The framework constructs a routing
  LLM with the three agents exposed as tools and lets the model pick.
  Need deterministic routing? Override `route()` — the
  [escape hatch documented in the reference](../reference/workflow.md).
- `agents=` enumerates the specialists. Their `@Tool` methods stay scoped
  to their owning agent (Billing's `issue_refund` is not exposed to
  Triage).
- `integrations=` exposes every `Integrations` tool to **the coordinator
  and every specialist** — that is how `github__search_issues` (the
  namespaced MCP tool) becomes available to whichever agent the
  coordinator hands the conversation to.
- `max_steps=8` caps the coordinator's tool-calling loop. The default is
  `10`; we tighten it because our team only needs hand-off + answer.

## What the stream looks like now

`self.stream(...)` on a `@Workflow` yields **dicts** with a `type`
discriminator, not raw strings. The four event types you will see on a
healthy run are:

- `handoff` — the coordinator picked a specialist (carries the agent
  class name).
- `agent_result` — the specialist returned (carries the answer, plus an
  `is_error` flag for surfaced tool failures).
- `token` — token-level streaming when the host emits intermediate
  output.
- `done` — terminal event.

A curl run looks like this:

```bash
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Refund order 4392, the package was damaged.", "user_id": "u_42"}'
```

```
data: {"type": "handoff", "to": "Billing"}

data: {"type": "agent_result", "content": "Refund issued for order 4392.", "is_error": false}

data: {"type": "done"}
```

Clients **must ignore unknown `type` values** forward-compatibly — that is
called out as a non-obvious gotcha in the
[`@Workflow` reference](../reference/workflow.md).

## Score the whole team

The metrics from [Step 2](step-2-evals.md) scored a single agent. The
moment routing matters, you also want to score the **team's final
answer** — including whether it referenced the right domain. Add a
workflow-level eval:

```python
from typing import Any

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge


@Eval(
    workflow=SupportTeam,
    dataset="evals/support_team.jsonl",
    threshold=0.85,
)
class TeamEval:
    """Workflow-level regression suite."""

    @Metric
    async def addresses_intent(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge over the team's final answer."""
        return await llm_judge(
            output.text,
            criterion=(
                f"The user's request is about {expected['domain']}. "
                "The answer must address it directly with concrete next steps. "
                "Penalise generic responses, off-topic answers, and refusals."
            ),
            model="claude-sonnet-4-7",
            cache=True,
        )

    @Metric(aggregator="min", pass_threshold=1.0)
    def mentions_domain(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic check: the answer name-checks the expected domain."""
        markers = expected.get("must_contain_any", [])
        text = output.text.lower()
        return 1.0 if any(m.lower() in text for m in markers) else 0.0
```

Add a dataset at `evals/support_team.jsonl`:

```jsonl
{"input": "Refund order 4392, the package was damaged.", "expected": {"domain": "billing", "must_contain_any": ["refund", "billing", "invoice"]}}
{"input": "Our API is returning 502s when we POST to /events.", "expected": {"domain": "technical", "must_contain_any": ["502", "error", "log", "retry"]}}
{"input": "What are your support hours?", "expected": {"domain": "general", "must_contain_any": ["hours", "support", "available"]}}
```

`ajolopy eval --ci` discovers both `SupportEval` (from Step 2) and
`TeamEval` automatically — there is no extra registration step.

!!! note "Why not assert on the routed specialist directly?"
    `@Workflow.run` returns the team's **final answer string**; the
    coordinator's routing decision is observable on `wf.stream(...)`
    events but not on the eval output. The honest scope for v0.1 evals
    over a `@Workflow` is to score the answer the team produced.
    Routing-level introspection is a future enhancement tracked under
    `AJ-31` and the deeper instrumentation it will land.

## What just happened

You took the single agent from [Step 1](step-1-hello.md), kept its public
contract (`POST /chat` SSE), and **scaled it into a team** without
rewriting a single client:

- Three specialists, two models, one tool, all behind a single endpoint.
- External GitHub tooling exposed through one `@MCP` declaration —
  shared across coordinator and every specialist.
- A coordinator LLM routes each message; routing is itself measurable
  with a workflow-level metric.
- Two eval suites running on every PR — one per-agent
  ([`SupportEval`](step-2-evals.md)) and one for the team
  (`TeamEval`).

The arc from the [tutorial overview](index.md) is closed:

| Step                                          | Lines       |
| --------------------------------------------- | ----------- |
| 1. Hello to prod                              | ~12         |
| 2. Evals                                      | +12         |
| 3. Equipo                                     | +30         |
| **Total**                                     | **~55**     |

Fifty-five lines, one dependency. The same set of behaviours is roughly
**800 lines and 8 dependencies** when stitched together by hand today —
and that is before you add tracing, fallback, env validation, and
streaming.

## Where to go next

You have exercised seven of the [ten primitives](../index.md#the-10-primitives)
end to end. From here:

- **[Reference docs](../reference/index.md)** — one page per primitive,
  with every kwarg, the magical default, and the escape-hatch subclass
  pattern. Search the page for any kwarg you saw in the tutorial that
  you want to dig into.
- **Standalone example app (`AJ-50`)** — the same arc as a runnable
  repo you can fork and deploy. Live at
  [`examples/support-agent`](https://github.com/jcocano/Ajolopy/tree/main/examples/support-agent).
- **[Observability recipes](../recipes/observability/index.md)** —
  install `ajolopy[otel]` and point the standard OTel env vars at
  Langfuse / Sentry / Grafana / Honeycomb / Datadog. OTel spans flow
  whether or not you wire an exporter — without the SDK they are cheap
  no-ops.
- **[Install extras](../install.md)** — pick the optional extras
  (`otel`, `mcp`, `redis`, `postgres`, `mongo`) you need for your stack.

This tutorial is the **viral surface** of the framework. If you build
something on top of it, file an issue at
[github.com/jcocano/Ajolopy](https://github.com/jcocano/Ajolopy) — the
project is small and the maintainer reads every one.
