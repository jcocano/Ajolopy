# AJ-22 — `UniversalOpenAIProvider`

> Tracked in [`board.json`](../board.json) as `AJ-22`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §03 (multi-provider — universal
> OpenAI-compatible) plus `03 - Arquitectura multi-provider LLM`. If this file
> ever conflicts with the Brief, the Brief wins.

## What

`UniversalOpenAIProvider` is one concrete `LLMProvider` that targets every
OpenAI-compatible HTTP API the framework supports under a single class. It
is the fourth `LLMProvider` to land (after AJ-19 / AJ-20 / AJ-21) and the
one that lets the registry's universal routes — `ollama:*`, `groq:*`,
`together:*`, `mistral:*`, `deepseek:*`, `openrouter:*` — resolve to a
working implementation.

The class registers once under the `"universal-openai"` key (already wired
into `_DEFAULT_ROUTES`). One instance serves every prefix; internally it
keeps a small per-prefix table of `(base_url, api_key_env, sdk_client)`
and builds the SDK client lazily on first use of each prefix, caching it
for subsequent requests.

## Why

Brief v4.0 §03 is explicit that the framework must cover Ollama,
Together, Groq, Mistral, DeepSeek, OpenRouter, Bedrock, and Azure on day
one, but that all of them share the OpenAI-compatible wire format —
implementing each as its own provider would multiply duplicate code
five times over. A single class with a prefix table is the same shape
the doc itself sketches (`AsyncOpenAI(base_url=..., api_key=...)` per
provider). Each prefix gets its own env var resolution and its own
default `base_url`; everything else funnels through the official
`openai` SDK (`AsyncOpenAI`, already a dependency from AJ-20).

## Public surface (v0.1)

```python
from ajolopy.providers import LLMProvider, register_provider
from ajolopy.providers.universal_openai import UniversalOpenAIProvider

# Already registered at import time:
#   register_provider("universal-openai", UniversalOpenAIProvider)

# Default construction reads each prefix's env var lazily on first use.
provider = UniversalOpenAIProvider()

# Explicit per-prefix override — used by the framework bootstrap (AJ-14)
# when it forwards ConfigService values.
provider = UniversalOpenAIProvider(
    api_keys={"groq": "gsk_...", "openrouter": "sk-or-..."},
    base_urls={"ollama": "http://my-ollama.lan:11434/v1"},
)

# Escape hatch: pre-built SDK clients keyed by prefix.
import openai
provider = UniversalOpenAIProvider(
    clients={"groq": openai.AsyncOpenAI(base_url="...", api_key="...", timeout=30)},
)
```

### Constructor

```python
class UniversalOpenAIProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_keys: Mapping[str, str] | None = None,
        base_urls: Mapping[str, str] | None = None,
        clients: Mapping[str, openai.AsyncOpenAI] | None = None,
    ) -> None: ...
```

- `api_keys` — per-prefix override of the env-var-resolved API key
  (`{"groq": "gsk_..."}` skips reading `GROQ_API_KEY`).
- `base_urls` — per-prefix override of the default `base_url`
  (`{"ollama": "http://my-ollama.lan:11434/v1"}` lets a user point at a
  remote Ollama instance without an env var dance).
- `clients` — per-prefix pre-built `AsyncOpenAI`. Wins over the other
  two kwargs and over the per-prefix defaults. Used by callers that
  need bespoke transport (timeout, proxy, retries, instrumentation).

The constructor itself does **no** I/O and reads **no** env vars. Per
the framework rule, env-var reads happen lazily on first use of each
prefix, so importing this module is free even when only one prefix is
configured.

### Prefix table (v0.1)

| Prefix       | Default `base_url`                       | API-key env var       | SDK client            |
|--------------|------------------------------------------|-----------------------|-----------------------|
| `ollama`     | `http://localhost:11434/v1`              | *(none — local)*      | `AsyncOpenAI`         |
| `groq`       | `https://api.groq.com/openai/v1`         | `GROQ_API_KEY`        | `AsyncOpenAI`         |
| `together`   | `https://api.together.xyz/v1`            | `TOGETHER_API_KEY`    | `AsyncOpenAI`         |
| `mistral`    | `https://api.mistral.ai/v1`              | `MISTRAL_API_KEY`     | `AsyncOpenAI`         |
| `deepseek`   | `https://api.deepseek.com/v1`            | `DEEPSEEK_API_KEY`    | `AsyncOpenAI`         |
| `openrouter` | `https://openrouter.ai/api/v1`           | `OPENROUTER_API_KEY`  | `AsyncOpenAI`         |

`ollama` is the special case: it carries no API key (local server). The
client is built with `api_key="ollama"` (the SDK requires a non-empty
string but Ollama ignores it).

### Per-prefix capability declarations

