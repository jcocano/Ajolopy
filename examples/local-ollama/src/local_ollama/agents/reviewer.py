"""The ``CodeReviewer`` agent — privacy-first Python reviewer over a local Ollama.

One ``@Agent`` + one ``@Tool`` + one ``@Stream``, matching the killer-demo
shape from
[`docs/tutorial/step-1-hello.md`](../../../../docs/tutorial/step-1-hello.md).
The only deviation from AJ-50's ``Support`` agent is the model string:
the ``ollama:`` prefix routes through the framework's universal
OpenAI-compatible provider so the demo runs entirely on the user's
laptop. No cloud account, no API key.

Drift notes:

- ``@Agent`` has no ``trace=`` kwarg in v0.1; OTel instrumentation is
  always-on and cheap when no SDK is installed.
- No ``fallback=`` here: a single-laptop Ollama daemon has nothing to
  fall back to. The README documents adding a hosted fallback
  (``fallback="groq:llama-3.3-70b-versatile"``) when the example moves
  to production.
- ``lint_function`` uses ``ast.parse`` only — no third-party imports —
  so the example's dependency footprint stays at ``ajolopy`` plus
  ``pydantic``.
"""

import ast
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel

from ajolopy import Agent, Stream, Tool
from ajolopy.http import Body

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class ReviewRequest(BaseModel):
    """Payload accepted by the ``/chat`` endpoint."""

    code: str


@Agent(
    model="ollama:llama3.3",
    system=(
        "You review Python code. Be concise and concrete. "
        "First call the lint_function tool with the user's code; if it "
        "reports a syntax error, quote the error verbatim and stop. "
        "Otherwise give two or three specific, actionable suggestions "
        "(naming, types, idioms, bugs). No preamble, no closing pleasantry."
    ),
)
class CodeReviewer:
    """Local code reviewer running on Ollama via the universal provider."""

    @Tool
    async def lint_function(self, code: str) -> dict[str, str | bool]:
        """Parse ``code`` and report whether it is syntactically valid Python.

        Returns ``{"ok": True, "error": ""}`` when the snippet parses
        cleanly and ``{"ok": False, "error": "<message>"}`` when
        :func:`ast.parse` raises :class:`SyntaxError`. Pure stdlib — no
        subprocess, no network, no third-party linter.

        The agent should call this once per request before reviewing,
        so a broken snippet is flagged early without spending tokens.
        """
        try:
            ast.parse(code)
        except SyntaxError as exc:
            # ``exc.msg`` carries the human-readable Python diagnostic
            # ("unexpected EOF while parsing", etc.). ``exc.lineno`` is
            # 1-indexed and may be ``None`` for top-of-file errors; the
            # ``or 0`` keeps the return shape stable for the model.
            return {
                "ok": False,
                "error": f"{exc.msg} (line {exc.lineno or 0})",
            }
        return {"ok": True, "error": ""}

    @Stream("/chat")
    async def respond(self, body: Annotated[ReviewRequest, Body()]) -> AsyncGenerator[str]:
        """Stream a code-review reply for ``body.code`` over SSE."""
        # ``self.stream`` is injected by ``@Agent`` at decoration time;
        # static analysers cannot see the attribute, so we silence the
        # missing-attribute warning here. Same pattern as the framework's
        # own composability tests and the AJ-50 example.
        async for chunk in self.stream(body.code):  # type: ignore[attr-defined]
            yield chunk
