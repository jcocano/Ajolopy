# AJ-68 — UniversalOpenAIProvider should read ${PREFIX}_BASE_URL env vars

> Status: backlog → ready · Type: feature · Priority: p2 · Milestone: v0.1.x
> Blocks: — (none) · Blocked by: — (none).

## Goal

Let users point `UniversalOpenAIProvider` at a non-default endpoint for any
of its known prefixes (`ollama`, `groq`, `together`, `mistral`, `deepseek`,
`openrouter`) without touching framework source. Today the provider ships
per-prefix base URLs baked into `_PREFIX_DEFAULTS` and only the constructor
kwarg `base_urls={"ollama": "..."}` overrides them. That kwarg is not
surfaced through `@Agent`, so any reader trying the AJ-66 example against a
remote Ollama instance — or against LM Studio's local OpenAI-compatible
server on `http://127.0.0.1:1234/v1` — has to monkey-patch
`_PREFIX_DEFAULTS`. That is a sharp edge the framework should not make a
user file down with a runtime patch.

The fix is the obvious one: for each known prefix, look up
`f"{PREFIX.upper()}_BASE_URL"` in the environment the first time that
prefix's client is built, and use it as the base URL when present. The env
var mirrors the existing `api_key_env` convention (one env var per prefix,
read lazily on first request) so the contract stays uniform.

## Why this matters

- **Single-line opt-in for remote / non-default endpoints.** Wedge user
  ships an Ajolopy app and wants to point `ollama:*` at an internal
  workstation or at LM Studio — `OLLAMA_BASE_URL=http://...` in the
  environment is enough. No subclassing, no `base_urls=` plumbing.
- **Closes the AJ-66 documentation gap.** The AJ-66 spec explicitly
  notes the `.env.example`'s `OLLAMA_BASE_URL` is "documentation only —
  the framework does not consume it". After this change that line of
  documentation becomes a real contract instead of a polite lie.
- **Production parity with provider envs.** `api_key_env` is already
  the magical-default escape hatch for the API key; this lands the
  same hatch for the URL. Users editing `.env` to switch endpoints no
  longer need a code change.

## Design rule — magical default + escape hatch

Per the framework-wide convention, every primitive ships a magical-default
config and an escape hatch. The universal provider already had the escape
hatch (`base_urls={"...": "..."}` constructor kwarg) but no environment-
backed default. AJ-68 lands that default:

- **Magical default (config-only).** Set `${PREFIX}_BASE_URL` in the
  environment; the provider picks it up automatically on first request
  for that prefix.
- **Escape hatch.** Pass `UniversalOpenAIProvider(base_urls={"ollama":
  "..."})` (subclass / programmatic construction). The kwarg always
  wins over the env var.

## Precedence rule

For every known prefix, `_resolve_client(prefix)` picks the base URL by:

1. **Constructor kwarg** `base_urls={"<prefix>": "..."}` — current
   behaviour, kept verbatim. Wins over everything else.
2. **NEW** — env var `${PREFIX.upper()}_BASE_URL`
   (`OLLAMA_BASE_URL`, `GROQ_BASE_URL`, `TOGETHER_BASE_URL`,
   `MISTRAL_BASE_URL`, `DEEPSEEK_BASE_URL`, `OPENROUTER_BASE_URL`).
   Empty string is treated as "not set" and falls through to the
   default.
3. **Per-prefix default** baked into `_PREFIX_DEFAULTS[prefix].default_base_url`.

The env var is read **lazily**, inside `_resolve_client(prefix)`, on the
first request that targets the prefix. `UniversalOpenAIProvider()` itself
still reads zero environment variables — import and construction stay
side-effect-free. Once the client is built it is cached for the lifetime of
the provider; a later change to the env var does **not** affect the cached
client.

## Affected prefixes

Every entry currently in `_PREFIX_DEFAULTS`:

| Prefix       | Env var                | Default base URL                      |
|--------------|------------------------|---------------------------------------|
| `ollama`     | `OLLAMA_BASE_URL`      | `http://localhost:11434/v1`           |
| `groq`       | `GROQ_BASE_URL`        | `https://api.groq.com/openai/v1`      |
| `together`   | `TOGETHER_BASE_URL`    | `https://api.together.xyz/v1`         |
| `mistral`    | `MISTRAL_BASE_URL`     | `https://api.mistral.ai/v1`           |
| `deepseek`   | `DEEPSEEK_BASE_URL`    | `https://api.deepseek.com/v1`         |
| `openrouter` | `OPENROUTER_BASE_URL`  | `https://openrouter.ai/api/v1`        |

No special-casing per prefix — every prefix follows the same
`${PREFIX.upper()}_BASE_URL` template, even the keyless `ollama` prefix.

## Security note

The base-URL env var is treated as **trusted configuration**, exactly like
`api_key_env`. The provider does not validate scheme, host, or reachability
— if the operator sets `OLLAMA_BASE_URL=file:///etc/passwd`, the underlying
`openai.AsyncOpenAI` constructor will receive it verbatim. This matches
how the existing `api_key_env` values are consumed (read, forwarded, no
validation) and how `api_keys=` / `base_urls=` constructor kwargs are
handled today. Validation is the operator's responsibility; the same
applies to the `OPENAI_API_KEY`-style env vars across the framework.