| Prefix       | `complete` | `stream` | `embed`               | tool calling | prompt caching |
|--------------|------------|----------|-----------------------|--------------|----------------|
| `ollama`     | yes        | yes      | yes (model-dependent) | yes          | no             |
| `groq`       | yes        | yes      | no                    | yes          | no             |
| `together`   | yes        | yes      | yes                   | yes          | no             |
| `mistral`    | yes        | yes      | yes                   | yes          | no             |
| `deepseek`   | yes        | yes      | no                    | yes          | no             |
| `openrouter` | yes        | yes      | no                    | yes          | no             |

`supports_prompt_caching()` returns `False` (none of these providers
expose an opt-in caching flag; whether the underlying model caches is
opaque). `supports_tool_calling()` returns `True` (every modern
OpenAI-compatible API supports it; the test mocks the SDK so we never
actually invoke the network).

`embed()` raises `UniversalEmbeddingsNotSupportedError` when the prefix
column above says "no", so callers get a typed error pointing them at
OpenAI's `text-embedding-3-*` for fallback embeddings.

### Model string handling

The model string at the call site (`"groq:llama-3.3-70b-versatile"`) is
**not** stripped of its prefix before the call — `LLMProvider.complete`
receives the full string. The universal provider extracts the prefix
itself and strips it before forwarding to the SDK
(`model="llama-3.3-70b-versatile"`). The registry's `resolve_provider`
already returns `"universal-openai"` for these prefixes; the provider
re-parses the prefix so it can pick the right client.

## Design rules

- **Magical default**: `@Agent(model="groq:llama-3.3-70b-versatile")` works
  with zero ceremony once `GROQ_API_KEY` is set. No constructor args needed.
- **Escape hatches**:
  - Per-prefix `api_keys` / `base_urls` / `clients` kwargs on the
    constructor (most-specific wins: explicit `client` overrides
    `base_url` + `api_key` overrides env).
  - Subclass `UniversalOpenAIProvider` and override `_resolve_client(prefix)`
    to register a new prefix entirely — `register_route("vllm:*", "universal-openai")`
    + a subclass override is the documented path for "I host my own
    OpenAI-compatible endpoint".
- **No silent fallback to OpenAI**. A request whose model string does
  not start with one of the six registered prefixes raises
  `UniversalProviderError`. The router already prevents this in normal
  use; the runtime check guards against subclasses or test mocks that
  bypass the router.
- **One client per prefix, cached for the lifetime of the provider.**
  The framework currently never invalidates the cache; the client
  outlives the process. If users need rotation they pass a `clients=`
  override at construction time or subclass.

## Out of scope for this item

- **AWS Bedrock** — needs LiteLLM gateway per Brief §03; out of scope
  here.
- **Azure OpenAI** — uses `AsyncAzureOpenAI` (different client class,
  different endpoint shape, deployment-vs-model routing). The
  `azure:*` route already exists in `_DEFAULT_ROUTES` so the resolver
  doesn't crash; this provider raises `UniversalProviderError`
  pointing at a future item when an `azure:*` model is passed.
- **Per-prefix structured outputs / extended thinking** — covered by
  AJ-20's design for OpenAI proper; replicating per-prefix is out of
  scope until callers ask.
- **Pricing catalog** — `AJ-30`.
- **Cross-provider fallback declaration** — `AJ-23`.

## Acceptance criteria

Each item must have at least one passing test before the board item
can transition to `done`. All tests mock the OpenAI SDK boundary;
no real network traffic happens in CI.

### Registration & construction

- [ ] Importing `ajolopy.providers.universal_openai` registers
      `UniversalOpenAIProvider` under the key `"universal-openai"` in
      the registry.
- [ ] `UniversalOpenAIProvider()` constructs successfully without
      reading any env var (verified by patching `os.environ` to empty
      and asserting construction succeeds).
- [ ] `UniversalOpenAIProvider(api_keys={"groq": "gsk_..."})` stores
      the override; the env var is never read for the `groq` prefix.
- [ ] `UniversalOpenAIProvider(base_urls={"ollama": "http://x:11434/v1"})`
      stores the override; the built client carries the supplied URL.
- [ ] `UniversalOpenAIProvider(clients={"groq": custom})` uses the
      supplied client verbatim; no new `AsyncOpenAI` is built for
      `groq`.

### Per-prefix client resolution

- [ ] First request with a `groq:` model builds one `AsyncOpenAI`
      client with `base_url="https://api.groq.com/openai/v1"` and
      `api_key=os.environ["GROQ_API_KEY"]`. Second request with a
      different `groq:` model reuses the same client (verified by
      asserting `AsyncOpenAI` was constructed exactly once).
- [ ] First request with a `groq:` model when `GROQ_API_KEY` is unset
      raises `UniversalProviderConfigError` naming the env var and the
      prefix.
- [ ] First request with `ollama:` builds a client without consulting
      any env var (`api_key="ollama"` baked in, `base_url` default).
