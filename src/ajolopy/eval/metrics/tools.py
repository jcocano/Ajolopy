"""Tool-dispatch helper: ``tool_called``.

Reads :attr:`~ajolopy.eval.results.EvalOutput.tool_calls` — the
runner-captured list of tools the agent dispatched during the case.
"""

from typing import TYPE_CHECKING, Literal

from ._resolve import require_eval_output

if TYPE_CHECKING:
    from collections.abc import Sequence


def tool_called(
    output: object,
    tool_name: str | Sequence[str] | None,
    *,
    mode: Literal["any", "all"] = "any",
) -> float:
    """Return ``1.0`` if the agent invoked the expected tool(s).

    - ``output`` MUST be an :class:`~ajolopy.eval.results.EvalOutput`;
      a plain string raises :class:`MetricsConfigError` because there
      is no tool-call list to read.
    - ``tool_name=None`` → ``1.0`` iff NO tools were dispatched.
    - ``tool_name=str`` → ``1.0`` iff the named tool appears in
      ``output.tool_calls``.
    - ``tool_name=Sequence[str]`` → ``mode="any"`` (default) requires
      any-of; ``mode="all"`` requires every-of.
    """
    eval_output = require_eval_output(output, helper_name="tool_called")
    dispatched = eval_output.tool_calls
    if tool_name is None:
        return 1.0 if not dispatched else 0.0
    if isinstance(tool_name, str):
        return 1.0 if tool_name in dispatched else 0.0
    names = list(tool_name)
    if not names:
        # Empty sequence has the same semantics as ``None`` —
        # "expected no tool was called". Keep the symmetry tight.
        return 1.0 if not dispatched else 0.0
    if mode == "all":
        return 1.0 if all(name in dispatched for name in names) else 0.0
    return 1.0 if any(name in dispatched for name in names) else 0.0


__all__ = ["tool_called"]