## Backwards compatibility

Strictly additive. Behaviour is unchanged whenever no `${PREFIX}_BASE_URL`
env var is set:

- The constructor kwarg `base_urls={...}` keeps its current precedence
  (still wins over the new env-var lookup).
- The pre-built `clients={...}` kwarg keeps its current precedence
  (still wins over everything — the env var is never consulted for a
  pre-built prefix because the resolver returns the cached client
  before reaching the URL lookup).
- The baked-in `_PREFIX_DEFAULTS[prefix].default_base_url` is the
  ultimate fallback when neither override nor env var is set.
- Empty env var (`OLLAMA_BASE_URL=""`) falls through to the default —
  same as `_resolve_api_key` treating empty strings as "not set".

No existing API call changes shape, no existing test that does not set
the new env var changes behaviour.

## Acceptance criteria

- [ ] `src/ajolopy/providers/universal_openai/provider.py` —
      `_resolve_client(prefix)` reads `os.environ.get(f"{prefix.upper()}_BASE_URL")`
      between the constructor-kwarg check and the
      `_PREFIX_DEFAULTS[prefix].default_base_url` fallback. Empty
      string falls through to the default.
- [ ] No env var is read in `__init__` or at import time — only inside
      `_resolve_client` on first build for a prefix.
- [ ] The class docstring's "Escape hatches" section documents the new
      env-var precedence (kwarg > env var > default), naming the
      env-var template `${PREFIX.upper()}_BASE_URL` explicitly.
- [ ] `tests/providers/universal_openai/test_resolution.py` (or a new
      sibling test file) covers: (a) env var overrides default for each
      known prefix; (b) constructor `base_urls=` kwarg overrides the env
      var; (c) empty env var falls through to the default; (d) the env
      var is read lazily — patching it after `__init__` and before the
      first `_resolve_client(prefix)` call is what takes effect.
- [ ] Existing `test_ollama_builds_without_consulting_any_env_var`
      (and any other test that asserts "no env var is read for prefix
      X") is updated to: assert no env var **other than the new
      `${PREFIX.upper()}_BASE_URL`** is read, AND that
      `OLLAMA_BASE_URL` is unset in the test environment.
- [ ] `docs/reference/agent.md` mentions the new env-var contract in
      the appropriate section (model-string / multi-provider
      configuration). One short paragraph + the template name.
- [ ] `uv run ruff check src/ajolopy/providers/universal_openai
      tests/providers/universal_openai` — clean.
- [ ] `uv run ruff format --check` — clean.
- [ ] `uv run pyright src/ajolopy/providers/universal_openai` — 0
      errors.
- [ ] `uv run pytest tests/providers/universal_openai` — green.
- [ ] `uv run pytest` — no new failures across the full suite.
- [ ] `uv run --group docs mkdocs build --strict` — passes.

## Out of scope

- Adding new prefixes to `_PREFIX_DEFAULTS`. AJ-68 only overrides the
  existing prefixes' base URLs.
- Adding an env-var override for `api_keys=`. The framework already
  has `api_key_env` per prefix for that case.
- Renaming or changing the `api_key_env` convention.
- Surfacing `base_urls=` through `@Agent` directly. That is a separate
  API design question and is post-v0.1.
- Validating the base URL (scheme, host, reachability). Treated as
  trusted operator configuration, matching `api_key_env`.
- A generic `OPENAI_BASE_URL` fallback. The framework intentionally
  routes by prefix; a single global override would conflict with
  multi-prefix usage (one provider instance, several prefixes, each
  potentially pointed at a different endpoint).

## Implementation notes

- **Where the lookup goes.** `_resolve_client(prefix)` is the only
  place that needs to change. The cached-client branch (`self._clients
  .get(prefix)`) stays first so pre-built clients keep their absolute
  priority; the env-var read sits between the `base_urls=` override and
  the per-prefix default.
- **Empty-string handling.** Mirror `_resolve_api_key`'s treatment:
  `os.environ.get(name)` returns `None` when unset and `""` when set
  empty. Both fall through to the default. The check is a simple
  `if env_value:` truthy test.
- **Cache semantics.** Once a prefix's client is built, the env var is
  not re-read on subsequent requests. Mutating the environment after
  the first request is not supported and not asserted.
- **Subclasses.** `_resolve_client` remains the single subclass-overridable
  hook for "register a new prefix" use cases. Subclasses calling
  `super()._resolve_client(prefix)` automatically pick up the new env-var
  behaviour for the prefixes they delegate.
- **Why not `OPENAI_BASE_URL`.** The OpenAI Python SDK reads a global
  `OPENAI_BASE_URL` for its OpenAI client, but a single global override
  would be ambiguous in `UniversalOpenAIProvider`, where one instance
  serves multiple prefixes simultaneously. Per-prefix env vars resolve
  the ambiguity and match the existing per-prefix `api_key_env`
  contract.
- **Docs touch.** `docs/reference/agent.md` is the canonical reference
  surface — the new env-var contract lands there in the existing
  multi-provider configuration paragraph (one sentence + the template
  name). The full per-prefix table lives in this spec; the
  documentation page only needs to point readers at the contract and
  this spec.
