"""Configuration layer — typed env loading + injectable accessor.

Public surface:

- ``BaseConfig`` — subclass to declare an app's environment variables.
- ``ConfigService`` — ergonomic accessor wrapper consumed by every other
  framework layer that needs to read configuration.
- ``ConfigMissingError`` — raised by ``ConfigService.require`` /
  ``get_int`` / ``get_bool`` when a key is missing without a fallback.
"""

from .base import BaseConfig
from .service import ConfigMissingError, ConfigService

__all__ = [
    "BaseConfig",
    "ConfigMissingError",
    "ConfigService",
]
