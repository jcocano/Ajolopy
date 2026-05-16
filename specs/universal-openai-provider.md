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

Brief v4.0 §03 calls for broad OpenAI-compatible coverage. v0.1 ships
the six prefixes that share the canonical OpenAI wire format out of
the box — Ollama, Together, Groq, Mistral, DeepSeek, OpenRouter —
plus an escape hatch (`base_urls=` constructor kwarg) for any other
OpenAI-compatible endpoint. Bedrock and Azure are deferred (they need
distinct client classes — `AsyncAzureOpenAI`, a LiteLLM-style gateway)
and are scoped separately; see the deferred-items section below.
Implementing each prefix as its own provider would multiply duplicate
code five times over. A single class with a prefix table is the same shape
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

- [x] Importing `ajolopy.providers.universal_openai` registers
      `UniversalOpenAIProvider` under the key `"universal-openai"` in
      the registry.
- [x] `UniversalOpenAIProvider()` constructs successfully without
      reading any env var (verified by patching `os.environ` to empty
      and asserting construction succeeds).
- [x] `UniversalOpenAIProvider(api_keys={"groq": "gsk_..."})` stores
      the override; the env var is never read for the `groq` prefix.
- [x] `UniversalOpenAIProvider(base_urls={"ollama": "http://x:11434/v1"})`
      stores the override; the built client carries the supplied URL.
- [x] `UniversalOpenAIProvider(clients={"groq": custom})` uses the
      supplied client verbatim; no new `AsyncOpenAI` is built for
      `groq`.

### Per-prefix client resolution

- [x] First request with a `groq:` model builds one `AsyncOpenAI`
      client with `base_url="https://api.groq.com/openai/v1"` and
      `api_key=os.environ["GROQ_API_KEY"]`. Second request with a
      different `groq:` model reuses the same client (verified by
      asserting `AsyncOpenAI` was constructed exactly once).
- [x] First request with a `groq:` model when `GROQ_API_KEY` is unset
      raises `UniversalProviderConfigError` naming the env var and the
      prefix.
- [x] First request with `ollama:` builds a client without consulting
      any env var (`api_key="ollama"` baked in, `base_url` default).
- [x] The five other API-key prefixes (`together`, `mistral`,
      `deepseek`, `openrouter`) each resolve their own env var
      (parametrised test). Missing env var → typed config error.

### `complete()`

- [x] `complete(model="groq:llama-3.3-70b-versatile", messages=[…])`
      proxies to `client.chat.completions.create(model="llama-3.3-70b-versatile", ...)` —
      the prefix is stripped, the model is forwarded clean.
- [x] Messages with `role="system"` are forwarded as a leading
      `{"role": "system", ...}` entry (same as AJ-20).
- [x] `tools=[Tool(...)]` converts to OpenAI's function-calling
      schema and is forwarded; `tool_calls` come back populated.
- [x] `temperature` / `max_tokens` are forwarded as-is.
- [x] `cache=True` is a no-op (none of these providers expose an
      opt-in caching flag). Verified: SDK call kwargs are identical
      between `cache=True` and `cache=False`.
- [x] Retriable SDK errors (`openai.APIConnectionError`,
      `openai.APITimeoutError`, `openai.RateLimitError`) surface as
      `UniversalProviderError` (typed).

### `stream()`

- [x] `stream(model="together:meta-llama/Llama-3.3-70B-Instruct-Turbo", messages=[…])`
      returns an async iterator that yields `Chunk(delta=...)` with the
      prefix stripped from the model on the SDK call.
- [x] The final `Chunk` carries `finish_reason="stop"` (or mapped
      equivalent).
- [x] Cancelling the iterator mid-stream closes the underlying SDK
      stream.
- [x] Tool-call deltas (`delta.tool_calls=[{...}]`) accumulate the
      same way AJ-20 does (mirror its implementation; do not reinvent
      the assembly logic).

### `embed()`

- [x] `embed(model="ollama:nomic-embed-text", text="hi")` proxies to
      `client.embeddings.create(model="nomic-embed-text", input="hi")`
      and returns `list[list[float]]` with one inner list.
- [x] `embed(model="together:togethercomputer/m2-bert-80M-8k-retrieval", text=["a", "b"])`
      returns two vectors in input order.
- [x] `embed(model="groq:...", text="x")` raises
      `UniversalEmbeddingsNotSupportedError` because the prefix
      capability table says `embed=False` for `groq`. The error
      message points at OpenAI's `text-embedding-3-*` as the
      framework's documented fallback.
- [x] The four prefixes whose table says `embed=False` (`groq`,
      `deepseek`, `openrouter`, plus a parametrised check for
      future-proofing) all raise the same typed error.

### `count_tokens()`

- [x] `count_tokens(model="groq:llama-3.3-70b-versatile", text="hello")`
      returns a positive int. Use `tiktoken.encoding_for_model` of
      `"gpt-4o"` as the default encoding fallback (Llama / Mixtral
      tokenisers diverge but the char-based fallback is what AJ-20
      already documents). Log a warning at first use of each prefix.
