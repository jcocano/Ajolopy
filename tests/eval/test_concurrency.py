"""Concurrency tests for :class:`EvalRunner`.

Two invariants are non-negotiable:

- ``concurrency=N`` caps the number of in-flight cases at any moment.
  We assert this with a custom :class:`Dataset` whose target sleeps
  long enough that the wall-clock duration tells us how many waves
  ran.
- Final case ordering matches the dataset regardless of execution
  order — workers may finish out of order but the result tuple is
  sorted by ``case_index``.
"""

import asyncio
import time
from typing import override

import pytest

from ajolopy import Agent, Eval, Metric
from ajolopy.eval import Case, Dataset, EvalRunner
from ajolopy.providers import Message, Response, Tool, register_provider
from tests.agent.conftest import FakeProvider

CASE_SLEEP_S = 0.05


class SlowProvider(FakeProvider):
    """FakeProvider that sleeps before answering so we can time waves."""

    @override
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        await asyncio.sleep(CASE_SLEEP_S)
        return Response(text=messages[-1].content, tokens_in=1, tokens_out=1, finish_reason="stop")


class _SixCaseDataset(Dataset):
    """In-memory dataset that yields six cases with predictable indexes."""

    @override
    def __iter__(self):
        for i in range(6):
            yield Case(input={"message": f"msg{i}"}, expected={"i": i})

    @override
    async def __aiter__(self):
        for i in range(6):
            yield Case(input={"message": f"msg{i}"}, expected={"i": i})


@pytest.fixture
def slow_provider() -> type[SlowProvider]:
    register_provider("anthropic", SlowProvider, overwrite=True)
    return SlowProvider


@pytest.mark.asyncio
async def test_concurrency_cap_limits_in_flight_cases(
    slow_provider: type[SlowProvider],
) -> None:
    """6 cases with concurrency=2 take ~3 waves of CASE_SLEEP_S each."""
    _ = slow_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Slow:
        pass

    @Eval(agent=Slow, dataset=_SixCaseDataset(), concurrency=2)
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    start = time.perf_counter()
    run = await EvalRunner().run(_Suite)
    elapsed = time.perf_counter() - start
    # Three waves of 0.05s each = 0.15s baseline. Allow a generous
    # tolerance band: at least 2 waves (caps in flight) but no more
    # than 1 case-time of overhead.
    assert elapsed >= 2 * CASE_SLEEP_S
    assert elapsed < 6 * CASE_SLEEP_S  # full serial would be 6 waves
    assert len(run.cases) == 6


@pytest.mark.asyncio
async def test_case_ordering_preserved_under_concurrency(
    slow_provider: type[SlowProvider],
) -> None:
    _ = slow_provider

    @Agent(model="claude-opus-4-7", system="…")
    class Slow:
        pass

    @Eval(agent=Slow, dataset=_SixCaseDataset(), concurrency=3)
    class _Suite:
        @Metric
        def m(self, output, expected) -> float:
            return 1.0

    run = await EvalRunner().run(_Suite)
    assert [c.case_index for c in run.cases] == [0, 1, 2, 3, 4, 5]
    # The case.expected payload carries the dataset index so we can
    # cross-check ordering survives concurrent execution.
    assert [c.expected["i"] for c in run.cases] == [0, 1, 2, 3, 4, 5]
