"""Server-spec parsing for the ``@MCP`` decorator.

Pure, side-effect-free helpers that turn user-supplied ``servers=``
entries into normalised metadata. Three responsibilities:

- :func:`parse_spec` — classify a string spec into a ``(transport,
  spec_str)`` tuple. Recognised prefixes: ``stdio:``, ``http://`` /
  ``https://``, ``sse://`` / ``mcp+sse://``. Anything else raises
  :class:`MCPConfigError` with the list of accepted prefixes.
- :func:`canonicalize_spec` — derive the pool key the
  :class:`~ajolopy.mcp.registry.MCPRegistry` uses to dedupe connections.
  Whitespace is normalised, scheme is casefolded, trailing slashes on
  URLs are stripped.
- :func:`substitute_env` — resolve ``${VAR}`` references inside auth
  string values. Recursive over nested dicts. Two failure modes: a
  malformed reference (caught at decoration time via
  :func:`validate_env_refs`) and an absent variable (boot-time WARN,
  caller marks server unhealthy).

No I/O happens here. The registry handles connect / list_tools / call_tool;
this module is import-clean and free of MCP SDK dependencies.
"""

import re
import shlex
from typing import Any, Literal, cast

from .errors import MCPConfigError

Transport = Literal["stdio", "http", "sse", "custom"]
"""Recognised transport families. ``custom`` is reserved for
:class:`MCPClient` instance entries — those bypass spec parsing."""

_STDIO_PREFIX = "stdio:"
_HTTP_PREFIXES = ("http://", "https://")
_SSE_PREFIXES = ("sse://", "mcp+sse://")

_ACCEPTED_PREFIXES = (
    _STDIO_PREFIX,
    *_HTTP_PREFIXES,
    *_SSE_PREFIXES,
)

# Match ``${IDENTIFIER}`` — Python-style identifier inside braces. Anything
# else (``${0bad}``, ``${has space}``, unclosed ``${VAR``) is rejected at
# decoration time so the user sees the typo early.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MALFORMED_DOLLAR = re.compile(r"\$\{[^}]*$")


def parse_spec(spec: str) -> Transport:
    """Classify ``spec`` into its transport family.

    Raises :class:`MCPConfigError` for unknown schemes. The returned
    transport drives downstream behaviour: stdio specs are tokenised
    with :func:`shlex.split` at connect time; HTTP / SSE specs are
    passed verbatim to the MCP SDK's URL-based clients.
    """
    lowered = spec.strip().lower()
    if lowered.startswith(_STDIO_PREFIX):
        return "stdio"
    if lowered.startswith(_HTTP_PREFIXES):
        return "http"
    if lowered.startswith(_SSE_PREFIXES):
        return "sse"
    accepted = ", ".join(_ACCEPTED_PREFIXES)
    raise MCPConfigError(f"Unrecognised MCP server spec {spec!r}. Accepted prefixes: {accepted}.")


def stdio_command(spec: str) -> list[str]:
    """Return the argv for a stdio spec (``"stdio:<cmd>"``)."""
    if not spec.lower().startswith(_STDIO_PREFIX):
        raise MCPConfigError(f"Spec {spec!r} is not a stdio spec.")
    command_str = spec[len(_STDIO_PREFIX) :].strip()
    if not command_str:
        raise MCPConfigError(f"stdio spec {spec!r} has no command after the scheme.")
    tokens = shlex.split(command_str)
    if not tokens:
        raise MCPConfigError(f"stdio spec {spec!r} parsed into zero tokens.")
    return tokens


def normalise_url(spec: str) -> str:
    """Return a runnable URL for an HTTP / SSE spec.

    ``sse://`` and ``mcp+sse://`` are normalised to ``https://`` for the
    underlying SSE channel; HTTP specs are passed through unchanged
    (except for trailing-slash trimming, which canonicalisation already
    handles separately).
    """
    lowered = spec.lower()
    if lowered.startswith("mcp+sse://"):
        return "https://" + spec[len("mcp+sse://") :]
    if lowered.startswith("sse://"):
        return "https://" + spec[len("sse://") :]
    return spec


