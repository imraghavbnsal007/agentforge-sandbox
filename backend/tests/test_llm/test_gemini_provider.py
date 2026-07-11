from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.types import LLMProviderError, text_message


def _fake_client(responses):
    return SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(side_effect=responses))
        )
    )


def _api_response(text="", function_calls=None, tokens=(10, 5)):
    return SimpleNamespace(
        text=text,
        function_calls=function_calls or [],
        usage_metadata=SimpleNamespace(
            prompt_token_count=tokens[0], candidates_token_count=tokens[1]
        ),
        candidates=[SimpleNamespace(content=None)],
    )


async def test_chat_text_response():
    client = _fake_client([_api_response(text="1. do things", tokens=(50, 20))])
    provider = GeminiProvider(client=client)
    response = await provider.chat("gemini-2.5-flash", [text_message("user", "plan")])

    assert response.text == "1. do things"
    assert response.stop_reason == "end"
    assert response.tokens_in == 50 and response.tokens_out == 20
    assert response.provider == "google"


async def test_chat_function_calls_become_tool_calls():
    fc = SimpleNamespace(id=None, name="write_file", args={"path": "x.py", "content": "1"})
    client = _fake_client([_api_response(text="", function_calls=[fc])])
    provider = GeminiProvider(client=client)
    response = await provider.chat(
        "gemini-2.5-flash",
        [text_message("user", "go")],
        tools=[{
            "name": "write_file", "description": "w",
            "input_schema": {"type": "object", "properties": {}},
        }],
    )
    assert response.stop_reason == "tool_use"
    call = response.tool_calls[0]
    assert call.name == "write_file"
    assert call.input == {"path": "x.py", "content": "1"}
    assert call.id  # synthesized when the API gives none

    # The request carried a FunctionDeclaration built from our neutral schema.
    kwargs = client.aio.models.generate_content.await_args.kwargs
    declaration = kwargs["config"].tools[0].function_declarations[0]
    assert declaration.name == "write_file"


