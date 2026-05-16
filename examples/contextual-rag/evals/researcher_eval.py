"""Regression suite for the contextual RAG ``ResearcherAgent``.

Three metrics, one LLM-as-judge and two deterministic:

- ``addresses_query`` — LLM-as-judge over the agent's answer. Penalises
  generic responses, refusals to use the retrieve tool, and
  hallucinated facts that are not present in the retrieved chunks.
- ``has_citations`` — deterministic (0 / 1). Passes when the answer
  contains at least one ``[path#section]`` reference. Forces the
  ``format_answer_with_citations`` tool to actually run.
- ``right_section`` — deterministic (0 / 1). Passes when the answer
  cites at least one of the ``expected_sections`` from the eval case.
  Forces the *correct* source to be cited, not just any source.

``ajolopy eval --ci`` discovers ``ResearcherEval`` automatically when
invoked from the ``examples/contextual-rag`` project root.
"""

import re
from typing import Any

from contextual_rag.agents.researcher import ResearcherAgent

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge

# Match a citation of the form ``[<path>#<section>]`` where ``path`` is
# something path-shaped and ``section`` is non-empty. We also accept
# bare ``[<path>]`` references for the deterministic-citations check so
# that the metric does not over-fit to the formatter's exact output.
_CITATION_RE = re.compile(r"\[[^\[\]\s][^\[\]]*\]")


@Eval(
    agent=ResearcherAgent,
    dataset="evals/researcher.jsonl",
    threshold=0.65,
    concurrency=3,
)
class ResearcherEval:
    """Regression suite for the Tlaltipac handbook researcher."""

    @Metric
    async def addresses_query(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge: did the answer address the user's question?"""
        topic: str = str(expected.get("topic", "the user's question"))
        return await llm_judge(
            output.text,
            criterion=(
                f"The user asked about '{topic}'. The answer must address "
                "the question directly using information from the Tlaltipac "
                "handbook. Penalise generic answers, hallucinated facts, "
                "refusals to call the `retrieve_with_context` tool, and "
                "answers that ignore the retrieved chunks. The answer should "
                "be concise (one or two short paragraphs)."
            ),
            model="claude-opus-4-7",
            cache=True,
        )

    @Metric(aggregator="mean", pass_threshold=1.0)
    def has_citations(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic: the answer contains at least one citation."""
        del expected  # uniform metric signature; not used by this metric
        return 1.0 if _CITATION_RE.search(output.text) is not None else 0.0

    @Metric(aggregator="mean", pass_threshold=0.5)
    def right_section(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic: the answer cites at least one expected section."""
        sections: list[str] = list(expected.get("expected_sections", []))
        if not sections:
            return 1.0
        text = output.text.lower()
        return 1.0 if any(section.lower() in text for section in sections) else 0.0
