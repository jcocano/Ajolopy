"""``ConfigService`` — ergonomic accessor wrapper around a loaded ``BaseConfig``.

Application and framework code reads config exclusively through
``ConfigService`` so ``os.environ`` is never touched outside of ``BaseConfig``
itself. Concrete providers (AJ-19/20/21/22) consume this when they need their
API keys.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseConfig


class ConfigMissingError(KeyError):
    """A required config key was missing when accessed via ``require()``."""


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "n", "f"})


class ConfigService:
    """Wrapper around a ``BaseConfig`` instance with typed accessor helpers."""

    def __init__(self, config: BaseConfig) -> None:
        self._config = config

    def get(self, key: str, default: object = None) -> object:
        """Return the value for ``key`` or ``default`` if absent / ``None``."""
        value = getattr(self._config, key, None)
        if value is None:
            return default
        return value

    def require(self, key: str) -> object:
        """Return the value for ``key`` or raise ``ConfigMissingError``."""
        sentinel = object()
        value = getattr(self._config, key, sentinel)
        if value is sentinel or value is None:
            raise ConfigMissingError(f"Required config key {key!r} is missing or None.")
        return value

    def get_int(self, key: str, default: int | None = None) -> int:
        """Return the value for ``key`` coerced to int.

        Raises ``ConfigMissingError`` if absent and ``default`` is ``None``.
        Raises ``ValueError`` (with key + bad value) if the value cannot be
        coerced to int.
        """
        value = getattr(self._config, key, None)
        if value is None:
            if default is None:
                raise ConfigMissingError(
                    f"int config key {key!r} is missing and no default was given."
                )
            return default
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Config key {key!r}={value!r} cannot be coerced to int.") from exc

    def get_bool(self, key: str, default: bool | None = None) -> bool:
        """Return the value for ``key`` coerced to bool.

        Accepts the case-insensitive truthy/falsy strings used by every other
        config tool (``1/true/yes/on/y/t`` vs ``0/false/no/off/n/f``). Empty
        string is treated as missing so optional flags without a value behave
        the same as if they were not set at all.
        """
        value = getattr(self._config, key, None)
        if value is None or value == "":
            if default is None:
                raise ConfigMissingError(
                    f"bool config key {key!r} is missing and no default was given."
                )
            return default
        if isinstance(value, bool):
            return value
        normalised = str(value).strip().lower()
        if normalised in _TRUE_VALUES:
            return True
        if normalised in _FALSE_VALUES:
            return False
        raise ValueError(
            f"Config key {key!r}={value!r} is not a recognised boolean. "
            f"Accepted: {sorted(_TRUE_VALUES | _FALSE_VALUES)}."
        )

    def get_list(
        self,
        key: str,
        separator: str = ",",
        default: list[str] | None = None,
    ) -> list[str]:
        """Return the value for ``key`` split on ``separator`` or ``default``.

        Values already typed as ``list`` are returned as-is. Strings are split
        on the separator, stripped, and empty fragments are dropped.
        """
        value = getattr(self._config, key, None)
        if value is None:
            return list(default) if default is not None else []
        if isinstance(value, list):
            return [str(item) for item in value]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        return [item.strip() for item in str(value).split(separator) if item.strip()]

    def is_production(self) -> bool:
        return getattr(self._config, "APP_ENV", None) == "production"

    def is_development(self) -> bool:
        return getattr(self._config, "APP_ENV", None) == "development"

    def is_test(self) -> bool:
        return getattr(self._config, "APP_ENV", None) == "test"
