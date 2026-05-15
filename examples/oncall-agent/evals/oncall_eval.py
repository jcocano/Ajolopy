"""Regression suite for the on-call agent.

Two metrics, following the AJ-50 / AJ-54 pattern:

- ``identifies_severity`` — LLM-as-judge over the agent's answer
  using :func:`ajolopy.eval.metrics.llm_judge`. Scores whether the
  answer correctly identifies the severity (``low`` / ``medium`` /
  ``high``) implied by the request.
- ``mentions_reference`` — deterministic per-case scorer (0.0 / 1.0).
  Passes when the answer mentions at least one of the expected
  reference markers from the case's ``expected.must_contain_any``
  list. Acts as a cheap sanity check that the agent grounds its
  triage in concrete artifacts (service names, error codes, repo
  references), not pure prose.

``ajolopy eval --ci`` discovers ``OnCallEval`` automatically when
invoked from this project's root.
"""

from typing import Any

from oncall_agent.agents.oncall import OnCallAgent

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge


@Eval(
    agent=OnCallAgent,
    dataset="evals/oncall.jsonl",
    threshold=0.6,
    concurrency=3,
)
class OnCallEval:
    """Regression suite for the on-call agent."""

    @Metric
    async def identifies_severity(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge: did the answer label the right severity?"""
        severity: str = str(expected.get("severity", "unknown"))
        return await llm_judge(
            output.text,
            criterion=(
                "An on-call assistant has answered the user's request. "
                f"The correct severity for this request is '{severity}' "
                "(one of low / medium / high). The answer must clearly "
                "identify that severity and propose a concrete next "
                "step. Penalise generic responses, off-topic answers, "
                "severity mismatches, and refusals to triage."
            ),
            model="claude-sonnet-4-7",
            cache=True,
        )

    @Metric(aggregator="mean", pass_threshold=0.5)
    def mentions_reference(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic: the answer mentions one of the expected markers."""
        markers: list[str] = list(expected.get("must_contain_any", []))
        if not markers:
            return 1.0
        text = output.text.lower()
        return 1.0 if any(m.lower() in text for m in markers) else 0.0
