"""Regression suite for the docs bot's :class:`~docsbot.agents.docs.DocsAgent`.

Two metrics, mirroring the AJ-50 + AJ-48 pattern:

- ``addresses_intent`` — LLM-as-judge over the agent's answer using
  :func:`ajolopy.eval.metrics.llm_judge`. The criterion encodes
  "answer is grounded in the docs and addresses the question".
- ``cites_docs`` — deterministic per-case scorer (0.0 / 1.0). Pass when
  the answer mentions at least one of the expected doc paths from the
  case's ``expected.paths`` list.

``ajolopy eval --ci`` discovers ``DocsbotEval`` automatically when
invoked from the ``dogfood/docsbot`` project root.
"""

from typing import Any

from docsbot.agents.docs import DocsAgent

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge


@Eval(
    agent=DocsAgent,
    dataset="evals/docsbot.jsonl",
    threshold=0.6,
    concurrency=3,
)
class DocsbotEval:
    """Regression suite for the Ajolopy docs bot."""

    @Metric
    async def addresses_intent(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge: did the answer address the user's question?"""
        topic: str = str(expected.get("topic", "the user's question"))
        return await llm_judge(
            output.text,
            criterion=(
                f"The user's question is about '{topic}' in the Ajolopy framework. "
                "The answer must address it directly and ground its claims in the "
                "Ajolopy documentation. Penalise generic responses, off-topic "
                "answers, refusals to use the retrieve_docs tool, and hallucinated "
                "facts that are not present in the documentation."
            ),
            model="claude-opus-4-7",
            cache=True,
        )

    @Metric(aggregator="mean", pass_threshold=0.5)
    def cites_docs(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic: the answer mentions one of the expected doc paths."""
        paths: list[str] = list(expected.get("paths", []))
        if not paths:
            return 1.0
        text = output.text.lower()
        return 1.0 if any(path.lower() in text for path in paths) else 0.0
