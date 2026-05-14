"""``@MCP`` class decorator.

Validates the configuration at decoration time and stamps the class
with ``_ajolopy_mcp`` metadata + registers it with the process-wide
:class:`MCPRegistry`. The decorator never spawns processes nor opens
connections — that work happens at factory boot via
:meth:`MCPRegistry.connect_all_for`.

The decorator's contract:

- ``servers=`` must be non-empty. Either a dict (user-chosen keys) or a
  list (auto-keyed ``"server_0"`` / ``"server_1"`` / ...).
- Each entry must be either a recognised string spec (``stdio:`` /
  ``http://`` / ``https://`` / ``sse://`` / ``mcp+sse://``) or an
  :class:`MCPClient` instance.
- ``auth=`` keys must be a subset of ``servers=`` keys.
- ``auth[<key>]`` MUST NOT be supplied for entries that are
  :class:`MCPClient` instances (instances own their credentials).
- ``timeout=`` must be a positive number; default 30 seconds.
- ``${VAR}`` references inside auth string values are SYNTACTICALLY
  validated at decoration time. Actual env lookup happens at boot so
  the same module can be imported in environments where the var is
  not yet set.
"""

import numbers
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .client import MCPClient
from .errors import MCPConfigError
from .registry import ServerEntry, get_mcp_registry
from .spec import Transport, parse_spec, validate_env_refs

_DEFAULT_TIMEOUT_S = 30.0


@dataclass(slots=True, frozen=True)
class MCPMetadata:
    """Decoration-time metadata stamped on a ``@MCP``-decorated class.

    Accessed via ``cls._ajolopy_mcp``. Carries the parsed server entry
    list plus the timeout so the registry can rebuild its plan without
    re-running the decorator's parsing.
    """

    entries: tuple[ServerEntry, ...]
    timeout: float


def MCP[T](  # noqa: N802 — public surface mirrors the Brief's primitive name.
    *,
    servers: Mapping[str, str | MCPClient] | list[str | MCPClient],
    auth: dict[str, dict[str, Any]] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> Callable[[type[T]], type[T]]:
    """Class decorator that declares external MCP-server integrations.

    See ``specs/mcp.md`` for the full surface and acceptance criteria.
    """
    _validate_timeout(timeout)
    keyed_specs = _materialise_servers(servers)
    if not keyed_specs:
        raise MCPConfigError("@MCP servers= must contain at least one entry.")
    auth_map = _validate_auth(auth, keyed_specs)
    entries = tuple(_build_entries(keyed_specs, auth_map))

    def _decorate(cls: type[T]) -> type[T]:
        metadata = MCPMetadata(entries=entries, timeout=float(timeout))
        cls._ajolopy_mcp = metadata  # type: ignore[attr-defined]
        get_mcp_registry().register_class(
            cls,
            entries=list(entries),
            timeout=float(timeout),
        )
        return cls

    return _decorate


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_timeout(timeout: float) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, numbers.Real):
        raise MCPConfigError(f"@MCP timeout= must be a positive number, got {timeout!r}.")
    if float(timeout) <= 0:
        raise MCPConfigError(f"@MCP timeout= must be > 0, got {timeout}.")


def _materialise_servers(
    servers: Mapping[str, str | MCPClient] | list[str | MCPClient],
) -> list[tuple[str, str | MCPClient]]:
    """Normalise ``servers=`` into an ordered list of ``(key, spec)`` tuples."""
    if isinstance(servers, Mapping):
        return [(str(key), value) for key, value in servers.items()]
    if isinstance(servers, list):  # pyright: ignore[reportUnnecessaryIsInstance]
        return [(f"server_{idx}", spec) for idx, spec in enumerate(servers)]
    raise MCPConfigError(f"@MCP servers= must be a dict or a list, got {type(servers).__name__}.")


def _validate_auth(
    auth: dict[str, dict[str, Any]] | None,
    servers: list[tuple[str, str | MCPClient]],
) -> dict[str, dict[str, Any]]:
    if auth is None:
        return {}
    server_keys = {key for key, _ in servers}
    instance_keys = {key for key, spec in servers if isinstance(spec, MCPClient)}
    unknown = set(auth.keys()) - server_keys
    if unknown:
        raise MCPConfigError(
            f"@MCP auth= references unknown server key(s) {sorted(unknown)!r}. "
            f"Known keys: {sorted(server_keys)!r}."
        )
    forbidden = set(auth.keys()) & instance_keys
    if forbidden:
        raise MCPConfigError(
            f"@MCP auth= cannot be supplied for MCPClient instance entries "
            f"{sorted(forbidden)!r} — instances own their credentials."
        )
    # Validate ${VAR} reference syntax now so typos surface at decoration time.
    for key, value in auth.items():
        validate_env_refs(value, source=f"auth[{key!r}]")
    return auth


def _build_entries(
    servers: list[tuple[str, str | MCPClient]],
    auth: dict[str, dict[str, Any]],
) -> list[ServerEntry]:
    out: list[ServerEntry] = []
    for key, spec in servers:
        if isinstance(spec, MCPClient):
            out.append(ServerEntry(key=key, spec=spec, transport="custom", auth=None))
            continue
        if not isinstance(spec, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise MCPConfigError(
                f"@MCP servers[{key!r}] must be a string spec or an MCPClient "
                f"instance, got {type(spec).__name__}."
            )
        transport: Transport = parse_spec(spec)
        out.append(
            ServerEntry(
                key=key,
                spec=spec,
                transport=transport,
                auth=auth.get(key),
            )
        )
    return out


__all__ = [
    "MCP",
    "MCPMetadata",
]
