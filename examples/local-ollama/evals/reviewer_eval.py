"""Regression suite for the ``CodeReviewer`` agent.

Two metrics, mirroring the AJ-50 + AJ-54 pattern but keeping the
example fully local:

- ``identifies_issue`` — LLM-as-judge over the agent's answer using
  :func:`ajolopy.eval.metrics.llm_judge`. The judge is the same local
  Ollama model, so the eval also runs offline. The criterion encodes
  "answer correctly identifies the seeded issue".
- ``response_within_budget`` — deterministic per-case scorer. Passes
  when the response is non-empty and shorter than ~500 tokens (word
  count is the cheap proxy that ships with stdlib only).

``ajolopy eval --ci`` discovers ``ReviewerEval`` automatically when
invoked from the ``examples/local-ollama`` project root. The README
notes the suite requires a running Ollama server with ``llama3.3``
pulled, same as the agent itself.
"""

from typing import Any

from local_ollama.agents.reviewer import CodeReviewer

from ajolopy.eval import Eval, Metric
from ajolopy.eval.metrics import llm_judge

# Word-count budget used by ``response_within_budget``. Tokens vary by
# tokenizer; word count is the framework-agnostic proxy that keeps the
# metric deterministic across providers (Ollama, OpenAI, Anthropic).
_RESPONSE_BUDGET_WORDS: int = 500


@Eval(
    agent=CodeReviewer,
    dataset="evals/reviewer.jsonl",
    threshold=0.6,
    concurrency=2,
)
class ReviewerEval:
    """Regression suite for the local code reviewer."""

    @Metric
    async def identifies_issue(self, output: Any, expected: dict[str, Any]) -> float:
        """LLM-as-judge: did the answer identify the seeded issue?"""
        issue: str = str(expected.get("issue", "the seeded issue"))
        return await llm_judge(
            output.text,
            criterion=(
                f"The user submitted a Python snippet with a known issue: '{issue}'. "
                "The reviewer's response must identify this exact issue and explain "
                "how to fix it. Penalise generic feedback, off-topic suggestions, "
                "and answers that miss the specific issue. Penalise refusals to "
                "review or to call the lint_function tool when relevant."
            ),
            model="ollama:llama3.3",
            cache=True,
        )

    @Metric(aggregator="mean", pass_threshold=0.8)
    def response_within_budget(self, output: Any, expected: dict[str, Any]) -> float:
        """Deterministic: response is non-empty and under the word budget."""
        # ``expected`` is consumed by the judge metric above; this metric
        # only inspects ``output.text``. The argument stays on the
        # signature so every metric on the suite has a uniform shape.
        del expected
        text: str = output.text
        if not text.strip():
            return 0.0
        return 1.0 if len(text.split()) < _RESPONSE_BUDGET_WORDS else 0.0
