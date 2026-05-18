"""Tiny ``/health`` route mounted for the deployment's liveness probe.

The bot's only real surface is ``@Stream("/chat")``. Fly's healthcheck
(``fly.toml`` → ``[checks.health]``) hits ``GET /health`` and uses the
status code to decide whether the machine is alive. Without this route
mounted, fly's proxy returns 500 / 503 on every probe and the deploy
is permanently "unhealthy".

Keeping it as a controller (rather than a Starlette mount in
``main.py``) keeps the framework's standard routing surface in charge
and makes the route discoverable to anyone reading the module.
"""

from ajolopy import Get


class Health:
    """Liveness probe target for fly's healthcheck."""

    @Get("/health")
    async def health(self) -> dict[str, str]:
        """Return a static OK payload. Fly only cares about the 200."""
        return {"status": "ok"}


__all__ = ["Health"]
