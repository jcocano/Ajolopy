"""AJ-47 — confidence gate for the mkdocs site.

The full smoke test is ``uv run mkdocs build --strict`` in the docs CI
workflow; this module just asserts that every Markdown file under
``docs/`` declares at least one top-level ``#`` heading. Without that
heading mkdocs builds a page with no <h1>, which renders as an
empty entry in the nav and is almost always a content mistake.
"""

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _markdown_files() -> list[Path]:
    return sorted(DOCS_DIR.rglob("*.md"))


def test_docs_directory_exists() -> None:
    assert DOCS_DIR.is_dir(), f"expected docs/ at {DOCS_DIR}"


@pytest.mark.parametrize("path", _markdown_files(), ids=lambda p: str(p.relative_to(DOCS_DIR)))
def test_markdown_has_top_level_heading(path: Path) -> None:
    """Every page must declare an H1 so it renders correctly in nav."""
    text = path.read_text(encoding="utf-8")
    has_h1 = any(line.startswith("# ") for line in text.splitlines())
    assert has_h1, f"{path.relative_to(DOCS_DIR)} is missing a top-level '# ' heading"
