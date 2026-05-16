# AJ-18 — `LLMProvider` abstract base class + provider registry

> Tracked in [`board.json`](../board.json) as `AJ-18`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §03 (multi-provider architecture).
> If this file ever conflicts with the Brief, the Brief wins.

## What

This item delivers three building blocks that the rest of the framework
(every primitive that touches an LLM) sits on top of:

1. **`LLMProvider` abstract base class** — the canonical interface every
   provider (Anthropic, OpenAI, Gemini, Universal OpenAI-compatible, future
   plugins) must implement.
2. **Provider registry** — a process-wide table that maps a *provider key*
   (e.g. `"anthropic"`, `"openai"`, `"ollama"`) to the registered
   `LLMProvider` subclass.
3. **Model-string router** — a pure function that takes a model string and
   returns the registered provider key, applying prefix rules
   (`claude-*` → `anthropic`, `ollama:*` → `universal-openai`, etc.).

This item ships **no concrete provider**. Concrete providers land separately:
- `AJ-19` — `AnthropicProvider`
- `AJ-20` — `OpenAIProvider`
- `AJ-21` — `GeminiProvider`
- `AJ-22` — `UniversalOpenAIProvider`

## Why

The Brief locks in vendor-agnostic LLM access as a non-negotiable: "Atar el
framework a un proveedor lo deja obsoleto si surge uno mejor o desaparece el
actual" (§03). The decorator API the user sees (`@Agent`, `@Workflow`,
`@Eval`) MUST consume an abstract `LLMProvider` so any concrete provider can
be swapped underneath without a single line of user code changing.

Doing this **before** any concrete provider is wired up keeps us honest: if
the ABC is too narrow it'll bend the moment we plug in the second native
provider.

## Public surface (v0.1)

```python
from collections.abc import AsyncIterator
from abc import ABC, abstractmethod

from ajolopy.providers import LLMProvider, Message, Tool, Response, Chunk
from ajolopy.providers import register_provider, resolve_provider


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response: ...

    @abstractmethod
    def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]: ...

    @abstractmethod
    async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]: ...

    @abstractmethod
    def count_tokens(self, *, model: str, text: str) -> int: ...

    @abstractmethod
    def supports_prompt_caching(self) -> bool: ...

    @abstractmethod
    def supports_tool_calling(self) -> bool: ...


# Registration & resolution

register_provider("anthropic", AnthropicProvider)  # used by AJ-19
provider: LLMProvider = resolve_provider("claude-opus-4-7")
```

### Message / Tool / Response / Chunk types

Minimal Pydantic v2 models (or plain dataclasses — TBD during implementation,
but the test surface must not depend on which is chosen):

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None

