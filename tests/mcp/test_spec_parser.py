"""Tests for the pure spec parser + canonicaliser + env substitution."""

import pytest

from ajolopy.mcp.errors import MCPConfigError
from ajolopy.mcp.spec import (
    canonicalize_spec,
    normalise_url,
    parse_spec,
    stdio_command,
    substitute_env,
    validate_env_refs,
)


def test_stdio_basic() -> None:
    assert parse_spec("stdio:npx -y @mcp/github") == "stdio"
    assert stdio_command("stdio:npx -y @mcp/github") == ["npx", "-y", "@mcp/github"]


def test_stdio_quoted_args() -> None:
    cmd = stdio_command('stdio:python -m my.server --flag "hello world"')
    assert cmd == ["python", "-m", "my.server", "--flag", "hello world"]


def test_http_and_https() -> None:
    assert parse_spec("https://api.example.com/mcp") == "http"
    assert parse_spec("http://localhost:9000/mcp") == "http"


def test_sse_variants() -> None:
    assert parse_spec("sse://example.com/sse") == "sse"
    assert parse_spec("mcp+sse://example.com/sse") == "sse"
    # sse:// is normalised to https:// for the runnable URL.
    assert normalise_url("sse://example.com/sse") == "https://example.com/sse"
    assert normalise_url("mcp+sse://example.com/sse") == "https://example.com/sse"


def test_unknown_scheme_raises() -> None:
    with pytest.raises(MCPConfigError, match="Accepted prefixes"):
        parse_spec("ftp://x.com")


def test_canonicalize_stdio_dedupes_whitespace() -> None:
    a = canonicalize_spec("stdio:npx -y @mcp/x")
    b = canonicalize_spec("stdio:  npx  -y   @mcp/x  ")
    c = canonicalize_spec("stdio:npx     -y @mcp/x")
    assert a == b == c == "stdio:npx -y @mcp/x"


def test_canonicalize_https_lowercases_scheme_strips_trailing_slash() -> None:
    a = canonicalize_spec("HTTPS://Api.Example.com/mcp/")
    b = canonicalize_spec("https://Api.Example.com/mcp")
    assert a == b
    assert a.startswith("https://")


def test_canonicalize_preserves_query_string() -> None:
    assert canonicalize_spec("https://example.com/mcp?a=1&b=2") == "https://example.com/mcp?a=1&b=2"


def test_env_substitution_replaces_known_vars() -> None:
    out = substitute_env({"token": "${X}", "nested": {"k": "${X}"}}, {"X": "secret"}, source="auth")
    assert out == {"token": "secret", "nested": {"k": "secret"}}


def test_env_substitution_collects_missing() -> None:
    missing: list[str] = []
    out = substitute_env({"k": "${X}", "m": "${Y}"}, {"Y": "set"}, source="auth", missing=missing)
    assert out == {"k": "", "m": "set"}
    assert missing == ["X"]


def test_env_substitution_raises_when_missing_no_collector() -> None:
    with pytest.raises(MCPConfigError, match="not set"):
        substitute_env("${ABSENT}", {}, source="auth.token")


def test_validate_env_refs_rejects_malformed() -> None:
    with pytest.raises(MCPConfigError, match="malformed"):
        validate_env_refs("Bearer ${UNCLOSED", source="auth.token")
