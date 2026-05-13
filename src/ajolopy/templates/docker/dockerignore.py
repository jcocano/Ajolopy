"""``.dockerignore`` text renderer.

Mirrors the canonical list from ``07 - Deploy y Docker`` so generated
projects ship with a predictable ignore set on day one. The renderer
takes no arguments — the list is deliberately flat. Downstream callers
that need to extend it concatenate their own entries to the returned
string.
"""

# Canonical entries, in the order documented in `07 - Deploy y Docker`.
# Hand-written tuple (not a set) so the output is deterministic and the
# reviewability ordering matches the doc 1-for-1.
_ENTRIES: tuple[str, ...] = (
    "__pycache__/",
    "*.py[cod]",
    "*$py.class",
    "*.so",
    ".Python",
    ".venv/",
    "venv/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".env",
    ".env.local",
    ".env.*.local",
    ".vscode/",
    ".idea/",
    "*.swp",
    "tests/",
    "docs/",
    ".github/",
    ".git/",
    "README.md",
)


def render_dockerignore() -> str:
    """Return the canonical ``.dockerignore`` body as a single string.

    The output ends with a trailing newline (POSIX convention for text
    files) but has no leading blank line and no blank-line padding between
    entries. Callers that want to append their own entries can do
    ``render_dockerignore() + "extra/\\n"`` without worrying about
    accidental blank lines.
    """

    return "\n".join(_ENTRIES) + "\n"
