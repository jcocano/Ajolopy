"""Pre-push guard: refuse direct pushes to ``main``.

Two invocation paths are supported:

1. **Raw git pre-push hook** — git pipes ``<local_ref> <local_sha> <remote_ref>
   <remote_sha>`` lines to stdin. The guard rejects if any ``remote_ref`` is
   ``refs/heads/main``.
2. **pre-commit framework (pre-push stage)** — pre-commit also forwards stdin,
   *and* exports ``PRE_COMMIT_REMOTE_BRANCH``. We check the env var first so
   the guard works even if the wrapper consumes stdin before the entry runs.

Set ``ALLOW_DIRECT_MAIN_PUSH=1`` to bypass deliberately (emergency hotfix,
post-merge cleanup, repository surgery). ``--no-verify`` is forbidden by
project policy, so the env var is the only sanctioned escape hatch.

Wired in via the ``protect-main`` ``pre-push`` hook in
``.pre-commit-config.yaml``; activated by ``uv run pre-commit install``.
"""

import os
import sys
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Mapping

PROTECTED_REF = "refs/heads/main"
BYPASS_ENV = "ALLOW_DIRECT_MAIN_PUSH"
PRE_COMMIT_REMOTE_BRANCH = "PRE_COMMIT_REMOTE_BRANCH"


def _refusal_message() -> str:
    return (
        "\nrefuse: direct pushes to `main` are not allowed.\n"
        "Open a PR from a typed branch "
        "(`feature/<slug>`, `fix/<slug>`, `chore/<slug>`, ...).\n"
        f"Bypass deliberately: {BYPASS_ENV}=1 git push\n\n"
    )


def check(stdin: TextIO, env: Mapping[str, str] | None = None) -> int:
    """Return 0 if the push is allowed, 1 if any ref targets ``main``."""
    env = env if env is not None else os.environ

    if env.get(BYPASS_ENV) == "1":
        return 0

    # pre-commit framework path: rely on the exported env var.
    remote_branch = env.get(PRE_COMMIT_REMOTE_BRANCH)
    if remote_branch == PROTECTED_REF:
        sys.stderr.write(_refusal_message())
        return 1

    # Raw git pre-push path: parse stdin.
    for raw in stdin:
        parts = raw.strip().split()
        if len(parts) < 4:
            continue
        remote_ref = parts[2]
        if remote_ref == PROTECTED_REF:
            sys.stderr.write(_refusal_message())
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(check(sys.stdin))
