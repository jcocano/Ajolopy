"""Shared template-rendering helpers for ``ajolopy new`` and ``ajolopy generate``.

The two scaffolders share two concerns:

1. **Walking** a ``.tmpl`` tree loaded via :mod:`importlib.resources`
   so the templates survive being shipped inside the installed
   wheel.
2. **Substituting** a small dictionary of variables into both file
   contents (``{name}`` -> ``support``) and path segments
   (``__package__`` -> the auto-detected package name).

Both behaviours used to live inside :mod:`ajolopy.cli.commands.new`;
they are pulled out here so :mod:`ajolopy.cli.commands.generate` can
reuse them without importing the ``new`` module (which would drag in
the wizard-only dependencies).

The helpers are deliberately tiny — no global state, no class —
because the scaffolders only need plain functions plus a constant
or two.
"""

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

__all__ = [
    "PATH_TOKEN_TO_CONTEXT_KEY",
    "TEMPLATE_SUFFIX",
    "read_template",
    "render_path",
    "strip_template_suffix",
]


# ---------------------------------------------------------------------------
# Constants — kept as module attributes so callers can reference them by
# name (e.g. ``_template_engine.TEMPLATE_SUFFIX``) instead of hard-coding
# the literal in every site.
# ---------------------------------------------------------------------------
TEMPLATE_SUFFIX: Final = ".tmpl"

# Sentinel path segments translated into context values. The keys use
# Python keyword markers (``__package__``) so the source tree stays
# importable / browsable inside the installed package — a plain
# ``{package_name}`` segment would clash with the substitution pass
# that runs on file contents.
PATH_TOKEN_TO_CONTEXT_KEY: Final[dict[str, str]] = {
    "__package__": "package_name",
}


def render_path(relative: str, context: dict[str, str]) -> str:
    """Translate sentinel path segments into their context values.

    Each ``/``-separated component of ``relative`` is looked up in
    :data:`PATH_TOKEN_TO_CONTEXT_KEY`; the matching value from
    ``context`` replaces the segment when the lookup hits, otherwise
    the segment passes through unchanged.
    """
    parts: list[str] = []
    for segment in relative.split("/"):
        key = PATH_TOKEN_TO_CONTEXT_KEY.get(segment)
        parts.append(context[key] if key is not None else segment)
    return "/".join(parts)


def strip_template_suffix(relative: str) -> str:
    """Return ``relative`` with the ``.tmpl`` suffix removed (if present)."""
    if relative.endswith(TEMPLATE_SUFFIX):
        return relative[: -len(TEMPLATE_SUFFIX)]
    return relative


def read_template(entry: Traversable, context: dict[str, str]) -> str:
    """Read ``entry`` as UTF-8 and (when ``.tmpl``) substitute ``context``.

    Used by both scaffolders: the file's logical name carries the
    ``.tmpl`` suffix and the body needs :func:`str.format` substitution;
    non-``.tmpl`` companion files (e.g. raw ``.jsonl`` fixtures shipped
    alongside the templates) are returned verbatim.
    """
    text = entry.read_text(encoding="utf-8")
    name = entry.name
    if name.endswith(TEMPLATE_SUFFIX):
        return text.format(**context)
    return text
