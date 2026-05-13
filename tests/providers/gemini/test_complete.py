"""Tests for GeminiProvider.complete().

Covers the "complete()" acceptance group: basic round-trip, system
extraction, tool conversion, parameter forwarding, error wrapping, and
the up-front validation checks that surface Gemini-specific quirks as
typed framework errors.
"""

import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from ajolopy.providers import Message, Tool
from ajolopy.providers.gemini import GeminiProvider, GeminiProviderError

from .conftest import make_async_client, make_generate_response


@pytest.mark.asyncio
async def test_basic_complete_round_trip() -> None:
    client = make_async_client(generate_return=make_generate_response(text="hi there"))
    provider = GeminiProvider(client=client)
    response = await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="hello")],
    )
    assert response.text == "hi there"
    assert response.tokens_in == 10
    assert response.tokens_out == 5
    assert response.finish_reason == "stop"
    client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_system_role_routed_to_system_instruction() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
    )
    kwargs = client.aio.models.generate_content.call_args.kwargs
    config = kwargs["config"]
    assert isinstance(config, genai_types.GenerateContentConfig)
    assert config.system_instruction == "You are concise."
    # User message stays in contents; no system entry leaks in.
    contents = kwargs["contents"]
    assert len(contents) == 1
    assert contents[0].role == "user"


@pytest.mark.asyncio
async def test_multiple_system_messages_joined_with_double_newline() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="system", content="Reply in English."),
            Message(role="user", content="hi"),
        ],
    )
    config = client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.system_instruction == "You are concise.\n\nReply in English."


@pytest.mark.asyncio
async def test_role_mapping_user_assistant_tool() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="user", content="find order X-9"),
            Message(role="assistant", content="On it."),
            Message(
                role="tool",
                content='{"status": "shipped"}',
                tool_call_id="tool_1",
                name="lookup_order",
            ),
        ],
    )
    contents = client.aio.models.generate_content.call_args.kwargs["contents"]
    # user → user (text part)
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "find order X-9"
    # assistant → model (text part)
    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "On it."
    # tool → user with function_response part
    assert contents[2].role == "user"
    fr = contents[2].parts[0].function_response
    assert fr is not None
    assert fr.id == "tool_1"
    assert fr.name == "lookup_order"
    assert fr.response == {"content": '{"status": "shipped"}'}


@pytest.mark.asyncio
async def test_tools_converted_to_function_declarations_and_tool_calls_surface() -> None:
    client = make_async_client(
        generate_return=make_generate_response(
            text="",
            function_calls=[
                {
                    "id": "call_1",
                    "name": "lookup_order",
                    "args": {"order_id": "X-9"},
                }
            ],
        )
    )
    provider = GeminiProvider(client=client)
    response = await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="find order X-9")],
        tools=[
            Tool(
                name="lookup_order",
                description="Look up an order by id",
                parameters={"type": "object", "properties": {"order_id": {"type": "string"}}},
            )
        ],
    )
    config = client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.tools is not None
    sdk_tool = config.tools[0]
    assert sdk_tool.function_declarations is not None
    decl = sdk_tool.function_declarations[0]
    assert decl.name == "lookup_order"
    assert decl.description == "Look up an order by id"
    assert decl.parameters_json_schema == {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
    }
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "lookup_order"
    assert response.tool_calls[0].arguments == {"order_id": "X-9"}


@pytest.mark.asyncio
async def test_temperature_and_max_tokens_forwarded() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="hi")],
        temperature=0.2,
        max_tokens=64,
    )
    config = client.aio.models.generate_content.call_args.kwargs["config"]
    assert config.temperature == 0.2
    # Framework's max_tokens maps to Gemini's max_output_tokens.
    assert config.max_output_tokens == 64


@pytest.mark.asyncio
async def test_cache_true_produces_identical_sdk_call_shape() -> None:
    # Gemini's prompt caching uses a stateful cachedContent resource that
    # does not fit a stateless `cache: bool`; the flag is a documented
    # no-op so the SDK call shape must NOT differ between cache=True and
    # cache=False. The full lifecycle lives in AJ-58.
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
        cache=False,
    )
    kwargs_off = client.aio.models.generate_content.call_args.kwargs

    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
        cache=True,
    )
    kwargs_on = client.aio.models.generate_content.call_args.kwargs

    # Compare model + contents.role/parts shape + config field values.
    assert kwargs_off["model"] == kwargs_on["model"]
    assert len(kwargs_off["contents"]) == len(kwargs_on["contents"])
    for left, right in zip(kwargs_off["contents"], kwargs_on["contents"], strict=True):
        assert left.role == right.role
        assert [p.text for p in left.parts] == [p.text for p in right.parts]
    config_off = kwargs_off["config"]
    config_on = kwargs_on["config"]
    assert config_off.system_instruction == config_on.system_instruction
    assert config_off.temperature == config_on.temperature
    assert config_off.max_output_tokens == config_on.max_output_tokens
    assert config_off.tools == config_on.tools


