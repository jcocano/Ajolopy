# AJ-21 — `GeminiProvider`

> Tracked in [`board.json`](../board.json) as `AJ-21`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §03 (multi-provider — Gemini
> entry) plus `01 - Primitivas core - especificacion detallada` for the
> framework's view of agent surfaces. If this file ever conflicts with the
> Brief, the Brief wins.

## What

`GeminiProvider` is the third concrete subclass of `LLMProvider` (AJ-18).
It bridges the framework's vendor-agnostic wire types (`Message`, `Tool`,
`Response`, `Chunk`) to Google's Gemini API via the official `google-genai`
Python SDK.

This item delivers a minimal end-to-end Gemini client good enough to:

- Make `@Agent(model="gemini-2.5-flash")` and `@Agent(model="gemini-2.5-pro")`
  work end to end (tool use + streaming + embeddings + native token count).
- Round out the framework's three native providers (Anthropic, OpenAI,
  Gemini) so the Brief's "no vendor lock-in" claim is exercised by three
  independent SDKs, not just two.

## Why

Brief v4.0 §03 lists Google Gemini as the third of four v0.1 native
providers (the fourth being the universal OpenAI-compatible adapter, which
shipped in AJ-22). AJ-19 filled the Anthropic slot, AJ-20 the OpenAI slot;
AJ-21 finishes the native-provider triad and unblocks the cross-provider
fallback story (AJ-23) being exercisable across genuinely different SDKs.

## Public surface (v0.1)

```python
from ajolopy.providers import LLMProvider, register_provider
from ajolopy.providers.gemini import GeminiProvider

# Already registered at import time:
#   register_provider("gemini", GeminiProvider)

# Default construction reads GEMINI_API_KEY from the env.
provider = GeminiProvider()

# Explicit api_key — used by the framework bootstrap (AJ-14) when it
# forwards the value from ConfigService.
provider = GeminiProvider(api_key="...")

# Escape hatch: pre-built SDK client (custom http_options, vertexai mode,
# etc.).
from google import genai
provider = GeminiProvider(client=genai.Client(api_key="...", http_options={"timeout": 30}))
```

### Constructor

```python
class GeminiProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: "genai.Client | None" = None,
    ) -> None: ...
```

Resolution order for the underlying client:

1. If `client` is provided, use it.
2. Else if `api_key` is provided, build `genai.Client(api_key=api_key)`.
3. Else if `GEMINI_API_KEY` is set in `os.environ`, build
   `genai.Client()` (the SDK reads the env var itself; `GOOGLE_API_KEY`
   is also honoured by the SDK as a fallback).
4. Otherwise raise `GeminiConfigError("GEMINI_API_KEY missing — pass api_key=, client=, or set the env var")` at construction time.

The env-var fallback exists so the provider works standalone in scripts /
tests. The framework's bootstrap layer (AJ-14) will inject the value from
`ConfigService` (AJ-12) explicitly; application code should never read
`os.environ` directly.

## Design rules

- **Magical default**: `GeminiProvider()` + `register_provider("gemini", GeminiProvider)` is enough for an `@Agent(model="gemini-…")` to work.
- **Escape hatches**:
  - `client=` accepts a pre-built `genai.Client` for custom transport
    settings (timeout, http_options, Vertex AI mode).
  - Subclass `GeminiProvider` and override one of the public methods to
    extend behaviour (e.g. plug in grounding / search tools once that
    surface lands as a framework concept).
- **Embeddings are first-class.** `embed()` returns `list[list[float]]`
  whether the caller passes a single string or a list. Gemini's native
  embedding models (`text-embedding-004`, `gemini-embedding-001`) are
  routed by the registry; the provider just forwards the request to the
  SDK's `embed_content` endpoint.

## Out of scope for this item

- **Multimodal / vision / file inputs.** The board title labels Gemini as
  "multimodal, grounding"; that's an aspirational framing for the
  provider's surface area in later versions. In v0.1 the wire
  `Message.content` stays `str` for all providers (consistent with AJ-19
  / AJ-20). A multimodal pipeline lands post-v0.1 with a wider wire type.
- **Grounding (web / Google Search retrieval).** Same reasoning — the
  framework does not yet expose retrieval tools on the wire; revisit
  alongside multimodal.
- **Vertex AI mode.** Available via `client=genai.Client(vertexai=True, ...)`
  — the provider accepts a custom client, so callers can opt in today,
  but no first-class `vertexai=` kwarg on `GeminiProvider`.