- [x] Unknown prefix → typed `UniversalProviderError`.

### Capability flags

- [x] `supports_prompt_caching()` returns `False`.
- [x] `supports_tool_calling()` returns `True`.

### Negative cases

- [x] A bare model string (`"gpt-4o-mini"`, `"claude-opus-4-7"`)
      with no universal prefix raises `UniversalProviderError`
      naming the supported prefixes.
- [x] An `azure:` model raises `UniversalProviderError` referring to
      the deferred Azure-OpenAI item — the framework should be honest
      about the gap.
- [x] A finish reason the SDK emits but `FinishReason` doesn't
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

Scope decisions and surprises captured while shipping AJ-22:

- **Shared helper module `_openai_helpers`.** The wire-shape
  translation lives in `src/ajolopy/providers/_openai_helpers.py` and
  is imported by both AJ-20's `OpenAIProvider` and AJ-22's
  `UniversalOpenAIProvider`. Extracted helpers: `convert_messages`,
  `convert_tools`, `convert_response`, `convert_stream_event`,
  `map_finish_reason`, `estimate_tokens`, plus the
  `RETRIABLE_SDK_EXCEPTIONS` tuple and the `FINISH_REASON_MAP` dict.
  Provider-specific concerns (error subclasses, model-prefix
  allowlists, capability flags) stay in each provider package.
  Behaviour for AJ-20 is unchanged; its 30 tests still pass.
- **Per-prefix table is a frozen dataclass dict.** `_PrefixDefaults`
  carries `default_base_url`, `api_key_env`, and `supports_embed` per
  prefix. Built once at module load, never mutated. Adding a new
  prefix to v0.1 is a one-line addition + a routing rule in
  `ajolopy.providers.registry` — no other code changes.
- **Construction is side-effect-free.** No env vars are read in
  `__init__`; no clients are built; no I/O happens. The constructor
  stores copies of the user-supplied `api_keys` / `base_urls` /
  `clients` mappings so callers cannot mutate them after construction.
  Env-var reads happen lazily inside `_resolve_client(prefix)` on the
  first request that targets that prefix.
- **One client per prefix, cached for the lifetime of the provider.**
  The cache lives on `self._clients` and is seeded with any
  pre-supplied clients from the `clients=` kwarg. The cache never
  expires; users who need rotation pass a new `clients=` mapping at
  construction or subclass `_resolve_client`.
- **Ollama special-case carved into the table.** `api_key_env=None`
  means "this prefix needs no env var"; `_resolve_api_key` returns the
  literal string `"ollama"` (the SDK rejects empty keys but Ollama
  itself ignores the value). An explicit `api_keys["ollama"]`
  override still wins, for hosted-Ollama setups that require an
  upstream proxy key.
- **`count_tokens` uses gpt-4o's encoding as a generic default.**
  Llama, Mixtral, and DeepSeek tokenisers diverge from o200k_base,
  but tiktoken is the only offline option with pre-built wheels. The
  spec calls this out explicitly; the provider also logs a one-time
  warning per prefix on first call (gated by
  `_warned_count_tokens_prefixes`) so the noise stays bounded on hot
  paths. Falls back to the same `max(1, len(text) // 4)` estimate
  AJ-20 uses when tiktoken fails outright.
- **`azure:*` rejects with a typed error pointing at a future item.**
  The route entry stays in `_DEFAULT_ROUTES` so the resolver does not
  crash, but Azure needs `AsyncAzureOpenAI` plus deployment-vs-model
  routing — a separate item per Brief v4.0 §03. The error message
  names the gap honestly.
- **`embed()` short-circuits on empty input.** `embed(model=..., text=[])`
  returns `[]` without an SDK call, matching the AJ-20 behaviour and
  the documented contract.
- **Capability flag asymmetry vs OpenAI proper.**
  `supports_prompt_caching()` returns `False` (none of the universal
  providers expose an opt-in caching flag; whether the underlying
  model caches is opaque). `supports_tool_calling()` returns `True`
  (every modern OpenAI-compatible API supports function calling on
  the wire format; per-model caveats are the caller's concern).
- **`_raise_unknown_prefix` typed as `NoReturn`.** Pyright needs the
  explicit marker so the call sites in `embed()` and `count_tokens()`
  do not require type narrowing after the call. Trade-off: a static
  method that always raises is less ergonomic than an inline raise,
  but DRY-ing the message (especially the deferred-Azure pointer) is
  worth it.
- **Test coverage: 59 tests, parametrised heavily per prefix.** The
  layout mirrors `tests/providers/openai/` plus a dedicated
  `test_resolution.py` for the lazy-build path. Every per-prefix
  capability is parametrised so the regression cost of adding a new
  prefix is bounded. All SDK interactions are mocked via
  `unittest.mock.AsyncMock`; no network traffic happens in CI.
