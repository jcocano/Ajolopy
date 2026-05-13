"""Tests for OpenAIProvider.complete().

Covers the "complete()" acceptance group: basic round-trip, system passthrough,
tools, prompt caching no-op, parameter forwarding, error wrapping.
"""

import json

import httpx
import openai
import pytest

from ajolopy.providers import Message, Tool
from ajolopy.providers.openai import OpenAIProvider, OpenAIProviderError

from .conftest import make_async_client, make_chat_completion


@pytest.mark.asyncio
async def test_basic_complete_round_trip() -> None:
    client = make_async_client(create_return=make_chat_completion(text="hi there"))
    provider = OpenAIProvider(client=client)
    response = await provider.complete(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="hello")],
    )
    assert response.text == "hi there"
    assert response.tokens_in == 10
    assert response.tokens_out == 5
    assert response.finish_reason == "stop"
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_system_role_forwarded_as_chat_message() -> None:
    client = make_async_client()
    provider = OpenAIProvider(client=client)
    await provider.complete(
        model="gpt-4o-mini",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    messages = kwargs["messages"]
    # OpenAI keeps the system message inline as the first entry of `messages`.
    assert messages[0] == {"role": "system", "content": "You are concise."}
    assert messages[1] == {"role": "user", "content": "hi"}
    # No top-level `system` parameter — that is Anthropic's shape, not OpenAI's.
    assert "system" not in kwargs


@pytest.mark.asyncio
async def test_tools_converted_to_function_schema_and_tool_calls_surface() -> None:
    client = make_async_client(
        create_return=make_chat_completion(
            text="",
            finish_reason="tool_calls",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "lookup_order",
                    "arguments": json.dumps({"order_id": "X-9"}),
                }
            ],
        )
    )
    provider = OpenAIProvider(client=client)
    response = await provider.complete(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="find order X-9")],
        tools=[
            Tool(
                name="lookup_order",
                description="Look up an order by id",
                parameters={"type": "object", "properties": {"order_id": {"type": "string"}}},
            )
        ],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup_order",
                "description": "Look up an order by id",
                "parameters": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                },
            },
        }
    ]
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "lookup_order"
    assert response.tool_calls[0].arguments == {"order_id": "X-9"}


@pytest.mark.asyncio
async def test_temperature_and_max_tokens_forwarded() -> None:
    client = make_async_client()
    provider = OpenAIProvider(client=client)
    await provider.complete(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="hi")],
        temperature=0.2,
        max_tokens=64,
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 64


@pytest.mark.asyncio
async def test_max_tokens_not_forwarded_when_unset() -> None:
    # Unlike Anthropic, OpenAI does not require max_tokens; we must not
    # invent a default so callers can rely on the SDK's own behaviour.
    client = make_async_client()
    provider = OpenAIProvider(client=client)
    await provider.complete(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="hi")],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in kwargs


@pytest.mark.asyncio
async def test_cache_true_is_no_op_no_extra_kwargs() -> None:
    # OpenAI caches automatically once the prompt crosses the SDK threshold,
    # so the provider must NOT leak any extra cache-related kwarg into the
    # SDK call. The capability flag still reports True elsewhere.
    client = make_async_client()
    provider = OpenAIProvider(client=client)
    await provider.complete(
        model="gpt-4o-mini",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
        cache=True,
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    # No cache-related field, no annotation on system, no extra config.
    assert "cache" not in kwargs
    assert "cache_control" not in kwargs
    # System entry remains a plain dict, not an annotated block list.
    assert kwargs["messages"][0] == {"role": "system", "content": "You are concise."}


@pytest.mark.asyncio
async def test_retriable_sdk_error_surfaces_as_openai_provider_error() -> None:
    # APIConnectionError requires a request= arg; build a stub request.
    request = httpx.Request("POST", "https://example.invalid")
    client = make_async_client(create_side_effect=openai.APIConnectionError(request=request))
    provider = OpenAIProvider(client=client)
    with pytest.raises(OpenAIProviderError, match="OpenAI SDK error"):
        await provider.complete(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_tool_role_messages_become_tool_entries() -> None:
    client = make_async_client()
    provider = OpenAIProvider(client=client)
    await provider.complete(
        model="gpt-4o-mini",
        messages=[
            Message(role="user", content="find order X-9"),
            Message(
                role="tool",
                content='{"status": "shipped"}',
                tool_call_id="call_1",
            ),
        ],
    )
    chat_messages = client.chat.completions.create.call_args.kwargs["messages"]
    tool_message = chat_messages[-1]
    # OpenAI's tool-result shape: role=tool, tool_call_id, content.
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["content"] == '{"status": "shipped"}'
