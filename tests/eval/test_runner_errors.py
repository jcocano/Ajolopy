"""Error-path tests for :class:`EvalRunner`.

The runner must isolate per-case failures so the suite keeps producing
a usable :class:`EvalRun`. Whole-run failures (empty dataset, missing
metadata) raise out of :meth:`run` so the caller learns about them.
"""

from pathlib import Path

import pytest

from ajolopy import Agent, Eval, Metric
from ajolopy.eval import EvalRunner
from ajolopy.eval.errors import EvalRunError
from ajolopy.providers import LLMProviderError, Response


@pytest.mark.asyncio
async def test_target_failure_isolates_case(
    scripted_fake: type, fixtures_dir: Path, tmp_path: Path
) -> None:
    """A failing target call captures into ``case.error`` and continues."""
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    # Toggle: fail case 0, succeed case 1 and 2.
    call_count = {"n": 0}

    async def faulty_complete(**_kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx == 0:
            raise LLMProviderError("simulated provider down")
        return Response(text="ok", tokens_in=1, tokens_out=1, finish_reason="stop")

    provider.complete = faulty_complete

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    run = await EvalRunner().run(_Suite)
    failed_cases = [c for c in run.cases if c.error is not None]
    assert len(failed_cases) >= 1
    # The failing case's metric score is 0.0 and it's marked not-passed.
    assert any(case.metric_scores["m"] == 0.0 and not case.passed for case in failed_cases)
    # The other two cases ran to completion.
    successful = [c for c in run.cases if c.error is None]
    assert len(successful) == 2
    assert all(c.passed for c in successful)


@pytest.mark.asyncio
async def test_metric_exception_captured_per_metric(
    scripted_fake: type, fixtures_dir: Path
) -> None:
    """A metric raising fails only itself for that case; other metrics still run."""
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def good(self, output, expected) -> float:
            return 1.0

        @Metric
        def bad(self, output, expected) -> float:
            raise RuntimeError("boom")

    run = await EvalRunner().run(_Suite)
    assert run.metrics["good"].aggregate == pytest.approx(1.0)
    assert run.metrics["bad"].aggregate == pytest.approx(0.0)
    # Every case carries a non-None error mentioning the metric name.
    for case in run.cases:
        assert case.error is not None
        assert "bad" in case.error
        assert case.metric_scores["good"] == pytest.approx(1.0)
        assert case.metric_scores["bad"] == pytest.approx(0.0)
        assert not case.passed


@pytest.mark.asyncio
async def test_non_numeric_metric_return_is_captured(
    scripted_fake: type, fixtures_dir: Path
) -> None:
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    provider = Support._agent_runtime._models[0][1]  # type: ignore[attr-defined]
    provider.responses = [
        Response(text="r", tokens_in=1, tokens_out=1, finish_reason="stop") for _ in range(3)
    ]

    @Eval(agent=Support, dataset=str(fixtures_dir / "support.jsonl"))
    class _Suite:
        @Metric
        def stringy(self, output, expected) -> float:
            return "not a number"  # type: ignore[return-value]

    run = await EvalRunner().run(_Suite)
    assert run.metrics["stringy"].aggregate == pytest.approx(0.0)
    for case in run.cases:
        assert case.error is not None
        assert "stringy" in case.error


@pytest.mark.asyncio
async def test_empty_dataset_raises(scripted_fake: type, tmp_path: Path) -> None:
    """An empty (no-cases) dataset is refused with ``EvalRunError``."""
    # The JSONLDataset constructor already raises on empty files, so we
    # build a custom in-memory dataset to exercise the runner's guard.
    _ = scripted_fake

    @Agent(model="claude-opus-4-7", system="…")
    class Support:
        pass

    from typing import override

    from ajolopy.eval import Case, Dataset

    class EmptyDataset(Dataset):
        @override
        def __iter__(self):
            return iter([])

        @override
        async def __aiter__(self):
            return
            yield Case(input={}, expected={})  # type: ignore[unreachable]

    @Eval(agent=Support, dataset=EmptyDataset())
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    with pytest.raises(EvalRunError, match="no cases"):
        await EvalRunner().run(_Suite)


@pytest.mark.asyncio
async def test_run_on_undecorated_class_raises() -> None:
    """Calling ``run`` on a plain class raises ``EvalRunError``."""

    class NotASuite:
        pass

    with pytest.raises(EvalRunError, match="not an @Eval"):
        await EvalRunner().run(NotASuite)
