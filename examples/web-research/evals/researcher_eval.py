"""Regression suite for the :class:`~web_research.agents.researcher.Researcher`.

Two metrics, matching the AJ-50 / AJ-54 example pattern:

- ``cites_sources`` — LLM-as-judge over the agent's answer using
  :func:`ajolopy.eval.metrics.llm_judge`. The criterion encodes
  "answer cites concrete web sources by URL".
- ``contains_url`` — deterministic per-case scorer (0.0 / 1.0). Pass
  when the answer text contains at least one ``http://`` or
  ``https://`` URL.

``ajolopy eval --ci`` discovers ``ResearcherEval`` automatically when
invoked from the ``examples/web-research`` project root.
"""

import re
from typing import Any

from web_research.agents.researcher import Researcher

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge

# URL regex used by ``contains_url`` — module-level so the compiled
# pattern is shared across cases. Matches ``http://`` or ``https://``
# followed by at least one non-whitespace character.
_URL_RE = re.compile(r"https?://\S+")


@Eval(
    agent=Researcher,
    dataset="evals/researcher.jsonl",
    threshold=0.8,
    concurrency=3,
)
class ResearcherEval:
    """Regression suite for the web research agent."""

    @Metric
    async def cites_sources(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge: did the answer cite concrete web sources?"""
        topic: str = str(expected.get("topic", "the user's question"))
        return await llm_judge(
            output.text,
            criterion=(
                f"The user's question is about '{topic}'. The answer must "
                "address it directly AND cite at least one concrete web "
                "source by URL (an http(s):// link). Penalise generic "
                "answers, off-topic answers, refusals to use the "
                "search_web tool, and hallucinated facts that do not "
                "appear in any cited source."
            ),
            model="claude-opus-4-7",
            cache=True,
        )

    @Metric(aggregator="mean", pass_threshold=0.5)
    def contains_url(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic: the answer contains at least one http(s):// URL."""
        # ``expected`` is read by the judge metric above; the deterministic
        # check only needs the answer text. The argument stays unused on
        # this metric so the suite-level signature stays uniform across
        # every metric.
        del expected
        return 1.0 if _URL_RE.search(output.text) else 0.0
