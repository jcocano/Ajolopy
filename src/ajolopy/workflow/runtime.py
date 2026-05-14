"""``WorkflowRuntime`` — the run/stream engine behind ``@Workflow``.

One ``WorkflowRuntime`` is built per decorated class at decoration time
and bound to the class. Instance methods ``run`` / ``stream`` close over
the runtime so per-instance state stays at the class level.

The runtime owns two execution paths:

- **Coordinator loop** (default): a transient LLM call sequence where the
  coordinator model is presented with one synthetic ``delegate_to_<agent>``
  tool per registered agent. The runtime drives the function-calling
  loop, dispatches each ``delegate_to_*`` call to the matching agent's
  ``run()`` method, and stops when the coordinator emits a tool-free
  response. The last turn is speculatively streamed: text is buffered
  until the runtime knows the turn carries no tool_call, at which point
  the buffered deltas plus every subsequent delta are yielded as
  ``token`` events.

- **Override path**: when the decorated class declares
  ``async def route(self, message, context)``, that coroutine decides
  which agent handles the message. The runtime emits exactly one
  ``handoff`` -> ``agent_result`` -> ``done`` triple. ``max_steps`` is
  unused; no coordinator chat spans land in the trace.

Observability is unconditional. Every ``run`` / ``stream`` invocation
opens a ``workflow.invoke {WorkflowName}`` root span. Each coordinator
turn gets a ``chat {coordinator_model}`` child span via the workflow's
own helpers (mirroring :class:`ajolopy.agent.runtime.AgentRuntime` but
without reusing its tool-loop plumbing — the coordinator's tool calls
target synthetic delegations, not real ``@Tool`` bindings). Each
delegation is executed through the delegated agent's own
``AgentRuntime``, so its ``agent.invoke`` span nests naturally under the
workflow root and its chat costs feed the workflow's cost roll-up via
the private ``cost_sink`` kwarg.
"""

import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import Span, Status, StatusCode

from ajolopy.agent.errors import AgentError
from ajolopy.agent.runtime import AgentRuntime
from ajolopy.observability import (
    AJOLOPY_STREAMING,
    AJOLOPY_WORKFLOW_COORDINATOR_MODEL,
    AJOLOPY_WORKFLOW_HANDOFF_COUNT,
    AJOLOPY_WORKFLOW_HANDOFF_FROM,
    AJOLOPY_WORKFLOW_HANDOFF_TO,
    AJOLOPY_WORKFLOW_MAX_STEPS,
    AJOLOPY_WORKFLOW_NAME,
    AJOLOPY_WORKFLOW_OPERATION,
    AJOLOPY_WORKFLOW_STEP_COUNT,
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_CHAT,
    Catalog,
    chat_span_name,
    get_tracer,
    workflow_invoke_span_name,
)
from ajolopy.observability.pricing import get_active_catalog
from ajolopy.observability.pricing_emit import set_chat_cost_attrs, set_root_cost_total
from ajolopy.providers import (
    ChunkUsage,
    LLMProvider,
    LLMProviderError,
    Message,
    ProviderNotRegisteredError,
    Tool,
    ToolCall,
    UnknownModelError,
    get_provider_class,
    resolve_provider,
)

from .errors import WorkflowConfigError, WorkflowMaxStepsError, WorkflowRouteError
from .events import (
    WorkflowEvent,
    make_agent_result,
    make_done,
    make_handoff,
    make_token,
)

_TRACER = get_tracer("ajolopy.workflow")

_COORDINATOR_SYSTEM_PROMPT = (
    "You are a coordinator. Delegate the user's request to one of the "
    "specialist agents using the provided tools. After agents respond, "
    "write a final answer to the user in plain text."
)

_DELEGATE_TOOL_PREFIX = "delegate_to_"
_DELEGATE_MESSAGE_PARAM = "message"
_DELEGATE_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        _DELEGATE_MESSAGE_PARAM: {
            "type": "string",
            "description": "The message to forward to the delegated agent.",
        }
    },
    "required": [_DELEGATE_MESSAGE_PARAM],
}


def _delegate_tool_name(agent_cls: type[Any]) -> str:
    """Return the synthetic tool name for ``agent_cls``."""
    return f"{_DELEGATE_TOOL_PREFIX}{agent_cls.__name__.lower()}"


