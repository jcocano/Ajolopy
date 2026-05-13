"""Tests for UniversalOpenAIProvider.complete().

Covers the "complete()" acceptance group: prefix stripping on the SDK
call, system passthrough, tool conversion, parameter forwarding, the
``cache=True`` no-op invariant, and SDK-error wrapping.
"""

import json

import httpx
import openai
import pytest

from ajolopy.providers import Message, Tool
from ajolopy.providers.universal_openai import (
    UniversalOpenAIProvider,
    UniversalProviderError,
)

from .conftest import make_async_client, make_chat_completion


@pytest.mark.asyncio
async def test_prefix_is_stripped_before_calling_sdk() -> None:
    # The model arrives prefixed; the SDK call must receive the bare
    # model identifier so the upstream API recognises it.
    client = make_async_client(create_return=make_chat_completion(text="ok"))
    provider = UniversalOpenAIProvider(clients={"groq": client})
    response = await provider.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
    )
    assert response.text == "ok"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_system_role_forwarded_as_first_message_entry() -> None:
    client = make_async_client()
    provider = UniversalOpenAIProvider(clients={"groq": client})
    await provider.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[
            Message(role="system", content="You are concise."),
            Message(role="user", content="hi"),
        ],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    messages = kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "You are concise."}
    assert messages[1] == {"role": "user", "content": "hi"}
    # Like OpenAI, universal providers keep the system message inline —
    # no top-level "system" parameter (that's Anthropic's shape).
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
    provider = UniversalOpenAIProvider(clients={"together": client})
    response = await provider.complete(
        model="together:meta-llama/Llama-3.3-70B-Instruct-Turbo",
        messages=[Message(role="user", content="find order X-9")],
        tools=[
            Tool(
                name="lookup_order",
                description="Look up an order by id",
                parameters={
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                },
            )
        ],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    # The model arrives stripped of its 'together:' prefix; the tool
    # schema matches OpenAI's function-calling shape (reused helper).
    assert kwargs["model"] == "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["name"] == "lookup_order"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "lookup_order"
    assert response.tool_calls[0].arguments == {"order_id": "X-9"}


@pytest.mark.asyncio
async def test_temperature_and_max_tokens_forwarded_as_is() -> None:
    client = make_async_client()
    provider = UniversalOpenAIProvider(clients={"groq": client})
    await provider.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
        temperature=0.2,
        max_tokens=64,
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 64


@pytest.mark.asyncio
async def test_max_tokens_not_forwarded_when_unset() -> None:
    client = make_async_client()
    provider = UniversalOpenAIProvider(clients={"groq": client})
    await provider.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in kwargs


@pytest.mark.asyncio
async def test_cache_true_does_not_leak_any_extra_kwarg() -> None:
    # None of the universal providers expose an opt-in caching flag, so
    # the provider must NOT leak a cache-related kwarg into the SDK call.
    # The capability flag separately advertises this (returns False) so
    # higher-level layers don't even pass cache=True; the runtime check
    # still belt-and-braces.
    client_a = make_async_client()
    provider_a = UniversalOpenAIProvider(clients={"groq": client_a})
    await provider_a.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
        cache=False,
    )
    kwargs_a = dict(client_a.chat.completions.create.call_args.kwargs)

    client_b = make_async_client()
    provider_b = UniversalOpenAIProvider(clients={"groq": client_b})
    await provider_b.complete(
        model="groq:llama-3.3-70b-versatile",
        messages=[Message(role="user", content="hi")],
        cache=True,
    )
    kwargs_b = dict(client_b.chat.completions.create.call_args.kwargs)
    # Identical call shape regardless of cache flag.
    assert kwargs_a == kwargs_b
    assert "cache" not in kwargs_b
    assert "cache_control" not in kwargs_b


@pytest.mark.parametrize(
    "exception",
    [
        openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid")),
        openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid")),
    ],
)
@pytest.mark.asyncio
async def test_retriable_sdk_errors_surface_as_universal_provider_error(
    exception: BaseException,
) -> None:
    client = make_async_client(create_side_effect=exception)
    provider = UniversalOpenAIProvider(clients={"groq": client})
    with pytest.raises(UniversalProviderError, match="SDK error"):
        await provider.complete(
            model="groq:llama-3.3-70b-versatile",
            messages=[Message(role="user", content="hi")],
        )


@pytest.mark.parametrize(
    ("prefix", "model"),
    [
        ("ollama", "ollama:llama3"),
        ("groq", "groq:llama-3.3-70b-versatile"),
        ("together", "together:meta-llama/Llama-3.3-70B-Instruct-Turbo"),
        ("mistral", "mistral:mistral-large-latest"),
        ("deepseek", "deepseek:deepseek-chat"),
        ("openrouter", "openrouter:anthropic/claude-3.5-sonnet"),
    ],
)
@pytest.mark.asyncio
async def test_complete_routes_each_prefix_through_its_own_client(
    prefix: str,
    model: str,
) -> None:
    # Parametrised smoke test: every prefix in the v0.1 table proxies
    # through its own client and receives the bare model identifier.
    client = make_async_client()
    provider = UniversalOpenAIProvider(clients={prefix: client})
    await provider.complete(
        model=model,
        messages=[Message(role="user", content="hi")],
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    _, _, expected_model = model.partition(":")
    assert kwargs["model"] == expected_model
