"""Step 3 — workflow-level regression suite for the ``SupportTeam``.

Mirrors the code block in
[`docs/tutorial/step-3-team.md`](../../../docs/tutorial/step-3-team.md):
one LLM-as-judge metric (``addresses_intent``) and one deterministic
domain-marker metric (``mentions_domain``).

The honest scope for v0.1 workflow-level evals is to score the team's
final answer — routing-level introspection is a future enhancement
tracked under ``AJ-31`` and the deeper instrumentation it will land.
"""

from typing import Any

from support_agent.agents.team import SupportTeam

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge


@Eval(
    workflow=SupportTeam,
    dataset="evals/support_team.jsonl",
    threshold=0.85,
)
class TeamEval:
    """Workflow-level regression suite."""

    @Metric
    async def addresses_intent(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge over the team's final answer."""
        return await llm_judge(
            output.text,
            criterion=(
                f"The user's request is about {expected['domain']}. "
                "The answer must address it directly with concrete next steps. "
                "Penalise generic responses, off-topic answers, and refusals."
            ),
            model="claude-sonnet-4-7",
            cache=True,
        )

    @Metric(aggregator="min", pass_threshold=1.0)
    def mentions_domain(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic check: the answer name-checks the expected domain."""
        markers: list[str] = expected.get("must_contain_any", [])
        text = output.text.lower()
        return 1.0 if any(m.lower() in text for m in markers) else 0.0
