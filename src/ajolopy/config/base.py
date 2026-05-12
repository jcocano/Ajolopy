"""``BaseConfig`` — typed environment variables with ``.env`` auto-loading.

Subclasses declare every env var their app reads. Variables without a default
are required; missing or malformed values raise ``pydantic.ValidationError``
at instantiation time so the process fails before serving traffic.
"""

import os
from typing import override

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _resolve_env_files() -> tuple[str, ...]:
    """Return dotenv files to load given the current ``APP_ENV``.

    When ``APP_ENV=test`` is set in the process env, ``.env.test`` is appended
    *after* ``.env`` so its values override the base file. For every other
    value (including unset), only ``.env`` is loaded.
    """
    if os.environ.get("APP_ENV") == "test":
        return (".env", ".env.test")
    return (".env",)


class BaseConfig(BaseSettings):
    """Base class users subclass to declare app-level environment variables.

    Variables without a default are required: instantiating the subclass
    raises ``pydantic.ValidationError`` if any required var is missing. Extra
    fields (typos in ``.env`` keys) also raise so misnamed variables surface
    at bootstrap instead of being silently dropped.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=True,
    )

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Resolve env files at construction time so a test that flips APP_ENV
        # inside the same process picks up the right layering. The default
        # source ordering (init → env → dotenv → file_secret) is preserved;
        # we replace the parent's dotenv_settings with our APP_ENV-aware copy.
        custom_dotenv = DotEnvSettingsSource(
            settings_cls,
            env_file=_resolve_env_files(),
            env_file_encoding="utf-8",
            case_sensitive=True,
        )
        return (init_settings, env_settings, custom_dotenv, file_secret_settings)
