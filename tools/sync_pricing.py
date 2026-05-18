"""Sync the embedded LiteLLM pricing snapshot with upstream.

Two modes:

- ``--check`` (default): fetch the upstream JSON, diff against the embedded
  copy, print a human-readable summary, exit non-zero on drift. The monthly
  GitHub Action calls this to decide whether to open a sync PR.
- ``--write``: overwrite the embedded snapshot with the upstream payload
  and update the recorded SHA constant in this file. The Action calls
  this when ``--check`` reports drift, then commits the result.

Network calls are confined to :func:`_fetch_upstream`; tests substitute it
with a fixture loader so the suite never touches the wire.
"""

import argparse
import difflib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

# Pinned upstream commit. Bump this manually when running with ``--write``;
# the GitHub Action's PR body should record the new SHA so reviewers see
# the diff range without having to inspect the file.
LITELLM_UPSTREAM_SHA = "410ce761dc234ba0f5a874c1415f5c423e87d860"
LITELLM_UPSTREAM_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/BerriAI/litellm/{sha}/model_prices_and_context_window.json"
)
LITELLM_HEAD_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = REPO_ROOT / "src" / "ajolopy" / "observability" / "pricing.json"

# Maximum lines of unified diff to print for any single mutated model entry.
_MAX_DIFF_LINES_PER_MODEL = 20


def _fetch_upstream(url: str) -> str:
    """Fetch the upstream JSON over HTTPS. Network call — patched in tests."""
    try:
        # The URL is a constant literal interpolated with a 40-char hex
        # commit SHA — no user input, no path traversal risk. ``S310`` lint
        # silenced because the scheme is hard-coded to ``https``.
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to fetch {url!r}: {exc}") from exc


def _load_snapshot(path: Path) -> str:
    return path.read_text("utf-8")


def _parse_json(payload: str, label: str) -> dict[str, Any]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} is not a JSON object")
    return data  # pyright: ignore[reportUnknownVariableType]


def diff_catalogs(
    embedded: Mapping[str, Any],
    upstream: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(added, removed, changed)`` model-name lists, all sorted."""
    embedded_keys = set(embedded.keys())
    upstream_keys = set(upstream.keys())
    added = sorted(upstream_keys - embedded_keys)
    removed = sorted(embedded_keys - upstream_keys)
    changed: list[str] = []
    for key in sorted(embedded_keys & upstream_keys):
        if embedded[key] != upstream[key]:
            changed.append(key)
    return added, removed, changed


def _format_summary(
    added: list[str],
    removed: list[str],
    changed: list[str],
    embedded: Mapping[str, Any],
    upstream: Mapping[str, Any],
) -> str:
    """Return a Markdown-ish, human-readable summary of the diff."""
    lines: list[str] = []
    lines.append(f"Added models   : {len(added)}")
    lines.append(f"Removed models : {len(removed)}")
    lines.append(f"Changed models : {len(changed)}")
    lines.append("")
    if added:
        lines.append("== Added ==")
        lines.extend(f"  + {name}" for name in added)
        lines.append("")
    if removed:
        lines.append("== Removed ==")
        lines.extend(f"  - {name}" for name in removed)
        lines.append("")
    if changed:
        lines.append("== Changed ==")
        for name in changed:
            lines.append(f"  ~ {name}")
            old_text = json.dumps(embedded[name], indent=2, sort_keys=True).splitlines()
            new_text = json.dumps(upstream[name], indent=2, sort_keys=True).splitlines()
            diff = list(
                difflib.unified_diff(
                    old_text,
                    new_text,
                    fromfile=f"embedded/{name}",
                    tofile=f"upstream/{name}",
                    lineterm="",
                )
            )
            for entry in diff[:_MAX_DIFF_LINES_PER_MODEL]:
                lines.append(f"    {entry}")
            omitted = len(diff) - _MAX_DIFF_LINES_PER_MODEL
            if omitted > 0:
                lines.append(f"    ... ({omitted} more lines omitted)")
        lines.append("")
    return "\n".join(lines)


def _replace_sha_constant(source: str, new_sha: str) -> str:
    """Rewrite the ``LITELLM_UPSTREAM_SHA`` literal in this file's text."""
    pattern = re.compile(r'^(LITELLM_UPSTREAM_SHA\s*=\s*)"[^"]*"', re.MULTILINE)
    replacement = rf'\g<1>"{new_sha}"'
    new_source, count = pattern.subn(replacement, source)
    if count == 0:
        raise RuntimeError("Could not locate the LITELLM_UPSTREAM_SHA constant to update.")
    return new_source


def run(
    *,
    mode: str,
    fetcher: Callable[[str], str] = _fetch_upstream,
    snapshot_path: Path = SNAPSHOT_PATH,
    upstream_url: str = LITELLM_HEAD_URL,
    sha_source: Path | None = None,
    head_sha: str | None = None,
) -> int:
    """Programmatic entry point. Returns the intended process exit code."""
    embedded_text = _load_snapshot(snapshot_path)
    embedded = _parse_json(embedded_text, "embedded snapshot")
    upstream_text = fetcher(upstream_url)
    upstream = _parse_json(upstream_text, "upstream snapshot")
    added, removed, changed = diff_catalogs(embedded, upstream)
    if not (added or removed or changed):
        print("Pricing snapshot is up-to-date with upstream — no drift detected.")
        return 0

    summary = _format_summary(added, removed, changed, embedded, upstream)
    print(summary)

    if mode == "write":
        snapshot_path.write_text(upstream_text, encoding="utf-8")
        print(f"Wrote refreshed snapshot to {snapshot_path}.")
        if head_sha:
            script_path = sha_source if sha_source is not None else Path(__file__)
            script_text = script_path.read_text("utf-8")
            updated = _replace_sha_constant(script_text, head_sha)
            script_path.write_text(updated, encoding="utf-8")
            print(f"Updated LITELLM_UPSTREAM_SHA to {head_sha}.")
        return 0

    # ``--check`` mode: non-zero exit indicates drift so the workflow opens a PR.
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Fail (exit 1) when the embedded snapshot drifts from upstream. "
        "Default mode used by the monthly cron workflow.",
    )
    group.add_argument(
        "--write",
        action="store_true",
        help="Overwrite the embedded snapshot with the upstream payload.",
    )
    parser.add_argument(
        "--head-sha",
        default=None,
        help="Commit SHA to record in LITELLM_UPSTREAM_SHA when running with --write.",
    )
    args = parser.parse_args(argv)
    mode = "write" if args.write else "check"
    # Resolve module-level names here (not via parameter defaults) so that
    # tests can monkeypatch ``_fetch_upstream`` and ``SNAPSHOT_PATH`` on the
    # module and have ``main`` honor the replacements.
    try:
        return run(
            mode=mode,
            fetcher=_fetch_upstream,
            snapshot_path=SNAPSHOT_PATH,
            head_sha=args.head_sha,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