class Tool(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

class Response(BaseModel):
    text: str
    tool_calls: list[ToolCall]
    tokens_in: int
    tokens_out: int
    finish_reason: Literal["stop", "length", "tool_calls", "error"]

class Chunk(BaseModel):
    delta: str
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: Literal["stop", "length", "tool_calls", "error"] | None = None
```

### Routing rules (model string → provider key)

| Pattern | Provider key |
|---|---|
| `claude-*` | `anthropic` |
| `gpt-*`, `o1-*`, `o3-*`, `text-embedding-3*` | `openai` |
| `gemini-*` | `gemini` |
| `ollama:*` | `universal-openai` (base_url=`http://localhost:11434/v1`) |
| `groq:*` | `universal-openai` (base_url=`https://api.groq.com/openai/v1`) |
| `together:*` | `universal-openai` (base_url=`https://api.together.xyz/v1`) |
| `mistral:*` | `universal-openai` (base_url=`https://api.mistral.ai/v1`) |
| `deepseek:*` | `universal-openai` (base_url=`https://api.deepseek.com/v1`) |
| `openrouter:*` | `universal-openai` (base_url=`https://openrouter.ai/api/v1`) |
| `azure:*` | `universal-openai` (per-deployment URL — resolved by AJ-22) |

`resolve_provider(model)` returns the provider key as a string. The caller
(usually `@Agent`) then asks the registry for the registered class and
instantiates it.

## Design rules

- **Magical default**: callers only ever pass `model="<string>"`. They never
  touch the registry.
- **Escape hatch**:
  - Subclass `LLMProvider` to add a new native provider.
  - Call `register_provider(key, cls)` once at import time.
  - Add a routing rule via `register_route(pattern, key)` (covers custom
    prefixes — useful for plugin providers).

## Out of scope for this item

- Any concrete provider (each has its own board item: AJ-19/20/21/22).
- Cross-provider fallback declaration (AJ-23). This item is one layer below
  fallback — fallback orchestrates *between* `LLMProvider` instances.
- Provider-specific features such as Anthropic prompt caching options,
  OpenAI structured outputs, Gemini grounding — those live in each
  concrete-provider item.
- Pricing catalog / cost tracking (AJ-30).

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`.

### Interface

- [x] `LLMProvider` is `ABC`; instantiating it directly raises `TypeError`.
- [x] All six abstract methods exist with the documented signatures and pass
      `pyright --strict`.

### Registry

- [x] `register_provider("anthropic", FakeProvider)` stores the class.
- [x] `get_provider_class("anthropic")` returns the registered class.
- [x] `register_provider` rejects re-registration of the same key unless
      `overwrite=True` is passed (prevents silent override at import-time).
- [x] `get_provider_class("unknown")` raises a clear
      `ProviderNotRegisteredError` naming the registered keys.

### Routing

- [x] `resolve_provider("claude-opus-4-7")` returns `"anthropic"`.
- [x] `resolve_provider("gpt-4o-mini")` returns `"openai"`.
- [x] `resolve_provider("o1-preview")` returns `"openai"`.
- [x] `resolve_provider("gemini-2.5-pro")` returns `"gemini"`.
- [x] `resolve_provider("ollama:llama3.3")` returns `"universal-openai"`.
- [x] `resolve_provider("groq:llama-3.3-70b")` returns `"universal-openai"`.
- [x] `resolve_provider("openrouter:anthropic/claude-3.5-sonnet")` returns
      `"universal-openai"`.
- [x] `resolve_provider("bogus-model")` raises a clear `UnknownModelError`
      naming the supported prefix groups.
- [x] `register_route("plugin:*", "custom")` lets users add new patterns; a
      subsequent `resolve_provider("plugin:foo")` returns `"custom"`.

### Types

- [x] `Message`, `Tool`, `Response`, `Chunk`, `ToolCall`, `ToolCallDelta` are
      exported from `ajolopy.providers` and pass `pyright --strict`.
- [x] `Response.finish_reason` is a `Literal` type — invalid string assignments
      fail at type-check time.

### Negative cases

- [x] A `LLMProvider` subclass missing one of the six abstract methods fails
      to instantiate (Python's ABC enforcement).
- [x] `register_provider` rejects non-`LLMProvider` classes with a clear
      error.

## Implementation pointers

- Source: `src/ajolopy/providers/` (package).
  - `base.py` — `LLMProvider` ABC.
  - `registry.py` — `register_provider`, `get_provider_class`,
    `register_route`, `resolve_provider`, errors.
  - `types.py` — `Message`, `Tool`, `Response`, `Chunk`, etc.
  - `__init__.py` — public re-exports.
- Tests: `tests/providers/`.
- This item adds **no external runtime dependency**. (Pydantic comes later or
  is dropped in favour of dataclasses — author's call during implementation
  but the decision is in-scope.)

## Implementation notes

- `2026-05-12` — Shipped `src/ajolopy/providers/{base,registry,types}.py` with
  zero external dependencies (plain dataclasses, `fnmatch` for routing).
  Renamed the registry errors to `ProviderNotRegisteredError` /
  `UnknownModelError` to satisfy ruff `N818`. Test fixture in
  `tests/providers/conftest.py` snapshots `_PROVIDERS` / `_ROUTES` per test so
  the global registry stays isolated. Coverage of the new package: 100%.
