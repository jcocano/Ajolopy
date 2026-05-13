"""Lifecycle hook orchestration.

Public surface:

- :class:`LifecycleManager` walks :meth:`Container.iter_singletons` to
  fire ``on_module_init`` / ``on_app_bootstrap`` / ``on_app_shutdown``
  hooks at bootstrap and shutdown.

``AjolopyFactory.create`` (AJ-14) composes this manager into the
ASGI lifespan; tests can drive it directly with a hand-built
container.
"""

from .manager import LifecycleManager

__all__ = ["LifecycleManager"]
