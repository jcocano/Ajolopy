"""Build ``data/docs-index.jsonl`` from the framework's own ``docs/`` tree.

The script walks ``../../docs/**/*.md`` (relative to the docsbot project
root), splits each page into paragraph-level chunks separated by blank
lines, and writes one JSON object per line to ``data/docs-index.jsonl``.

Each record has the shape::

    {
        "id": "reference/agent.md#3",
        "path": "reference/agent.md",
        "title": "@Agent",
        "text": "…paragraph contents…",
    }

The script is deterministic and reproducible — run it any time the docs
change to refresh the in-memory retriever's snapshot. The README
documents the refresh step.

Usage::

    cd dogfood/docsbot
    uv run python scripts/build_index.py
"""

import json
import re
from pathlib import Path

# Resolve directories relative to the script so it runs from any cwd.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _PROJECT_ROOT.parent.parent
_DOCS_ROOT = _REPO_ROOT / "docs"
_OUTPUT_PATH = _PROJECT_ROOT / "data" / "docs-index.jsonl"

# Paragraph splitter: blank lines (any whitespace) separate chunks.
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
# Title splitter: pull the first H1 if present; fall back to the file stem.
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", flags=re.MULTILINE)


def _extract_title(text: str, fallback: str) -> str:
    """Return the file's first H1 or ``fallback`` when missing."""
    match = _H1_RE.search(text)
    if match is None:
        return fallback
    return match.group(1)


def _chunk_paragraphs(text: str) -> list[str]:
    """Split ``text`` into non-empty paragraphs."""
    chunks: list[str] = []
    for raw in _PARAGRAPH_RE.split(text):
        stripped = raw.strip()
        if stripped:
            chunks.append(stripped)
    return chunks


def main() -> None:
    """Walk ``docs/`` and write the JSONL snapshot."""
    if not _DOCS_ROOT.is_dir():
        raise SystemExit(f"docs/ not found at {_DOCS_ROOT}")

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    records_written = 0
    with _OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for md_path in sorted(_DOCS_ROOT.rglob("*.md")):
            rel = md_path.relative_to(_DOCS_ROOT).as_posix()
            text = md_path.read_text(encoding="utf-8")
            title = _extract_title(text, fallback=md_path.stem)
            for index, chunk in enumerate(_chunk_paragraphs(text)):
                record: dict[str, str] = {
                    "id": f"{rel}#{index}",
                    "path": rel,
                    "title": title,
                    "text": chunk,
                }
                out.write(json.dumps(record, ensure_ascii=False))
                out.write("\n")
                records_written += 1

    print(f"wrote {records_written} chunks to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