def _delegate_tool_description(agent_cls: type[Any]) -> str:
    """Return the synthetic tool description for ``agent_cls``.

    Uses the agent class's docstring stripped of indentation, or falls
    back to a default ``Delegate to the {Name} agent.`` when the class
    has no docstring.
    """
    doc = inspect.getdoc(agent_cls)
    if doc:
        for line in doc.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return f"Delegate to the {agent_cls.__name__} agent."


def is_agent_class(cls: object) -> bool:
    """``True`` when ``cls`` was decorated with :func:`ajolopy.Agent`.

    The agent decorator binds an ``_agent_runtime`` attribute on the
    class itself; checking for it (and that it is an :class:`AgentRuntime`
    instance) is the cheapest way to validate without importing the
    decorator module and risking a circular dependency. Public so the
    workflow decorator can validate ``agents=`` without reaching across
    the package boundary into a private helper.
    """
    if not isinstance(cls, type):
        return False
    runtime = getattr(cls, "_agent_runtime", None)
    return isinstance(runtime, AgentRuntime)


_RouteCallable = Callable[..., Awaitable[type[Any]]]


class WorkflowRuntime:
    """Encapsulates run/stream/tracing for one decorated workflow class."""

    def __init__(
        self,
        *,
        workflow_cls: type[Any],
        agents: list[type[Any]],
        coordinator: str | None,
        max_steps: int,
        route_override: _RouteCallable | None,
        catalog: Catalog | None = None,
    ) -> None:
        self._workflow_cls = workflow_cls
        self._workflow_name = workflow_cls.__name__
        self._agents: list[type[Any]] = list(agents)
        self._agents_by_tool_name: dict[str, type[Any]] = {
            _delegate_tool_name(cls): cls for cls in agents
        }
        self._coordinator_model = coordinator
        self._max_steps = max_steps
        self._route_override = route_override
        self._catalog = catalog

        # Pre-build the synthetic tool list. Order mirrors ``agents=`` so the
        # coordinator always sees a stable tool list across invocations.
        self._wire_tools: list[Tool] = [
            Tool(
                name=_delegate_tool_name(cls),
                description=_delegate_tool_description(cls),
                parameters=dict(_DELEGATE_PARAMETERS_SCHEMA),
            )
            for cls in agents
        ]

        # Resolve the coordinator's provider once at construction time so
        # misconfigurations surface at decoration time, not at first call.
        if coordinator is not None and route_override is None:
            self._coordinator_provider = self._instantiate_coordinator_provider(coordinator)
        else:
            self._coordinator_provider = None

    # ------------------------------------------------------------------
    # provider resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _instantiate_coordinator_provider(model: str) -> LLMProvider:
        """Resolve and instantiate the provider for ``coordinator=model``.

        Surfaces both unknown-model and provider-instantiation failures as
        :class:`WorkflowConfigError` so they fail the decorator, not the
        first request.
        """
        try:
            key = resolve_provider(model)
        except UnknownModelError as exc:
            raise WorkflowConfigError(
                f"Unknown coordinator model {model!r}: {exc}. Check the "
                f"registered provider prefixes or call register_route()."
            ) from exc
        try:
            cls = get_provider_class(key)
        except ProviderNotRegisteredError as exc:
            raise WorkflowConfigError(
                f"Provider {key!r} is registered as a routing target but no "
                f"concrete LLMProvider class is bound. Import the corresponding "
                f"ajolopy.providers.* package."
            ) from exc
        try:
            return cls()
        except Exception as exc:
            raise WorkflowConfigError(f"Failed to instantiate provider {key!r}: {exc}") from exc

    def _resolve_catalog(self) -> Catalog:
        if self._catalog is not None:
            return self._catalog
        return get_active_catalog()

    # ------------------------------------------------------------------
    # public methods called by the decorator-injected instance methods
    # ------------------------------------------------------------------

    async def run(self, workflow_instance: Any, message: str, **context: Any) -> str:
        """Drive the orchestration to completion and return the final text."""
        # ``run`` is a thin wrapper around ``stream``: consume the event
        # stream internally and return the terminal ``done.text``. That
        # keeps the two code paths byte-identical from the provider's
        # point of view (mocked providers see exactly one call sequence).
        final_text = ""
        async for event in self._iterate("run", workflow_instance, message, context):
            if event["type"] == "done":
                final_text = event["text"]
        return final_text

    def stream(
        self, workflow_instance: Any, message: str, **context: Any
    ) -> AsyncIterator[WorkflowEvent]:
        """Yield workflow events in real time."""
        return self._iterate("stream", workflow_instance, message, context)

    # ------------------------------------------------------------------
    # core dispatch
    # ------------------------------------------------------------------

    async def _iterate(
        self,
        operation: str,
        workflow_instance: Any,
        message: str,
        context: dict[str, Any],
    ) -> AsyncIterator[WorkflowEvent]:
        """Open the workflow span and dispatch to the right execution path."""
        child_costs: list[float | None] = []
        counters: dict[str, int] = {"handoffs": 0, "steps": 0}
        with self._invoke_span(operation=operation) as invoke_span:
            try:
                if self._route_override is not None:
                    async for event in self._run_route_path(
                        workflow_instance=workflow_instance,
                        message=message,
                        context=context,
                        child_costs=child_costs,
                        counters=counters,
                    ):
                        yield event
                else:
                    async for event in self._run_coordinator_path(
                        message=message,
                        child_costs=child_costs,
                        counters=counters,
                    ):
                        yield event
            finally:
                # Record attributes whether the run completed or raised so
                # observability captures partial work alongside the failure.
                invoke_span.set_attribute(AJOLOPY_WORKFLOW_HANDOFF_COUNT, counters["handoffs"])
                invoke_span.set_attribute(AJOLOPY_WORKFLOW_STEP_COUNT, counters["steps"])
                set_root_cost_total(invoke_span, child_costs)

    # ------------------------------------------------------------------
    # route() override path
    # ------------------------------------------------------------------

    async def _run_route_path(
        self,
        *,
        workflow_instance: Any,
        message: str,
        context: dict[str, Any],
        child_costs: list[float | None],
        counters: dict[str, int],
    ) -> AsyncIterator[WorkflowEvent]:
        route = self._route_override
        if route is None:  # pragma: no cover - invariant guaranteed by _iterate
            raise WorkflowRouteError(
                f"Workflow {self._workflow_name!r} reached the route() path "
                f"without a registered override."
            )
        try:
            chosen = await route(workflow_instance, message, context)
        except WorkflowRouteError:
            # Already a workflow error - propagate verbatim.
            raise
        except Exception as exc:
            raise WorkflowRouteError(
                f"route() on {self._workflow_name!r} raised {type(exc).__name__}: {exc}"
            ) from exc

        if not is_agent_class(chosen):
            legal = sorted(cls.__name__ for cls in self._agents)
            raise WorkflowRouteError(
                f"route() on {self._workflow_name!r} returned {chosen!r}, which is "
                f"not an @Agent-decorated class. Legal agents: {legal!r}."
            )
        if chosen not in self._agents:
            legal = sorted(cls.__name__ for cls in self._agents)
            raise WorkflowRouteError(
                f"route() on {self._workflow_name!r} returned {chosen.__name__!r}, "
                f"which is not in agents=. Legal agents: {legal!r}."
            )

        counters["handoffs"] += 1
        yield make_handoff(agent=chosen.__name__, message=message)
        output = await self._delegate_to_agent(
            agent_cls=chosen,
            message=message,
            origin="route",
            child_costs=child_costs,
        )
        yield make_agent_result(agent=chosen.__name__, output=output)
        yield make_done(text=output)

    # ------------------------------------------------------------------
    # coordinator loop path
    # ------------------------------------------------------------------

    async def _run_coordinator_path(
        self,
        *,
        message: str,
        child_costs: list[float | None],
        counters: dict[str, int],
    ) -> AsyncIterator[WorkflowEvent]:
        provider = self._coordinator_provider
        model = self._coordinator_model
        if provider is None or model is None:  # pragma: no cover - invariant from decorator
            raise WorkflowConfigError(
                f"Workflow {self._workflow_name!r} reached the coordinator path "
                f"without a configured coordinator model."
            )
        prompt_messages: list[Message] = [
            Message(role="system", content=_COORDINATOR_SYSTEM_PROMPT),
            Message(role="user", content=message),
        ]

        for _step in range(self._max_steps):
            counters["steps"] += 1
            text_parts, tool_calls_this_turn, finish_reason = await self._coordinator_turn(
                provider=provider,
                model=model,
                prompt_messages=prompt_messages,
                child_costs=child_costs,
            )
            _ = finish_reason  # captured on the span; nothing else uses it here.

            if not tool_calls_this_turn:
                # Final turn: emit every text part as a ``token`` event
                # (speculatively buffered while we waited to see whether
                # this turn carried tool calls), then the terminal
                # ``done``.
                final_text = "".join(text_parts)
                for piece in text_parts:
                    if piece:
                        yield make_token(text=piece)
                yield make_done(text=final_text)
                return

            # Tool-call turn: append the assistant message + dispatch each
            # call sequentially, then push tool_results back as the next
            # conversational payload.
            prompt_messages.append(
                Message(
                    role="assistant",
                    content="".join(text_parts),
                    tool_calls=tool_calls_this_turn,
                )
            )
            for call in tool_calls_this_turn:
                agent_cls = self._agents_by_tool_name.get(call.name)
                if agent_cls is None:
                    # The coordinator emitted a tool name not in our
                    # synthetic list. Push back an error tool_result so it
                    # can recover; do not emit a handoff event because no
                    # real delegation happened.
                    prompt_messages.append(
                        Message(
                            role="tool",
                            content=(
                                f"Unknown tool {call.name!r}. Available: "
                                f"{sorted(self._agents_by_tool_name)}."
                            ),
                            tool_call_id=call.id,
                            is_error=True,
                        )
                    )
                    continue
                forwarded_message = str(call.arguments.get(_DELEGATE_MESSAGE_PARAM, ""))
                counters["handoffs"] += 1
                yield make_handoff(agent=agent_cls.__name__, message=forwarded_message)
                try:
                    output = await self._delegate_to_agent(
                        agent_cls=agent_cls,
                        message=forwarded_message,
                        origin="coordinator",
                        child_costs=child_costs,
                    )
                    is_error = False
                except AgentError as exc:
                    output = f"{type(exc).__name__}: {exc}"
                    is_error = True
                yield make_agent_result(agent=agent_cls.__name__, output=output)
                prompt_messages.append(
                    Message(
                        role="tool",
                        content=output,
                        tool_call_id=call.id,
                        is_error=is_error,
                    )
                )

        # Loop exited without a tool-free coordinator response.
        raise WorkflowMaxStepsError(
            (
                f"Workflow {self._workflow_name!r} exceeded max_steps="
                f"{self._max_steps} without a tool-free coordinator response."
            ),
            max_steps=self._max_steps,
            step_count=self._max_steps,
        )

    async def _coordinator_turn(
        self,
        *,
        provider: LLMProvider,
        model: str,
        prompt_messages: list[Message],
        child_costs: list[float | None],
    ) -> tuple[list[str], list[ToolCall], str | None]:
        """Run one coordinator turn via ``provider.stream``.

        Returns ``(text_parts, tool_calls, finish_reason)``. Text parts are
        buffered (not yielded) because the caller decides whether to flush
        them as ``token`` events (tool-free final turn) or discard them
        (tool-calling intermediate turn). The chat span emits its own
        attributes plus the cost roll-up entry.
        """
        text_parts: list[str] = []
        tool_accum: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        terminal_usage: ChunkUsage | None = None

        with self._chat_span(provider=provider, model_str=model) as span:
            try:
                async for chunk in provider.stream(
                    model=model,
                    messages=prompt_messages,
                    tools=self._wire_tools,
                    temperature=None,
                    max_tokens=None,
                    cache=False,
                ):
                    if chunk.tool_call_delta is not None:
                        delta = chunk.tool_call_delta
                        key = delta.index if delta.index is not None else len(tool_accum)
                        entry = tool_accum.setdefault(key, {"id": "", "name": "", "args": ""})
                        if delta.id:
                            entry["id"] = delta.id
                        if delta.name:
                            entry["name"] = delta.name
                        if delta.arguments_delta:
                            entry["args"] += delta.arguments_delta
                    if chunk.delta:
                        text_parts.append(chunk.delta)
                    if chunk.finish_reason is not None:
                        finish_reason = chunk.finish_reason
                    if chunk.usage is not None:
                        terminal_usage = chunk.usage
            except LLMProviderError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            self._record_chat_response(
                span,
                finish_reasons=[finish_reason] if finish_reason else [],
                usage=terminal_usage,
            )
            cost = set_chat_cost_attrs(
                span,
                model=model,
                usage=terminal_usage,
                catalog=self._resolve_catalog(),
            )
            child_costs.append(cost)

        tool_calls = _assemble_tool_calls(tool_accum) if tool_accum else []
        # If the coordinator emitted any tool_call, the buffered text was
        # not a final answer; drop it so the caller does not flush it as
        # ``token`` events.
        if tool_calls:
            text_parts = []
        return text_parts, tool_calls, finish_reason

    async def _delegate_to_agent(
        self,
        *,
        agent_cls: type[Any],
        message: str,
        origin: str,
        child_costs: list[float | None],
    ) -> str:
        """Instantiate ``agent_cls`` and call its ``run()`` method.

        Opens a wrapper span named ``agent.invoke {AgentName}`` that
        carries the workflow's handoff breadcrumbs
        (:data:`AJOLOPY_WORKFLOW_HANDOFF_FROM` /
        :data:`AJOLOPY_WORKFLOW_HANDOFF_TO`). The agent's own runtime
        opens its own ``agent.invoke`` span as a nested child; the
        workflow trace therefore shows breadcrumbs on the same-named
        ancestor span and full agent telemetry on the nested span. The
        ``cost_sink`` parameter routes every chat-cost child of the
        delegated agent into the workflow's accumulator so the workflow
        root span aggregates them.
        """
        runtime: AgentRuntime = agent_cls._agent_runtime
        instance = agent_cls()
        with _TRACER.start_as_current_span(f"agent.invoke {agent_cls.__name__}") as wrapper_span:
            wrapper_span.set_attribute(AJOLOPY_WORKFLOW_HANDOFF_FROM, origin)
            wrapper_span.set_attribute(AJOLOPY_WORKFLOW_HANDOFF_TO, agent_cls.__name__)
            return await runtime.run(instance, message, cost_sink=child_costs)

    # ------------------------------------------------------------------
    # span helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _invoke_span(self, *, operation: str) -> Generator[Span]:
        with _TRACER.start_as_current_span(workflow_invoke_span_name(self._workflow_name)) as span:
            span.set_attribute(AJOLOPY_WORKFLOW_NAME, self._workflow_name)
            span.set_attribute(AJOLOPY_WORKFLOW_OPERATION, operation)
            span.set_attribute(AJOLOPY_STREAMING, operation == "stream")
            if self._coordinator_model is not None and self._route_override is None:
                span.set_attribute(AJOLOPY_WORKFLOW_COORDINATOR_MODEL, self._coordinator_model)
                span.set_attribute(AJOLOPY_WORKFLOW_MAX_STEPS, self._max_steps)
            yield span

    @contextmanager
    def _chat_span(
        self,
        *,
        provider: LLMProvider,
        model_str: str,
    ) -> Generator[Span]:
        with _TRACER.start_as_current_span(chat_span_name(model_str)) as span:
            span.set_attribute(GEN_AI_SYSTEM, provider.gen_ai_system_for(model_str))
            span.set_attribute(GEN_AI_OPERATION_NAME, OPERATION_CHAT)
            span.set_attribute(GEN_AI_REQUEST_MODEL, model_str)
            yield span

    @staticmethod
    def _record_chat_response(
        span: Span,
        *,
        finish_reasons: list[str | None],
        usage: ChunkUsage | None,
    ) -> None:
        reasons = [r for r in finish_reasons if r]
        if reasons:
            span.set_attribute(GEN_AI_RESPONSE_FINISH_REASONS, reasons)
        if usage is not None:
            if usage.input_tokens > 0:
                span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, usage.input_tokens)
            if usage.output_tokens > 0:
                span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, usage.output_tokens)


def _assemble_tool_calls(accum: dict[int, dict[str, Any]]) -> list[ToolCall]:
    """Materialise the streamed tool-call accumulator into ``ToolCall`` objects.

    Mirrors :meth:`ajolopy.agent.runtime.AgentRuntime._assemble_stream_tool_calls`
    but lives at module scope here because the workflow runtime does not
    reuse the agent runtime's instance methods.
    """
    calls: list[ToolCall] = []
    for key in sorted(accum.keys()):
        entry = accum[key]
        args_raw = entry.get("args") or "{}"
        args: dict[str, Any] = {}
        if args_raw:
            try:
                parsed: Any = json.loads(args_raw)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                args = {str(k): v for k, v in parsed.items()}  # type: ignore[misc]
        calls.append(
            ToolCall(
                id=entry.get("id") or f"call_{key}",
                name=entry.get("name") or "",
                arguments=args,
            )
        )
    return calls


__all__ = [
    "WorkflowRuntime",
]
