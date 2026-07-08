import pytest

import app.llm.providers  # noqa: F401  (registers providers)
from app.llm.base import all_providers, get_provider_class
from app.llm.types import LLMProviderError
from tests.test_llm.fakes import FakeProvider, text_response


def test_registry_contains_all_five_providers():
    names = set(all_providers())
    assert {"anthropic", "google", "openai", "openrouter", "ollama"} <= names


def test_unknown_provider_raises_readable_error():
    with pytest.raises(LLMProviderError, match="Unknown LLM provider 'nope'"):
        get_provider_class("nope")


def test_new_provider_class_registers_itself():
    """Adding a provider requires exactly one class — registration is automatic."""

    class TotallyNewProvider(FakeProvider):
        name = "totally-new"
        label = "Totally New"

    assert get_provider_class("totally-new") is TotallyNewProvider
    # Cleanup so other tests see a pristine registry.
    from app.llm import base

    del base._REGISTRY["totally-new"]


def test_estimate_cost_longest_prefix_wins():
    cls = get_provider_class("anthropic")
    provider = object.__new__(cls)
    provider._api_key = ""
    # 1M in + 1M out on sonnet pricing (3, 15)
    assert cls.estimate_cost(provider, "claude-sonnet-5", 1_000_000, 1_000_000) == 18.0
    assert cls.estimate_cost(provider, "claude-opus-4-8", 1_000_000, 0) == 5.0
    assert cls.estimate_cost(provider, "unknown-model", 1000, 1000) is None


def test_stub_providers_fail_gracefully_not_crash():
    for name in ("openai", "openrouter", "ollama"):
        with pytest.raises(LLMProviderError, match="not implemented yet"):
            get_provider_class(name)()


async def test_plan_parses_numbered_lines():
    provider = FakeProvider([text_response("1. Read code\n2) Add function\n3 - Test\n")])
    steps, response = await provider.plan("fake-model", "T", "R", "ctx")
    assert steps == ["Read code", "Add function", "Test"]
    assert response.tokens_in == 100


async def test_plan_empty_raises():
    provider = FakeProvider([text_response("")])
    with pytest.raises(LLMProviderError, match="empty plan"):
        await provider.plan("fake-model", "T", "R", "ctx")


async def test_analyze_repository_parses_json_and_strips_fences():
    provider = FakeProvider([text_response('```json\n{"summary": "ok"}\n```')])
    data, _ = await provider.analyze_repository("fake-model", "prompt")
    assert data == {"summary": "ok"}


async def test_analyze_repository_bad_json_raises():
    provider = FakeProvider([text_response("not json at all")])
    with pytest.raises(LLMProviderError, match="unparseable"):
        await provider.analyze_repository("fake-model", "prompt")


def test_scrub_removes_api_key():
    provider = FakeProvider()
    provider._api_key = "sk-secret-123"
    assert "sk-secret-123" not in provider.scrub("error with sk-secret-123 inside")