@pytest.mark.asyncio
async def test_retriable_sdk_error_surfaces_as_gemini_provider_error() -> None:
    # APIError requires (code, response_json). 503 is a typical retriable
    # 5xx ServerError; the framework wraps it under its typed error.
    sdk_exc = genai_errors.APIError(code=503, response_json={"error": {"message": "overloaded"}})
    client = make_async_client(generate_side_effect=sdk_exc)
    provider = GeminiProvider(client=client)
    with pytest.raises(GeminiProviderError, match="Gemini SDK error"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_complete_with_empty_messages_raises_before_sdk_call() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    with pytest.raises(GeminiProviderError, match="at least one user message"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[],
        )
    client.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_with_only_system_messages_raises_before_sdk_call() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    with pytest.raises(GeminiProviderError, match="at least one user/assistant/tool"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="system", content="You are concise.")],
        )
    client.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_consecutive_same_role_messages_pass_through_verbatim() -> None:
    # The provider must not auto-merge consecutive turns — that's the
    # caller's responsibility (and @Agent's in v0.1.x).
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="user", content="hello"),
            Message(role="user", content="follow-up"),
            Message(role="assistant", content="first reply"),
            Message(role="assistant", content="second reply"),
        ],
    )
    contents = client.aio.models.generate_content.call_args.kwargs["contents"]
    assert [c.role for c in contents] == ["user", "user", "model", "model"]
    assert [c.parts[0].text for c in contents] == [
        "hello",
        "follow-up",
        "first reply",
        "second reply",
    ]


@pytest.mark.asyncio
async def test_tool_message_with_is_error_flag_threads_through_response_payload() -> None:
    # Anthropic-style is_error semantics on a tool result must survive the
    # round-trip via Gemini's function_response.response dict, so the model
    # has a chance to recover.
    client = make_async_client()
    provider = GeminiProvider(client=client)
    await provider.complete(
        model="gemini-2.5-flash",
        messages=[
            Message(role="user", content="find order X-9"),
            Message(
                role="tool",
                content="upstream timeout",
                tool_call_id="tool_1",
                name="lookup_order",
                is_error=True,
            ),
        ],
    )
    contents = client.aio.models.generate_content.call_args.kwargs["contents"]
    fr = contents[-1].parts[0].function_response
    assert fr is not None
    assert fr.response == {"content": "upstream timeout", "is_error": True}


@pytest.mark.asyncio
async def test_finish_reason_enum_value_form_is_mapped() -> None:
    # Real SDK Pydantic responses expose finish_reason as a FinishReason
    # enum whose .value is the string; the converter must accept both
    # plain strings (mocks) and enum-like objects with .value.
    from types import SimpleNamespace

    raw = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text="ok", function_call=None)],
                    role="model",
                ),
                finish_reason=SimpleNamespace(value="STOP"),
                index=0,
            )
        ],
        usage_metadata=SimpleNamespace(prompt_token_count=1, response_token_count=1),
    )
    client = make_async_client(generate_return=raw)
    provider = GeminiProvider(client=client)
    response = await provider.complete(
        model="gemini-2.5-flash",
        messages=[Message(role="user", content="hi")],
    )
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_complete_logs_warning_on_safety_finish_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A non-streaming complete() that comes back with SAFETY/RECITATION must
    # surface finish_reason="error" AND log a warning naming the underlying
    # reason — same logging contract the streaming path uses.
    import logging as _logging

    client = make_async_client(
        generate_return=make_generate_response(text="partial", finish_reason="SAFETY"),
    )
    provider = GeminiProvider(client=client)
    with caplog.at_level(_logging.WARNING, logger="ajolopy.providers.gemini"):
        response = await provider.complete(
            model="gemini-2.5-flash",
            messages=[Message(role="user", content="risky")],
        )
    assert response.finish_reason == "error"
    assert any("SAFETY" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_tool_message_without_tool_call_id_raises_at_conversion_time() -> None:
    client = make_async_client()
    provider = GeminiProvider(client=client)
    with pytest.raises(GeminiProviderError, match="tool_call_id"):
        await provider.complete(
            model="gemini-2.5-flash",
            messages=[
                Message(role="user", content="find order X-9"),
                Message(role="tool", content='{"status": "shipped"}', name="lookup_order"),
            ],
        )
    client.aio.models.generate_content.assert_not_awaited()
