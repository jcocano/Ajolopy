# AJ-12 — BaseConfig + ConfigService

> Tracked in [`board.json`](../board.json) as `AJ-12`. Status, owner, branch,
> and dependencies live there — do not duplicate them in this file.
>
> Source of truth for the design: Brief v4.0 §04 (`.env` transparente).
> If this file ever conflicts with the Brief, the Brief wins.

## What

Two cooperating pieces:

1. **`BaseConfig`** — a `pydantic_settings.BaseSettings` subclass that the
   user extends to declare every environment variable the app reads.
   Required variables have no default; optional ones do. `BaseConfig`
   automatically loads `.env` (and `.env.test` when ``APP_ENV=test``) and
   validates everything at instantiation time. Bootstrap calls
   ``AppConfig()`` once at startup so missing variables fail the process
   with a clear message instead of surfacing on the first request.
2. **`ConfigService`** — an injectable wrapper around a loaded `BaseConfig`
   instance. It exposes ergonomic accessors (`get`, `get_int`, `get_bool`,
   `get_list`, `require`) and environment predicates (`is_production`,
   `is_development`, `is_test`). Application code reads config via
   `ConfigService`, never via `os.environ` directly.

## Why

The Brief locks ".env transparente" in as non-negotiable for v0.1: it maps to
production-pain #1 ("2am deploy breaks because of a missing env var"). The
guarantee is that a misconfigured environment fails fast at bootstrap with
the exact list of missing variables, not silently at first request.

This item is also a prerequisite for AJ-19 (`AnthropicProvider`) and AJ-20 /
AJ-21 (`OpenAIProvider`, `GeminiProvider`) — every concrete provider reads
its API key through `ConfigService` so application code never touches the
environment directly.

## Public surface (v0.1)

```python
from typing import Literal
from pydantic import field_validator
from ajolopy.config import BaseConfig, ConfigService


class AppConfig(BaseConfig):
    APP_NAME: str
    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    APP_PORT: int = 3000
    APP_SECRET: str

    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    DATABASE_URL: str
    REDIS_URL: str | None = None

    @field_validator("APP_SECRET")
    @classmethod
    def secret_must_be_strong_in_production(cls, value: str, info: object) -> str:
        # `info` carries the rest of the model — see Pydantic v2 docs.
        ...


config = AppConfig()                    # raises with a clear message if vars missing
service = ConfigService(config)
service.require("ANTHROPIC_API_KEY")
service.is_production()                 # True/False
service.get_int("APP_PORT")             # int
```

### `ConfigService` method surface

```python
class ConfigService:
    def __init__(self, config: BaseConfig) -> None: ...
    def get(self, key: str, default: object = None) -> object: ...
    def get_int(self, key: str, default: int | None = None) -> int: ...
    def get_bool(self, key: str, default: bool | None = None) -> bool: ...
    def get_list(
        self,
        key: str,
        separator: str = ",",
        default: list[str] | None = None,
    ) -> list[str]: ...
    def require(self, key: str) -> object: ...      # raises if missing
    def is_production(self) -> bool: ...
    def is_development(self) -> bool: ...
    def is_test(self) -> bool: ...
```

## Design rules

- **Magical default**: subclass `BaseConfig` and declare types — `.env` is
  loaded automatically, validation runs automatically, missing required
  variables crash at startup with a list of exactly what is missing.
- **Escape hatch**:
  - Override `model_config` on the subclass to point at a different env file,
    add a prefix, or change the case sensitivity.
  - Drop down to the raw `pydantic_settings` API when you need a
    multi-source config (remote secrets, AWS SSM, Vault). Those backends
    land in v0.3 (Brief §04 "Config remota").

## Environment file resolution

| `APP_ENV` value | Files read (first wins) |
|---|---|
| `test` | `.env.test` then `.env` |
| anything else (including unset) | `.env` |

`.env.example` is **not** loaded — it exists for documentation and is checked
by the future `ajolopy env:diff` command (AJ-36, out of scope here).

## Out of scope for this item

- CLI commands (`ajolopy env:show / env:validate / env:diff`) → `AJ-36`.
- DI registration of `ConfigService` into the framework container → `AJ-11`
  builds the container; this item just provides the class that DI will wire.
- Hot-reload of config → Brief §04 explicitly defers to v0.2.
- Remote config sources (Vault, SSM, KeyVault) → Brief §04 defers to v0.3.
- `field_validator` examples beyond the docstring; users write their own.

## Acceptance criteria

Each item must have at least one passing test before the board item can
transition to `done`.

### BaseConfig — required vs optional

- [ ] A `BaseConfig` subclass with a required field and no value present in
      env raises `pydantic.ValidationError` at instantiation, and the error
      message names the missing field.
- [ ] A `BaseConfig` subclass with an optional field (default value) loads
      successfully when the env var is absent, returning the declared
      default.
- [ ] A `BaseConfig` subclass loads values from a `.env` file when the
      process env var is unset.
- [ ] Process env vars take precedence over `.env` values (standard
      `pydantic_settings` precedence; pin it with a test so it cannot
      silently regress).

### Test-environment file

- [ ] When `APP_ENV=test`, values in `.env.test` override `.env` for the same
      keys.
- [ ] When `APP_ENV` is anything other than `test`, `.env.test` is ignored
      even if present.

### Custom validation hook

- [ ] A subclass with a `@field_validator` raising `ValueError` surfaces the
      validator's message in the resulting `ValidationError`.

### ConfigService method surface

- [ ] `get(key, default)` returns the value when set, the default when not.
- [ ] `get_int` / `get_bool` / `get_list` coerce string env values to the
      requested type and raise a clear error on malformed input.
- [ ] `require(key)` returns the value when set and raises a typed
      `ConfigMissingError` (subclass of `KeyError`) naming the key when not.
- [ ] `is_production` / `is_development` / `is_test` reflect `APP_ENV` only
      — adding an unrelated env var does not change their value.

### Negative cases

- [ ] Calling `BaseConfig.__init__()` with extra unknown fields raises (no
      silent dropping of misnamed env vars — surfaces typos at startup).
- [ ] `ConfigService.get_int("X")` where `X` is set to a non-numeric string
      raises with a message including both the key and the bad value.

## Implementation pointers

- Source: `src/ajolopy/config/` (package).
  - `base.py` — `BaseConfig` (subclass of `pydantic_settings.BaseSettings`).
  - `service.py` — `ConfigService` plus errors (`ConfigMissingError`).
  - `__init__.py` — public re-exports.
- Tests: `tests/config/`.
- Runtime deps to add: `pydantic` (>=2.0) and `pydantic-settings` (>=2.0).
  Justify in PR description.

## Implementation notes

Empty for now. Append entries during the work in chronological order with a
`YYYY-MM-DD` prefix.
