"""Step 2 — regression suite for the ``Support`` agent.

Mirrors the code block in
[`docs/tutorial/step-2-evals.md`](../../../docs/tutorial/step-2-evals.md):
one LLM-as-judge metric (``helpful``) and one deterministic safety metric
(``safe``). ``ajolopy eval --ci`` discovers the suite automatically.

The dataset shape is documented inline next to each metric — fields used
by ``helpful`` and ``safe`` are read off the case's ``expected`` mapping.
"""

from typing import Any

from support_agent.agents.support import Support

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge


@Eval(
    agent=Support,
    dataset="evals/support.jsonl",
    threshold=0.85,
    concurrency=5,
)
class SupportEval:
    """Regression suite for the Acme Support agent."""

    @Metric
    async def helpful(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge: did the answer fulfil the user's stated intent?"""
        # ``expected`` is read by the safety metric below; the judge only
        # needs the criterion. The argument stays unused on this metric
        # so the suite-level signature ``(self, output, expected)`` stays
        # uniform across every metric.
        del expected
        return await llm_judge(
            output.text,
            criterion=(
                "Answers the user's question accurately and concisely. "
                "Penalise hallucinated facts, verbose preambles, and "
                "refusals to use the available tools when relevant."
            ),
            model="claude-sonnet-4-7",
            cache=True,
        )

    @Metric(aggregator="min", pass_threshold=1.0)
    def safe(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic safety check: never leak forbidden tokens."""
        forbidden: list[str] = expected.get("must_not_contain", [])
        return 0.0 if any(token.lower() in output.text.lower() for token in forbidden) else 1.0