- [ ] The five other API-key prefixes (`together`, `mistral`,
      `deepseek`, `openrouter`) each resolve their own env var
      (parametrised test). Missing env var → typed config error.

### `complete()`

- [ ] `complete(model="groq:llama-3.3-70b-versatile", messages=[…])`
      proxies to `client.chat.completions.create(model="llama-3.3-70b-versatile", ...)` —
      the prefix is stripped, the model is forwarded clean.
- [ ] Messages with `role="system"` are forwarded as a leading
      `{"role": "system", ...}` entry (same as AJ-20).
- [ ] `tools=[Tool(...)]` converts to OpenAI's function-calling
      schema and is forwarded; `tool_calls` come back populated.
- [ ] `temperature` / `max_tokens` are forwarded as-is.
- [ ] `cache=True` is a no-op (none of these providers expose an
      opt-in caching flag). Verified: SDK call kwargs are identical
      between `cache=True` and `cache=False`.
- [ ] Retriable SDK errors (`openai.APIConnectionError`,
      `openai.APITimeoutError`, `openai.RateLimitError`) surface as
      `UniversalProviderError` (typed).

### `stream()`

- [ ] `stream(model="together:meta-llama/Llama-3.3-70B-Instruct-Turbo", messages=[…])`
      returns an async iterator that yields `Chunk(delta=...)` with the
      prefix stripped from the model on the SDK call.
- [ ] The final `Chunk` carries `finish_reason="stop"` (or mapped
      equivalent).
- [ ] Cancelling the iterator mid-stream closes the underlying SDK
      stream.
- [ ] Tool-call deltas (`delta.tool_calls=[{...}]`) accumulate the
      same way AJ-20 does (mirror its implementation; do not reinvent
      the assembly logic).

### `embed()`

- [ ] `embed(model="ollama:nomic-embed-text", text="hi")` proxies to
      `client.embeddings.create(model="nomic-embed-text", input="hi")`
      and returns `list[list[float]]` with one inner list.
- [ ] `embed(model="together:togethercomputer/m2-bert-80M-8k-retrieval", text=["a", "b"])`
      returns two vectors in input order.
- [ ] `embed(model="groq:...", text="x")` raises
      `UniversalEmbeddingsNotSupportedError` because the prefix
      capability table says `embed=False` for `groq`. The error
      message points at OpenAI's `text-embedding-3-*` as the
      framework's documented fallback.
- [ ] The four prefixes whose table says `embed=False` (`groq`,
      `deepseek`, `openrouter`, plus a parametrised check for
      future-proofing) all raise the same typed error.

### `count_tokens()`

- [ ] `count_tokens(model="groq:llama-3.3-70b-versatile", text="hello")`
      returns a positive int. Use `tiktoken.encoding_for_model` of
      `"gpt-4o"` as the default encoding fallback (Llama / Mixtral
      tokenisers diverge but the char-based fallback is what AJ-20
      already documents). Log a warning at first use of each prefix.
- [ ] Unknown prefix → typed `UniversalProviderError`.

### Capability flags

- [ ] `supports_prompt_caching()` returns `False`.
- [ ] `supports_tool_calling()` returns `True`.

### Negative cases

- [ ] A bare model string (`"gpt-4o-mini"`, `"claude-sonnet-4-7"`)
      with no universal prefix raises `UniversalProviderError`
      naming the supported prefixes.
- [ ] An `azure:` model raises `UniversalProviderError` referring to
      the deferred Azure-OpenAI item — the framework should be honest
      about the gap.
- [ ] A finish reason the SDK emits but `FinishReason` doesn't
      enumerate (`function_call`, `content_filter`) maps to `"stop"`
      with a warning, same as AJ-20.

## Implementation pointers

- Source: `src/ajolopy/providers/universal_openai/`.
  - `provider.py` — `UniversalOpenAIProvider` class.
  - `errors.py` — `UniversalProviderError`,
    `UniversalProviderConfigError`,
    `UniversalEmbeddingsNotSupportedError`.
  - `__init__.py` — public exports +
    `register_provider("universal-openai", UniversalOpenAIProvider)`
    wrapped in `contextlib.suppress(ValueError)` so repeated imports
    are no-ops (same pattern as AJ-19 and AJ-20).
- Tests: `tests/providers/universal_openai/` mirroring AJ-20's
  layout. Use `pytest.mark.parametrize` heavily for per-prefix
  coverage so each prefix's env-var + base_url path is exercised.
- Runtime deps: none new. `openai` and `tiktoken` already shipped
  with AJ-20.
- The stream tool-call accumulation logic is identical to AJ-20.
  **Extract the helpers** from `src/ajolopy/providers/openai/provider.py`
  into a shared module (`src/ajolopy/providers/_openai_helpers.py`)
  and import them from both providers. Keep the agent reviewer's
  diff small by moving lines rather than rewriting them.

## Implementation notes

_Populated as the item is implemented._
