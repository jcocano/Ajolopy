"""Tests for AnthropicProvider.complete().

Covers the "complete()" acceptance group: basic round-trip, system
extraction, tools, prompt caching, parameter forwarding, error wrapping.
"""

import anthropic
import httpx
import pytest

from ajolopy.providers import Message, Tool
from ajolopy.providers.anthropic import AnthropicProvider, AnthropicProviderError

from .conftest import make_anthropic_message, make_async_client


@pytest.mark.asyncio
async def test_basic_complete_round_trip() -> None:
    client = make_async_client(create_return=make_anthropic_message(text="hi there"))
    provider = AnthropicProvider(client=client)
    response = await provider.complete(
        model="claude-opus-4-7",
        messages=[Message(role="user", content="hello")],
    )
    assert response.text == "hi there"
    assert response.tokens_in == 10
    assert response.tokens_out == 5
    assert response.finish_reason == "stop"
    client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_system_role_extracted_to_top_level_param() -> None:
    client = make_async_client()
    provider = AnthropicProvider(client=client)
    await provider.complete(
        model="claude-opus-4-7",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == "You are concise."
    # The user message stays in the messages list; the system one does not.
    assert all(m["role"] != "system" for m in kwargs["messages"])
    assert kwargs["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_tools_converted_to_anthropic_schema() -> None:
    client = make_async_client(
        create_return=make_anthropic_message(
            text="",
            stop_reason="tool_use",
            tool_uses=[
                {"id": "tool_1", "name": "lookup_order", "input": {"order_id": "X-9"}},
            ],
        )
    )
    provider = AnthropicProvider(client=client)
    response = await provider.complete(
        model="claude-opus-4-7",
        messages=[Message(role="user", content="find order X-9")],
        tools=[
            Tool(
                name="lookup_order",
                description="Look up an order by id",
                parameters={"type": "object", "properties": {"order_id": {"type": "string"}}},
            )
        ],
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [
        {
            "name": "lookup_order",
            "description": "Look up an order by id",
            "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
        }
    ]
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "lookup_order"
    assert response.tool_calls[0].arguments == {"order_id": "X-9"}


@pytest.mark.asyncio
async def test_temperature_and_max_tokens_forwarded() -> None:
    client = make_async_client()
    provider = AnthropicProvider(client=client)
    await provider.complete(
        model="claude-opus-4-7",
        messages=[Message(role="user", content="hi")],
        temperature=0.2,
        max_tokens=64,
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 64


@pytest.mark.asyncio
async def test_default_max_tokens_set_when_not_provided() -> None:
    client = make_async_client()
    provider = AnthropicProvider(client=client)
    await provider.complete(
        model="claude-opus-4-7",
        messages=[Message(role="user", content="hi")],
    )
    # Anthropic requires max_tokens; we always send a default.
    assert "max_tokens" in client.messages.create.call_args.kwargs


@pytest.mark.asyncio
async def test_cache_true_annotates_system_block_with_cache_control() -> None:
    client = make_async_client()
    provider = AnthropicProvider(client=client)
    await provider.complete(
        model="claude-opus-4-7",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
        cache=True,
    )
    system = client.messages.create.call_args.kwargs["system"]
    # When cache=True, system is forwarded as a block list (not a string)
    # carrying cache_control={"type":"ephemeral"} on each block.
    assert isinstance(system, list)
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_retriable_sdk_error_surfaces_as_anthropic_provider_error() -> None:
    # APIConnectionError requires a request= arg; build a stub request.
    request = httpx.Request("POST", "https://example.invalid")
    client = make_async_client(create_side_effect=anthropic.APIConnectionError(request=request))
    provider = AnthropicProvider(client=client)
    with pytest.raises(AnthropicProviderError, match="Anthropic SDK error"):
        await provider.complete(
            model="claude-opus-4-7",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.asyncio
async def test_tool_role_messages_become_tool_result_blocks() -> None:
    client = make_async_client()
    provider = AnthropicProvider(client=client)
    await provider.complete(
        model="claude-opus-4-7",
        messages=[
            Message(role="user", content="find order X-9"),
            Message(
                role="tool",
                content='{"status": "shipped"}',
                tool_call_id="tool_1",
            ),
        ],
    )
    chat_messages = client.messages.create.call_args.kwargs["messages"]
    tool_message = chat_messages[-1]
    assert tool_message["role"] == "user"
    block = tool_message["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tool_1"
    assert block["content"] == '{"status": "shipped"}'
