from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

from app.llm.providers.anthropic_provider import (
    AnthropicProvider,
    _to_anthropic_messages,
)
from app.llm.types import LLMProviderError, text_message


def _fake_client(responses):
    return SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=responses))
    )


def _api_response(*blocks, stop_reason="end_turn", tokens=(10, 5)):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def test_neutral_message_translation():
    messages = [
        text_message("user", "hello"),
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "using tool"},
                {"type": "tool_call", "id": "t1", "name": "read_file",
                 "input": {"path": "a.py"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_call_id": "t1", "name": "read_file",
                 "content": "data", "is_error": False},
            ],
        },
    ]
    converted = _to_anthropic_messages(messages)
    assert converted[0] == {
        "role": "user", "content": [{"type": "text", "text": "hello"}]
    }
    assert converted[1]["content"][1] == {
        "type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}
    }
    assert converted[2]["content"][0]["tool_use_id"] == "t1"


async def test_chat_parses_text_and_tool_calls():
    client = _fake_client(
        [_api_response(
            _text_block("thinking..."),
            _tool_block("t9", "write_file", {"path": "x.py", "content": "1"}),
            stop_reason="tool_use",
            tokens=(120, 40),
        )]
    )
    provider = AnthropicProvider(client=client)
    response = await provider.chat("claude-sonnet-5", [text_message("user", "go")])

    assert response.text == "thinking..."
    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0].name == "write_file"
    assert response.tokens_in == 120 and response.tokens_out == 40
    assert response.provider == "anthropic"


async def test_auth_error_is_readable():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError(
        "bad key", response=httpx.Response(401, request=req), body=None
    )
    provider = AnthropicProvider(client=_fake_client([err]))
    with pytest.raises(LLMProviderError, match="authentication failed \\(401\\)"):
        await provider.chat("claude-sonnet-5", [text_message("user", "x")])


async def test_api_error_never_exposes_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-supersecret")
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError(
        "boom involving sk-ant-supersecret",
        response=httpx.Response(500, request=req),
        body=None,
    )
    provider = AnthropicProvider(client=_fake_client([err]))
    with pytest.raises(LLMProviderError) as excinfo:
        await provider.chat("claude-sonnet-5", [text_message("user", "x")])
    assert "sk-ant-supersecret" not in str(excinfo.value)


def test_normalize_strips_provider_prefix():
    assert (
        AnthropicProvider.normalize_model_id("anthropic/claude-sonnet-5")
        == "claude-sonnet-5"
    )


def test_normalize_bare_model_unchanged():
    """Anthropic model handling is unchanged: bare ids pass straight through."""
    assert AnthropicProvider.normalize_model_id("claude-sonnet-5") == "claude-sonnet-5"
    assert AnthropicProvider.normalize_model_id("claude-opus-4-8") == "claude-opus-4-8"


async def test_chat_sends_normalized_model_to_sdk():
    client = _fake_client([_api_response(_text_block("ok"), tokens=(10, 5))])
    provider = AnthropicProvider(client=client)
    response = await provider.chat(
        "anthropic/claude-sonnet-5", [text_message("user", "x")]
    )

    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert response.model == "claude-sonnet-5"


def test_requires_credentials(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(LLMProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()


async def test_json_schema_is_accepted_and_ignored():
    """Interface parity: json_schema must not change the Anthropic request."""
    client = _fake_client([_api_response(_text_block('{"summary": "s"}'))])
    provider = AnthropicProvider(client=client)
    response = await provider.chat(
        "claude-sonnet-5",
        [text_message("user", "analyze")],
        json_schema={"type": "object"},
    )
    kwargs = client.messages.create.await_args.kwargs
    assert "json_schema" not in kwargs
    assert "response_format" not in kwargs
    assert response.parsed is None
    assert response.text == '{"summary": "s"}'