def canonicalize_spec(spec: str) -> str:
    """Derive the connection-pool key for ``spec``.

    For stdio specs we tokenise + re-join so whitespace and quoting
    differences map to the same key. For URL specs we lowercase the
    scheme, strip trailing slashes from the path, and preserve any
    query string verbatim.

    Caller guarantees ``spec`` has already passed :func:`parse_spec`.
    """
    transport = parse_spec(spec)
    if transport == "stdio":
        tokens = stdio_command(spec)
        return f"stdio:{' '.join(tokens)}"

    url = normalise_url(spec).strip()
    # Lowercase the scheme component, keep host + path case (paths are
    # case-sensitive on most MCP servers). Strip trailing slash from
    # the path-only portion (preserve query strings).
    scheme_sep = "://"
    head, _, rest = url.partition(scheme_sep)
    scheme = head.lower()
    # Split off a query string and re-attach later so we do not chew
    # through whitespace inside ``?key=value`` pairs.
    path, query_sep, query = rest.partition("?")
    path = path.rstrip("/")
    canonical = f"{scheme}{scheme_sep}{path}"
    if query_sep:
        canonical = f"{canonical}?{query}"
    return canonical


def validate_env_refs(value: Any, *, source: str) -> None:
    """Walk ``value`` (str / dict / list) checking ``${...}`` references.

    Recursive. Raises :class:`MCPConfigError` for malformed references
    (unclosed braces, non-identifier names). Absent env vars are NOT a
    decoration-time error — they only surface at boot. ``source`` is the
    field name (``"auth['github'].env"``) used in error messages.
    """
    if isinstance(value, str):
        if _MALFORMED_DOLLAR.search(value):
            raise MCPConfigError(
                f"{source}: malformed ${{...}} reference in {value!r} "
                f"(unclosed brace or invalid identifier)."
            )
        # Find every `${...}` and reject anything that does not match the
        # strict identifier shape.
        for match in re.finditer(r"\$\{([^}]*)\}", value):
            ref = match.group(1)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ref):
                raise MCPConfigError(
                    f"{source}: ${{{ref}}} is not a valid environment-variable "
                    f"name (must match [A-Za-z_][A-Za-z0-9_]*)."
                )
        return
    if isinstance(value, dict):
        dict_value = cast("dict[Any, Any]", value)
        for key, item in dict_value.items():
            validate_env_refs(item, source=f"{source}.{key}")
        return
    if isinstance(value, list):
        list_value = cast("list[Any]", value)
        for index, item in enumerate(list_value):
            validate_env_refs(item, source=f"{source}[{index}]")
        return
    # Non-string / non-collection values are passed through untouched.


def substitute_env(
    value: Any,
    env: dict[str, str],
    *,
    source: str,
    missing: list[str] | None = None,
) -> Any:
    """Replace ``${VAR}`` references in ``value`` with values from ``env``.

    Recursive over dicts and lists. Returns a NEW structure rather than
    mutating in place so callers can safely share the original auth
    spec across multiple boot attempts (e.g. across two ``@MCP``
    classes referencing the same server). Missing variables are
    collected into ``missing`` if supplied; otherwise an
    :class:`MCPConfigError` is raised on the first absent var. The
    registry uses the list form at boot to report all missing names in
    one WARN log.
    """
    if isinstance(value, str):
        return _substitute_str(value, env, source=source, missing=missing)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        dict_value = cast("dict[Any, Any]", value)
        for key, item in dict_value.items():
            out[str(key)] = substitute_env(item, env, source=f"{source}.{key}", missing=missing)
        return out
    if isinstance(value, list):
        list_value = cast("list[Any]", value)
        return [
            substitute_env(item, env, source=f"{source}[{idx}]", missing=missing)
            for idx, item in enumerate(list_value)
        ]
    return value


def _substitute_str(
    value: str,
    env: dict[str, str],
    *,
    source: str,
    missing: list[str] | None,
) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in env:
            return env[name]
        if missing is not None:
            missing.append(name)
            return ""
        raise MCPConfigError(f"{source}: environment variable ${{{name}}} is not set.")

    return _ENV_REF.sub(_replace, value)


__all__ = [
    "Transport",
    "canonicalize_spec",
    "normalise_url",
    "parse_spec",
    "stdio_command",
    "substitute_env",
    "validate_env_refs",
]