- **Context Caching (explicit cache resource API).** Gemini's caching
  works by creating a server-side `cachedContent` resource and referencing
  it; that's a stateful lifecycle that doesn't map cleanly onto the
  `cache: bool` flag the `LLMProvider` ABC shares across vendors. AJ-21
  ships `cache=True` as a documented no-op (see open decision #1); the
  full lifecycle — with configurable defaults and an explicit opt-in
  escape hatch — is tracked separately as **AJ-58** (`specs/gemini-cache-config.md`).
- Pricing catalog → `AJ-30`.
- Cross-provider fallback declaration → `AJ-23`.

## Open design decisions (please confirm before implementation)

1. **`cache=True` is a no-op; `supports_prompt_caching()` returns `False`.**
   Unlike Anthropic (ephemeral cache control on a message) and OpenAI
   (automatic prompt caching above a token threshold), Gemini requires the
   caller to create a `cachedContent` resource ahead of time and pass its
   name to subsequent calls. Modelling that lifecycle inside a stateless
   provider would be a meaningful new surface. Defer the cache lifecycle
   to a post-v0.1 item; v0.1 ships a Gemini provider without prompt
   caching and the capability flag advertises that honestly. **Agreed?**

2. **System messages map to the SDK's `system_instruction` config field,
   not into `contents=[]`.** Gemini's API has a dedicated `system_instruction`
   slot on `GenerateContentConfig`. If multiple messages with
   `role="system"` are passed, concatenate them with `\n\n` separators —
   matches what OpenAI's provider effectively does and avoids silently
   dropping a system message. **Agreed?**

3. **Tool-call decoding mirrors OpenAI.** Gemini returns function calls as
   structured `parts` with `function_call={name, args}`. The provider
   decodes `args` (already a dict in the SDK; no JSON-string parsing
   needed) into `ToolCall.arguments`. **Agreed?**

4. **`count_tokens` uses the SDK's native endpoint (not `tiktoken`).**
   Gemini's SDK ships `client.aio.models.count_tokens(model=..., contents=...)`
   as a real online call. The provider calls it, runs it on a fresh event
   loop if no loop is active (matches AJ-19's pattern), and falls back to
   `len(text) // 4` with a warning if the SDK call fails. **Agreed?**

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`. All tests mock the `google-genai` SDK boundary; no
real network traffic happens in CI.

### Construction & registration

- [x] Importing `ajolopy.providers.gemini` registers
      `GeminiProvider` under the key `"gemini"` in the registry.
- [x] `GeminiProvider(api_key="...")` constructs successfully and
      exposes a `genai.Client` instance internally.
- [x] `GeminiProvider(client=<custom>)` uses the supplied client
      verbatim — no new `genai.Client` is built.
- [x] `GeminiProvider()` with `GEMINI_API_KEY` set in the env builds
      a client successfully (no error).
- [x] `GeminiProvider()` with `GEMINI_API_KEY` unset raises
      `GeminiConfigError` at construction time, naming the env var.

### `complete()`

- [x] A simple `complete(model="gemini-2.5-flash", messages=[…])` call
      proxies to `client.aio.models.generate_content(...)` and returns a
      `Response` with `text`, `tokens_in`, `tokens_out`,
      `finish_reason="stop"`.
- [x] Messages with `role="system"` are forwarded as the
      `system_instruction` field of `GenerateContentConfig` — not as a
      `contents[]` entry. Multiple system messages are joined with
      `\n\n`.
- [x] Non-system messages are converted to Gemini `Content` objects with
      `role="user"` / `role="model"` and a single text `Part`. Framework
      `role="assistant"` maps to Gemini `role="model"`; framework
      `role="tool"` maps to a `Part` with `function_response`.
- [x] `tools=[Tool(...)]` is converted to Gemini's `function_declarations`
      schema and forwarded; if the response includes a `function_call`
      part, the returned `Response.tool_calls` contains the
      corresponding `ToolCall`.
- [x] `temperature` / `max_tokens` are forwarded via `GenerateContentConfig`
      as `temperature` and `max_output_tokens`.
- [x] `cache=True` is accepted but produces no extra kwargs in the SDK
      call (verified by asserting the SDK call shape is identical
      between `cache=True` and `cache=False`).
- [x] A retriable SDK error (e.g. `google.api_core.exceptions.RetryError`,
      `google.genai.errors.APIError` with a 5xx status) surfaces as a
      typed `GeminiProviderError` rather than the raw SDK exception.
- [x] `complete(messages=[])` (empty list) raises `GeminiProviderError`
      with a clear "at least one user message required" hint, **before**
      the SDK is called. Gemini's API rejects empty `contents=[]` with
      a generic 400; surfacing a typed framework error is the framework
      contract.
- [x] `complete(messages=[Message(role="system", ...)])` (only system
      messages, no user/assistant turn) raises `GeminiProviderError` —
      Gemini requires at least one non-system turn in `contents=[]`.
- [x] Consecutive same-role messages (`[user, user, ...]` or
      `[assistant, assistant, ...]`) are passed through to the SDK
      verbatim. The provider does not auto-merge, auto-inject empty
      turns, or otherwise rewrite history — that's the caller's
      responsibility (and `@Agent`'s in v0.1.x). The test asserts the
      SDK call sees the consecutive turns exactly as supplied.
- [x] A framework `role="tool"` message without `tool_call_id` raises
      `GeminiProviderError` at conversion time naming the offending
      message. `function_response` parts require the call id.

### `stream()`

- [x] `stream(model="gemini-2.5-flash", messages=[…])` returns an async
      iterator that yields `Chunk(delta=…)` for each text delta.
- [x] The final `Chunk` carries `finish_reason="stop"` (or the mapped
      equivalent — `STOP` → `stop`, `MAX_TOKENS` → `length`,
      `SAFETY`/`RECITATION`/`OTHER` → `error` with a logged warning).
- [x] Cancelling the iterator mid-stream cancels the underlying SDK
      stream (no orphan HTTP connections in test).
- [x] Tool-call deltas (Gemini emits the function_call in a single chunk,
      not progressively) are surfaced as `Chunk.tool_call_delta` with
      the full payload in one delta.
- [x] A mid-stream `finish_reason` of `SAFETY` / `RECITATION` / `OTHER`
      surfaces as a final `Chunk(finish_reason="error", delta="")` and
      the iterator terminates cleanly (no exception propagated). The
      provider also logs a warning naming the underlying reason. This
      matches AJ-3's `@Stream` consumer contract that the stream
      "completes successfully" at the iterator boundary even when the
      upstream model refused.
- [x] An SDK error raised mid-stream (`google.genai.errors.APIError`,
      connection drop, etc. — not a user cancellation) surfaces as a
      `GeminiProviderError` propagated through the iterator on the
      offending step. No orphan connection remains.

### `embed()`

- [x] `embed(model="text-embedding-004", text="hello")` proxies to
      `client.aio.models.embed_content(...)` and returns
      `list[list[float]]` with one inner list (the single vector).
- [x] `embed(model="text-embedding-004", text=["a", "b"])` returns two
      vectors in input order.
- [x] Empty `text=[]` returns `[]` without calling the SDK.
- [x] `embed(model="gemini-2.5-flash", text="hello")` (a generation
      model passed to `embed`) raises `GeminiProviderError` referencing
      the offending model. The defence-in-depth `_ensure_gemini_model`
      check accepts only the `text-embedding-` / `embedding-` prefixes
      for `embed`.

### `count_tokens()`

- [x] `count_tokens(model="gemini-2.5-flash", text="hello")` returns the
      value reported by the SDK's `count_tokens` endpoint.
- [x] If the SDK call fails (transport error, unknown model), the method
      falls back to a deterministic 4-chars-per-token estimate and logs
      a warning (verified with `caplog`).
- [x] When `count_tokens` is called from inside a running event loop
      (e.g. an `async def` test calling `provider.count_tokens(...)`
      synchronously), the method falls back to the
      4-chars-per-token estimate with a logged warning rather than
      attempting `asyncio.run` (which would raise
      `RuntimeError: cannot be called from a running event loop`). This
      matches AJ-19's pattern verbatim.

### Capability flags

- [x] `supports_prompt_caching()` returns `False` (Gemini caching requires
      explicit cache-resource lifecycle, deferred to post-v0.1).
- [x] `supports_tool_calling()` returns `True`.

### Negative cases

- [x] A non-Gemini model string (`model="gpt-4o-mini"`, `model="claude-…"`)
      passed to any method raises `GeminiProviderError` with the
      offending model in the message. (The router would normally prevent
      this, but the provider double-checks so subclasses cannot silently
      route the wrong model.)

## Implementation pointers

- Source: `src/ajolopy/providers/gemini/`.
  - `provider.py` — `GeminiProvider` class.
  - `errors.py` — `GeminiProviderError`, `GeminiConfigError`.
  - `__init__.py` — public exports + `register_provider("gemini", GeminiProvider)`.
- Tests: `tests/providers/gemini/`. All SDK calls mocked via
  `unittest.mock.AsyncMock` patching `genai.Client.aio.models.generate_content`,
  `generate_content_stream`, `embed_content`, and `count_tokens`.
- Runtime dep to add via `uv add`: `google-genai` (the official Google
  Gen AI Python SDK, Apache-2.0). PR description must justify the
  addition (matches the Brief's v0.1 multi-provider non-negotiable) and
  confirm no known CVEs against the pinned version.
- Model-prefix allowlist in the defence-in-depth `_ensure_gemini_model`
  check: `gemini-`, `text-embedding-`, `embedding-`. Any new family
  (`gemini-3-*`, future embedding models) needs an explicit entry — the
  registry's `_DEFAULT_ROUTES` covers prefixes the same way.
- Naming: align with AJ-19 / AJ-20 — same constructor shape, same error
  class naming, same registration side-effect on package import.

## Implementation notes

Summary: `GeminiProvider` lands as a thin bridge over `google-genai` 2.2.0
covering complete / stream / embed / count_tokens end to end. All four
open design decisions in §"Open design decisions (please confirm before
implementation)" were adopted **as written**: (1) `cache=True` is a
documented no-op with `supports_prompt_caching() == False`; (2) system
messages route to `GenerateContentConfig.system_instruction` and multiple
system messages are joined with `\n\n`; (3) tool-call args arrive
pre-decoded as a `dict` (no JSON-string parsing); (4) `count_tokens`
calls the SDK's native online endpoint via `asyncio.run`, falling back
to a deterministic `len(text) // 4` estimate + logged warning when the
SDK fails *or* when called from inside a running event loop.

Layout matches AJ-19 / AJ-20:

- `src/ajolopy/providers/gemini/{__init__.py,provider.py,errors.py}` —
  side-effect registration of the `"gemini"` key on package import.
- `tests/providers/gemini/{conftest,test_*}.py` — every `google-genai`
  SDK call mocked through `AsyncMock`/`MagicMock`, no network in CI.

Coverage (per `pytest --cov=ajolopy.providers.gemini`):

| File | Coverage |
|---|---|
| `gemini/__init__.py` | 100% |
| `gemini/errors.py` | 100% |
| `gemini/provider.py` | 94% |

The uncovered ~6% in `provider.py` are defensive branches: the
`_finish_reason_to_str` fallthrough for objects that lack `.value` and
aren't strings (the SDK only ever emits one of those forms), the
best-effort `aclose()` failure path (only hit if the SDK's own iterator
raises during cleanup), the assistant-content-without-text-or-tool-calls
branch (the wire type makes this practically unreachable), and the
single-await branch on the stream call (we always get the iterator
directly in tests; the await branch exists for a hypothetical SDK
version that returns a coroutine-wrapped iterator).

SDK boundary surprises:

- `client.aio.models.generate_content` and friends carry a sprawling
  `ContentListUnion` / `PartUnionDict` union for `contents` that pyright
  cannot resolve narrowly. Centralised the workaround as a private
  `_aio_models` property that returns the underlying object cast to
  `Any`; the rest of the provider reads `self._aio_models.<method>(...)`
  cleanly and the strict checker stays focused on framework boundaries.
- `google.genai.errors.APIError.__init__` requires `(code, response_json)`
  rather than a single message string. The test helpers construct it
  with `code=503, response_json={"error": {"message": "..."}}`.
- `Part` and `FunctionResponse` are Pydantic models with `extra='forbid'`
  semantics — every part is built explicitly with the keyword the SDK
  expects (`function_response=...`, never `functionResponse=...`).
- Gemini's `function_response.response` must be a `dict`; the framework's
  `Message.content` carries the tool-result body as a `str`. Wrapped it
  under a stable `{"content": <str>}` key (plus an `is_error: True` flag
  when the framework signalled an error) so the model can read it back
  uniformly.
- Conversion helpers live inline in `provider.py` rather than alongside
  AJ-22's `_openai_helpers` because Gemini's `Content`/`Part`/
  `FunctionCall` tree is too different from the OpenAI chat-completions
  shape to share without ugly adapters.
- Empty / system-only message lists raise `GeminiProviderError`
  *before* any SDK call so callers see a typed framework error instead
  of a generic 400 from the API.
- The `count_tokens` fallback also triggers when the SDK returns a
  response object without a usable integer `total_tokens` (covered by
  `test_count_tokens_falls_back_when_sdk_returns_no_total_tokens`); the
  spec's "transport error, unknown model" wording covers it implicitly,
  but it's worth flagging.
