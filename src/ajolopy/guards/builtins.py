"""Built-in guards shipped with v0.1.

Two are enough to cover the wedge user's day-one needs:

- :class:`BearerTokenGuard` — ``Authorization: Bearer <token>`` checked
  against an env-derived value (or a literal for tests).
- :class:`IPAllowlistGuard` — remote-client IP matched against a CIDR
  list, with optional ``X-Forwarded-For`` honouring for deployments
  sitting behind a known proxy.

The two patterns ("read a header" + "inspect ``request.client``") cover
the ~80% of internal-endpoint gating users hand-roll today.
"""

import ipaddress
import os
from typing import TYPE_CHECKING, override

from .base import Guard
from .errors import GuardForbiddenError, GuardUnauthorizedError, UseGuardsConfigError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.requests import Request


class BearerTokenGuard(Guard):
    """Check ``Authorization: Bearer <token>`` against a token source.

    Construction does NOT read the env var — the lookup happens on
    every request so a test fixture that sets ``os.environ`` after the
    guard is built still works, and so rotated tokens take effect
    without re-instantiating the guard.

    When ``token=`` is provided the literal string wins and the env
    var is ignored entirely (useful for tests and constant-secret
    deployments). When only ``token_env=`` is set and the env var is
    unset at request time, the guard returns 401 with a GENERIC
    message — leaking that the env var is unset would tell an attacker
    which knob to set in their own environment.
    """

    __slots__ = ("_literal", "_token_env")

    def __init__(
        self,
        *,
        token_env: str = "API_TOKEN",  # noqa: S107 — env-var NAME, not a credential.
        token: str | None = None,
    ) -> None:
        self._token_env = token_env
        self._literal = token

    @override
    async def can_activate(self, request: Request) -> bool:
        header = request.headers.get("authorization") or ""
        scheme, _, presented = header.partition(" ")
        if not header:
            raise GuardUnauthorizedError("Authentication required.")
        if scheme.lower() != "bearer" or not presented:
            raise GuardUnauthorizedError("Authentication required.")
        expected = self._resolve_expected()
        if expected is None:
            # Missing config at request time — surface a generic 401 so
            # the attacker cannot distinguish "env var unset" from
            # "wrong token" by status code.
            raise GuardUnauthorizedError("Authentication required.")
        if presented != expected:
            raise GuardForbiddenError("Invalid authentication token.")
        return True

    def _resolve_expected(self) -> str | None:
        """Return the expected token, or ``None`` when unconfigured.

        Lazy by design: every request consults the live env at the time
        the guard runs. Tests rely on this so they can set the env var
        after the controller is decorated.
        """
        if self._literal is not None:
            return self._literal
        value = os.environ.get(self._token_env)
        return value or None


class IPAllowlistGuard(Guard):
    """Allow requests whose remote IP matches a CIDR list.

    The ``allowed`` argument accepts host literals (``"127.0.0.1"``) or
    CIDR ranges (``"10.0.0.0/8"``, ``"::1/128"``) — both are parsed once
    at construction via :func:`ipaddress.ip_network` (``strict=False``).
    An invalid entry raises :class:`UseGuardsConfigError` at decoration
    time so typos surface during import / boot, not on a hot path.

    ``trust_forwarded_for=False`` (the default) checks
    ``request.client.host``. Set ``True`` only behind a proxy that
    rewrites ``X-Forwarded-For`` for you — otherwise any client can
    spoof their IP. The leftmost value of the header wins; the rest is
    ignored.
    """

    __slots__ = ("_networks", "_trust_forwarded_for")

    def __init__(
        self,
        *,
        allowed: Iterable[str],
        trust_forwarded_for: bool = False,
    ) -> None:
        self._trust_forwarded_for = trust_forwarded_for
        # Eager validation: each spec is parsed exactly once and stored
        # as an ``IPv4Network`` / ``IPv6Network`` for fast membership
        # checks at request time.
        self._networks = tuple(_parse_networks(allowed))
        if not self._networks:
            raise UseGuardsConfigError(
                "IPAllowlistGuard requires at least one CIDR or host in allowed=."
            )

    @override
    async def can_activate(self, request: Request) -> bool:
        host = self._extract_host(request)
        if host is None:
            raise GuardForbiddenError("Client IP is not allowed.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise GuardForbiddenError("Client IP is not allowed.") from exc
        for network in self._networks:
            if address in network:
                return True
        raise GuardForbiddenError("Client IP is not allowed.")

    def _extract_host(self, request: Request) -> str | None:
        """Pick the IP to check, honouring ``trust_forwarded_for``.

        The leftmost ``X-Forwarded-For`` value wins when the flag is
        set AND the header is present. With the flag unset, the header
        is ignored entirely — a deliberate posture so the default
        configuration cannot be tricked by a spoofed header.
        """
        if self._trust_forwarded_for:
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                leftmost = xff.split(",", 1)[0].strip()
                if leftmost:
                    return leftmost
        client = request.client
        if client is None:
            return None
        return client.host


def _parse_networks(
    specs: Iterable[str],
) -> Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse each CIDR / host spec via :func:`ipaddress.ip_network`.

    ``strict=False`` so host literals like ``"127.0.0.1"`` (which would
    otherwise complain about non-network host bits) are accepted as
    ``/32`` (or ``/128`` for IPv6) implicitly.
    """
    for spec in specs:
        if not isinstance(spec, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise UseGuardsConfigError(
                f"IPAllowlistGuard allowed= entries must be strings, "
                f"got {type(spec).__name__}: {spec!r}."
            )
        try:
            yield ipaddress.ip_network(spec, strict=False)
        except ValueError as exc:
            raise UseGuardsConfigError(
                f"IPAllowlistGuard allowed= entry {spec!r} is not a valid "
                f"IP address or CIDR range: {exc}."
            ) from exc


__all__ = [
    "BearerTokenGuard",
    "IPAllowlistGuard",
]