async def test_tool_result_roundtrip_content_roles():
    client = _fake_client([_api_response(text="done")])
    provider = GeminiProvider(client=client)
    messages = [
        text_message("user", "go"),
        {
            "role": "assistant",
            "content": [
                {"type": "tool_call", "id": "t1", "name": "read_file",
                 "input": {"path": "a.py"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_call_id": "t1", "name": "read_file",
                 "content": "file body", "is_error": False},
            ],
        },
    ]
    await provider.chat("gemini-2.5-flash", messages)
    contents = client.aio.models.generate_content.await_args.kwargs["contents"]
    roles = [c.role for c in contents]
    assert roles == ["user", "model", "tool"]
    assert contents[1].parts[0].function_call.name == "read_file"
    assert contents[2].parts[0].function_response.name == "read_file"


def test_retry_delay_parsing():
    from app.llm.providers.gemini_provider import _retry_delay_seconds

    assert _retry_delay_seconds("... Please retry in 46.79s.") == pytest.approx(47.79)
    assert _retry_delay_seconds("'retryDelay': '46s'") == pytest.approx(47.0)
    assert _retry_delay_seconds("no hint here") == 30.0
    assert _retry_delay_seconds("Please retry in 500s") == 65.0  # capped


def _api_error_429():
    from google.genai import errors

    return errors.APIError(
        429,
        {"error": {"message": "quota exceeded. Please retry in 2.5s.",
                   "status": "RESOURCE_EXHAUSTED"}},
    )


async def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    import app.llm.providers.gemini_provider as gp

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
    client = _fake_client([_api_error_429(), _api_response(text="recovered")])
    provider = GeminiProvider(client=client)

    response = await provider.chat("gemini-3.5-flash", [text_message("user", "x")])
    assert response.text == "recovered"
    assert sleeps == [pytest.approx(3.5)]  # server-suggested 2.5s + 1s margin


async def test_rate_limit_retries_exhausted_is_readable(monkeypatch):
    import app.llm.providers.gemini_provider as gp

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
    client = _fake_client([_api_error_429(), _api_error_429(), _api_error_429()])
    provider = GeminiProvider(client=client)

    with pytest.raises(LLMProviderError, match="retries exhausted"):
        await provider.chat("gemini-3.5-flash", [text_message("user", "x")])
    assert len(sleeps) == 2  # MAX_RATE_LIMIT_RETRIES


async def test_transport_error_is_readable_and_scrubbed(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_api_key", "goog-secret-key")
    client = _fake_client([RuntimeError("socket to goog-secret-key broke")])
    provider = GeminiProvider(client=client)
    with pytest.raises(LLMProviderError) as excinfo:
        await provider.chat("gemini-2.5-flash", [text_message("user", "x")])
    message = str(excinfo.value)
    assert "goog-secret-key" not in message
    assert "Google Gemini" in message


def test_requires_api_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_api_key", "")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMProviderError, match="GOOGLE_API_KEY"):
        GeminiProvider()


def test_cost_estimation():
    provider = object.__new__(GeminiProvider)
    provider._api_key = ""
    cost = GeminiProvider.estimate_cost(provider, "gemini-3.5-flash", 1_000_000, 100_000)
    assert cost == round(1.50 + 0.90, 6)
    # Historical 2.5-flash runs keep their original pricing for display.
    cost = GeminiProvider.estimate_cost(provider, "gemini-2.5-flash", 1_000_000, 100_000)
    assert cost == round(0.30 + 0.25, 6)
    assert GeminiProvider.estimate_cost(provider, "gemini-9-unknown", 1000, 1000) is None


def test_dropdown_offers_35_flash_not_25_flash():
    assert "gemini-3.5-flash" in GeminiProvider.known_models
    assert "gemini-2.5-flash" not in GeminiProvider.known_models


# -- Model ID normalization (bug: "google/gemini-2.5-flash" reached the SDK
# unstripped and 404'd, even though the bare model is valid) ----------------

def test_normalize_strips_provider_prefix():
    assert GeminiProvider.normalize_model_id("google/gemini-2.5-flash") == "gemini-2.5-flash"
    assert GeminiProvider.normalize_model_id("google/gemini-3.5-flash") == "gemini-3.5-flash"
    assert GeminiProvider.normalize_model_id("gemini-3.5-flash") == "gemini-3.5-flash"


def test_normalize_bare_model_unchanged():
    assert GeminiProvider.normalize_model_id("gemini-2.5-flash") == "gemini-2.5-flash"


def test_normalize_strips_models_discovery_prefix():
    # google/ prefix stripped first, then models/ (order matters if both appear).
    assert GeminiProvider.normalize_model_id("models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert (
        GeminiProvider.normalize_model_id("google/models/gemini-2.5-flash")
        == "gemini-2.5-flash"
    )


async def test_chat_sends_normalized_model_to_sdk():
    client = _fake_client([_api_response(text="ok")])
    provider = GeminiProvider(client=client)
    response = await provider.chat("google/gemini-2.5-flash", [text_message("user", "x")])

    kwargs = client.aio.models.generate_content.await_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    # The recorded response also reflects what was actually invoked.
    assert response.model == "gemini-2.5-flash"


def _api_error_404(message: str):
    from google.genai import errors

    return errors.APIError(404, {"error": {"message": message, "status": "NOT_FOUND"}})


def _models_list_pager(names: list[str]):
    """An async-iterable standing in for AsyncPager[Model]."""

    class _Pager:
        def __aiter__(self):
            async def gen():
                for name in names:
                    yield SimpleNamespace(
                        name=f"models/{name}", supported_actions=["generateContent"]
                    )
            return gen()

    async def list_models(config=None):
        return _Pager()

    return list_models


async def test_invalid_model_produces_readable_error_with_available_models():
    client = _fake_client([_api_error_404("model not found")])
    client.aio.models.list = _models_list_pager(["gemini-2.5-flash", "gemini-2.5-pro"])
    provider = GeminiProvider(client=client)

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.chat("google/gemini-9-nonexistent", [text_message("user", "x")])

    message = str(excinfo.value)
    assert "gemini-9-nonexistent" in message
    assert "normalized to 'gemini-9-nonexistent'" in message
    assert "gemini-2.5-flash" in message
    assert "gemini-2.5-pro" in message


async def test_invalid_model_error_falls_back_to_known_models_if_list_fails():
    client = _fake_client([_api_error_404("model not found")])

    async def broken_list(config=None):
        raise RuntimeError("network down")

    client.aio.models.list = broken_list
    provider = GeminiProvider(client=client)

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.chat("bogus-model", [text_message("user", "x")])

    message = str(excinfo.value)
    # Falls back to the provider's own known_models list.
    assert "gemini-3.5-flash" in message


async def test_404_on_25_flash_includes_migration_hint():
    """Old configs pointing at 2.5-flash get told exactly what to do."""
    client = _fake_client([_api_error_404("no longer available to new users")])
    client.aio.models.list = _models_list_pager(["gemini-3.5-flash"])
    provider = GeminiProvider(client=client)

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.chat("google/gemini-2.5-flash", [text_message("user", "x")])

    message = str(excinfo.value)
    assert "Gemini 2.5 Flash is unavailable for new users. Use Gemini 3.5 Flash." in message


async def test_raw_model_turn_is_replayed_verbatim():
    """Gemini thinking models attach thought_signature to function-call parts;
    reconstructed parts without it are rejected (400). The provider must
    replay the raw Content object when the runner carries it."""
    from google.genai import types as genai_types

    raw_model_turn = genai_types.Content(
        role="model",
        parts=[
            genai_types.Part(
                function_call=genai_types.FunctionCall(
                    name="list_files", args={}
                ),
                thought_signature=b"opaque-signature",
            )
        ],
    )
    client = _fake_client([_api_response(text="done")])
    provider = GeminiProvider(client=client)
    messages = [
        text_message("user", "go"),
        {
            "role": "assistant",
            "content": [
                {"type": "tool_call", "id": "t1", "name": "list_files", "input": {}},
            ],
            "raw": raw_model_turn,
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_call_id": "t1", "name": "list_files",
                 "content": "a.py", "is_error": False},
            ],
        },
    ]
    await provider.chat("gemini-3.5-flash", messages)
    contents = client.aio.models.generate_content.await_args.kwargs["contents"]
    # The model turn is the exact object we were handed — signature intact.
    assert contents[1] is raw_model_turn
    assert contents[1].parts[0].thought_signature == b"opaque-signature"


async def test_chat_response_carries_raw_content():
    model_content = SimpleNamespace(role="model", parts=["sentinel"])
    api_response = _api_response(text="ok")
    api_response.candidates = [SimpleNamespace(content=model_content)]
    client = _fake_client([api_response])
    provider = GeminiProvider(client=client)
    response = await provider.chat("gemini-3.5-flash", [text_message("user", "x")])
    assert response.raw is model_content


async def test_404_on_other_models_has_no_migration_hint():
    client = _fake_client([_api_error_404("model not found")])
    client.aio.models.list = _models_list_pager(["gemini-3.5-flash"])
    provider = GeminiProvider(client=client)

    with pytest.raises(LLMProviderError) as excinfo:
        await provider.chat("gemini-9-bogus", [text_message("user", "x")])

    assert "unavailable for new users" not in str(excinfo.value)
