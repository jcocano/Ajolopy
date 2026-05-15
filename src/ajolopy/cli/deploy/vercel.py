"""Deploy target: ``ajolopy deploy vercel``.

Generates the canonical ``vercel.json`` documented in Brief v4.0 §10
(vault doc ``07 - Deploy y Docker.md``) **after** prompting the user
with an interactive warning gate. The gate is the only place in the
v0.1 deploy surface where a target writes to ``stdout`` / reads from
``stdin`` inside :meth:`DeployTarget.prepare`; it is a documented
escape hatch from AJ-37's "targets are pure" invariant. See
``specs/vercel-deploy.md`` for the rationale.

The constructor accepts injectable ``stdin`` / ``stdout`` streams so
tests can drive the gate without touching the real process streams.
Production wiring uses the defaults (``sys.stdin`` / ``sys.stdout``);
the registry instantiates :class:`VercelTarget` with no arguments.
"""

import json
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, ClassVar

from .base import DeployContext, DeployResult
from .errors import DeployUserAbortError

if TYPE_CHECKING:
    from collections.abc import Iterable


_VERCEL_JSON_NAME = "vercel.json"

# Inputs that count as an affirmative answer to the warning gate.
# Anything else (including empty input) aborts.
_AFFIRMATIVE_RESPONSES = frozenset({"y", "yes"})

# The exact text shown to the user before the prompt. Kept as a module
# constant so the test suite can assert on the section markers without
# duplicating the entire body.
_WARNING_TEXT = (
    "Vercel for Python AI apps has serious limitations:\n"
    "  - Serverless function timeout: 300s max (Pro plan)\n"
    "  - No persistent in-process state (in-memory Memory backends fail)\n"
    "  - Cold starts can break long SSE streams\n"
    "\n"
    "If your app has:\n"
    "  - Workflows > 5 min          -> use Fly.io or Railway\n"
    "  - Persistent in-proc memory  -> use Fly.io or Railway\n"
    "  - Long streaming             -> use Fly.io or Railway\n"
    "\n"
    "Vercel works well for:\n"
    "  - Single-turn short agents\n"
    "  - Batch endpoints\n"
    "  - Non-streaming APIs\n"
    "\n"
    "Continue with Vercel? (y/N) "
)


class VercelTarget:
    """Render ``vercel.json`` after an interactive warning gate."""

    name: ClassVar[str] = "vercel"
    description: ClassVar[str] = (
        "Vercel — generates vercel.json after an interactive warning gate "
        "about Python AI limitations (use -y to skip)."
    )

    def __init__(
        self,
        *,
        stdin: IO[str] | None = None,
        stdout: IO[str] | None = None,
    ) -> None:
        """Capture the streams used by :meth:`prepare`'s warning gate.

        Both default to the real process streams. Tests inject
        :class:`io.StringIO` instances to exercise the gate hermetically.
        """
        self._stdin: IO[str] | None = stdin
        self._stdout: IO[str] | None = stdout

    def prepare(self, ctx: DeployContext) -> DeployResult:
        """Show the warning, ask for confirmation, then render the manifest."""
        if not ctx.yes:
            self._run_warning_gate()
        return DeployResult(files={Path(_VERCEL_JSON_NAME): _render_vercel_json()})

    def next_steps(self, ctx: DeployContext, result: DeployResult) -> Iterable[str]:
        """Yield the three ``vercel`` CLI commands the user runs next."""
        # ``ctx`` / ``result`` are part of the Protocol but unused here.
        del ctx, result
        return (
            "vercel login",
            "vercel link             # link to an existing project",
            "vercel deploy --prod    # production deploy",
        )

    # ------------------------------------------------------------------
    # Internal — warning gate plumbing.
    # ------------------------------------------------------------------

    def _run_warning_gate(self) -> None:
        """Print the warning, read one line, abort unless the user says yes."""
        stdout = self._stdout if self._stdout is not None else sys.stdout
        stdin = self._stdin if self._stdin is not None else sys.stdin
        self._print_warning(stdout)
        answer = stdin.readline().strip().lower()
        if answer not in _AFFIRMATIVE_RESPONSES:
            raise DeployUserAbortError(
                "ajolopy deploy: vercel cancelled by user.",
            )

    @staticmethod
    def _print_warning(stream: IO[str]) -> None:
        """Write the canonical warning text to ``stream`` and flush."""
        stream.write(_WARNING_TEXT)
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()


def _render_vercel_json() -> str:
    """Return the canonical ``vercel.json`` body with a trailing newline."""
    payload: dict[str, object] = {
        "version": 2,
        "builds": [{"src": "main.py", "use": "@vercel/python"}],
        "routes": [{"src": "/(.*)", "dest": "main.py"}],
    }
    return json.dumps(payload, indent=2) + "\n"


__all__ = ["VercelTarget"]
