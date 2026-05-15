"""Build ``data/index.jsonl`` from ``data/source-docs/**/*.md``.

The script implements the three RAG quality bumps documented in
``specs/example-contextual-rag.md``:

1. **Contextual chunking.** Each Markdown file is split along H2 / H3
   header boundaries (header text becomes the chunk's ``section``).
   The file's first H1 becomes the chunk's ``title``; a hand-authored
   one-line summary of the parent section (sourced from
   :data:`CONTEXT_SUMMARIES`) is attached as ``context_summary``. The
   summary is prepended to ``text`` at retrieval time so the chunk
   reads sensibly in isolation when the LLM sees it.

2. **Hybrid retrieval ingredients.** Each chunk record carries a
   ``keywords`` list (top tokens by frequency, with stopwords removed)
   and an ``embedding_hash`` (a deterministic 16-bit fingerprint of the
   chunk's token set, computed by
   :func:`contextual_rag.scripts_runtime.embedding_hash`). The
   retriever combines a Jaccard score over keywords with a
   Hamming-distance score over the hash.

3. **Citation-ready metadata.** ``path``, ``section``, ``title``, and a
   stable ``chunk_id`` of the form ``<path>#<slug>`` are stored on
   every record so the agent's formatter tool can render
   ``[path#section]`` citations.

The script is deterministic and reproducible. Re-run it any time the
source docs change to refresh ``data/index.jsonl``::

    cd examples/contextual-rag
    uv run python scripts/build_index.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — resolved relative to the script so it runs from any cwd.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SOURCE_DIR = _PROJECT_ROOT / "data" / "source-docs"
_OUTPUT_PATH = _PROJECT_ROOT / "data" / "index.jsonl"
_PACKAGE_SRC = _PROJECT_ROOT / "src"


# Make ``contextual_rag.scripts_runtime`` importable from a fresh clone
# even if the user has not run ``uv sync`` yet. The package layout is
# editable in development; this fallback covers ``python scripts/...``
# straight after cloning.
if str(_PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SRC))


from contextual_rag.scripts_runtime import (  # noqa: E402 — path setup above
    content_tokens,
    embedding_hash,
    tokenise,
)

# ---------------------------------------------------------------------------
# Markdown parsing.
# ---------------------------------------------------------------------------
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", flags=re.MULTILINE)
_HEADER_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Hand-authored per-section summaries.
#
# Keyed by ``(path, section)`` where ``path`` is the source file's
# relative posix path under ``data/source-docs/`` and ``section`` is the
# H2/H3 heading text. Missing keys fall back to a generic summary built
# from the chunk's title + section.
#
# Editing the source markdown does NOT invalidate these summaries —
# keeping them in code (instead of in the markdown) is what lets the
# build script re-run without losing context.
# ---------------------------------------------------------------------------
CONTEXT_SUMMARIES: dict[tuple[str, str], str] = {
    # welcome.md
    ("handbook/welcome.md", "Who we are"): (
        "Company background for the sample handbook: a fictional 40-person "
        "Series A SaaS used as the RAG fixture."
    ),
    ("handbook/welcome.md", "What this handbook covers"): (
        "Index of the sample handbook's eight files so retrieval lands on the right page."
    ),
    ("handbook/welcome.md", "How to read this handbook"): (
        "Authoring convention: one H1 title plus short H2 sections so "
        "header-based chunking has clean boundaries."
    ),
    # onboarding.md
    ("handbook/onboarding.md", "Day one"): (
        "First-day checklist for new engineers: laptop, SSO, Slack, buddy walkthrough."
    ),
    ("handbook/onboarding.md", "Week one"): (
        "Week one is paired programming across services; no solo commits expected."
    ),
    ("handbook/onboarding.md", "Week two"): (
        "Week two: ship a good-first-issue end-to-end, including code review and deployment."
    ),
    # dev-environment.md
    ("handbook/dev-environment.md", "Getting set up"): (
        "Local-toolchain bootstrap: install uv and pnpm, run make "
        "bootstrap once, idempotent thereafter."
    ),
    ("handbook/dev-environment.md", "Local services"): (
        "Local stack via docker compose: Postgres, Redis, NATS. Frontend "
        "talks to mock API by default."
    ),
    ("handbook/dev-environment.md", "Editor configuration"): (
        "Repo ships editor config + pyright strict; pre-commit rejects new type errors."
    ),
    # code-review.md
    ("handbook/code-review.md", "Opening a pull request"): (
        "Draft PRs early. Conventional Commits title format under 70 characters."
    ),
    ("handbook/code-review.md", "Reviewer expectations"): (
        "One reviewer for in-package changes, two for cross-package or "
        "deploy-pipeline changes. Focus on interface, not style."
    ),
    ("handbook/code-review.md", "Merging"): (
        "Squash-merge by default; rebase-merge only for hot-fix branches to preserve timestamps."
    ),
    # security.md
    ("handbook/security.md", "Secrets handling"): (
        "Every secret in the password manager. gitleaks pre-commit. "
        "Rotate first, file the report after."
    ),
    ("handbook/security.md", "Single sign-on"): (
        "Every internal tool sits behind SSO. New employees enrolled day "
        "one. Non-SSO tools need security-lead approval."
    ),
    ("handbook/security.md", "Incident response"): (
        "Anyone can declare an incident. First responder posts to "
        "#incidents, opens runbook, pages on-call; PIR within five days."
    ),
    # deployment.md
    ("handbook/deployment.md", "Continuous delivery"): (
        "Every merge to main goes to staging; production after 30 minutes "
        "green. Image SHA pinned end-to-end."
    ),
    ("handbook/deployment.md", "Rolling back"): (
        "Rollback is one make command and auto-opens an incident ticket. "
        "Flag every rollback in #engineering."
    ),
    ("handbook/deployment.md", "Release captain"): (
        "Release captain rotates weekly; owns deploy review, customer "
        "release notes, and incident point-of-contact."
    ),
    # time-off.md
    ("handbook/time-off.md", "Annual minimum"): (
        "Unlimited PTO with a 20-day annual minimum tracked in HR and on manager dashboards."
    ),
    ("handbook/time-off.md", "Requesting time off"): (
        "Two-week notice for absences longer than a day; on-call rotation "
        "must be re-balanced first."
    ),
    ("handbook/time-off.md", "Public holidays"): (
        "Public holidays follow each employee's country of residence; "
        "additional observances filed as normal PTO."
    ),
    # expenses.md
    ("handbook/expenses.md", "What is covered"): (
        "Home office, co-working, conferences, work software covered. "
        "Off-sites booked through the company travel agent."
    ),
    ("handbook/expenses.md", "Filing an expense"): (
        "30-day filing window via the expense tool; manager-routed; "
        "reimbursed in the next payroll. 90-day hard deadline."
    ),
    ("handbook/expenses.md", "Receipts"): (
        "Receipt per line item. Card statement screenshot is the accepted "
        "fallback when a vendor refuses to issue a receipt."
    ),
}


def _slugify(text: str) -> str:
    """Return a URL-safe lowercase slug derived from ``text``."""
    lowered = text.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned or "section"


def _extract_title(text: str, fallback: str) -> str:
    """Return the file's first H1 or ``fallback`` when missing."""
    match = _H1_RE.search(text)
    if match is None:
        return fallback
    return match.group(1)


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split a Markdown file into ``(section_heading, body)`` pairs.

    Sections are demarcated by H2 or H3 headers. Body text between the
    H1 and the first H2 is folded into a synthetic "Overview" section
    so that nothing is silently dropped from the index.
    """
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        h1 = _H1_RE.search(text)
        body_start = 0 if h1 is None else h1.end()
        return [("Overview", text[body_start:].strip())]

    sections: list[tuple[str, str]] = []
    h1 = _H1_RE.search(text)
    preamble_start = 0 if h1 is None else h1.end()
    preamble = text[preamble_start : matches[0].start()].strip()
    if preamble:
        sections.append(("Overview", preamble))

    for index, match in enumerate(matches):
        heading = match.group(2)
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((heading, body))
    return sections


def _top_keywords(text: str, limit: int = 15) -> list[str]:
    """Return the top ``limit`` content tokens by frequency."""
    counter = Counter(content_tokens(tokenise(text)))
    return [token for token, _ in counter.most_common(limit)]


def _fallback_summary(title: str, section: str) -> str:
    """Generic context summary used when no hand-authored one exists."""
    return f"Section '{section}' of the '{title}' handbook page."


def main() -> None:
    """Walk ``data/source-docs/`` and write ``data/index.jsonl``."""
    if not _SOURCE_DIR.is_dir():
        raise SystemExit(f"source docs not found at {_SOURCE_DIR}")

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    records_written = 0
    with _OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for md_path in sorted(_SOURCE_DIR.rglob("*.md")):
            rel_path = md_path.relative_to(_SOURCE_DIR).as_posix()
            text = md_path.read_text(encoding="utf-8")
            title = _extract_title(text, fallback=md_path.stem)
            for section_heading, body in _split_sections(text):
                if not body:
                    continue
                chunk_id = f"{rel_path}#{_slugify(section_heading)}"
                context_summary = CONTEXT_SUMMARIES.get(
                    (rel_path, section_heading),
                    _fallback_summary(title, section_heading),
                )
                record: dict[str, object] = {
                    "path": rel_path,
                    "chunk_id": chunk_id,
                    "title": title,
                    "section": section_heading,
                    "context_summary": context_summary,
                    "text": body,
                    "keywords": _top_keywords(body),
                    "embedding_hash": embedding_hash(body),
                }
                out.write(json.dumps(record, ensure_ascii=False))
                out.write("\n")
                records_written += 1

    print(f"wrote {records_written} chunks to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
