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
    provider = FakeProvider(
        [text_response('```json\n{"summary": "ok", "suggestions": []}\n```')]
    )
    data, _ = await provider.analyze_repository("fake-model", "prompt")
    assert data["summary"] == "ok"
    assert data["suggestions"] == []
    # Optional fields come back with safe defaults.
    assert data["architecture_notes"] == ""
    assert data["risk_areas"] == [] and data["file_purposes"] == []


async def test_analyze_repository_requests_structured_output():
    from app.llm.analysis_schema import ENRICHMENT_JSON_SCHEMA

    provider = FakeProvider(
        [text_response('{"summary": "ok", "suggestions": []}')]
    )
    await provider.analyze_repository("fake-model", "prompt")
    assert provider.calls[0]["json_schema"] is ENRICHMENT_JSON_SCHEMA


async def test_analyze_repository_prefers_provider_parsed_object():
    response = text_response("garbage text the parser would choke on")
    response.parsed = {"summary": "from parsed", "suggestions": []}
    provider = FakeProvider([response])
    data, _ = await provider.analyze_repository("fake-model", "prompt")
    assert data["summary"] == "from parsed"


async def test_analyze_repository_bad_json_raises_with_diagnostics():
    from app.llm.types import AnalysisParseError

    provider = FakeProvider([text_response("not json at all")])
    with pytest.raises(AnalysisParseError, match="unparseable") as excinfo:
        await provider.analyze_repository("fake-model", "prompt")
    diagnostics = excinfo.value.diagnostics
    assert diagnostics is not None
    assert diagnostics.failed_stage == "truncation_repair"
    assert diagnostics.response_length == len("not json at all")
    assert "not json at all" in diagnostics.preview


async def test_analyze_repository_missing_required_field_names_it():
    from app.llm.types import AnalysisParseError

    provider = FakeProvider([text_response('{"summary": "ok"}')])
    with pytest.raises(AnalysisParseError, match="suggestions") as excinfo:
        await provider.analyze_repository("fake-model", "prompt")
    assert excinfo.value.diagnostics.failed_stage == "validation"


def test_default_normalize_model_id_strips_own_prefix():
    """Future providers get correct normalization for free unless they
    override it — the default strips '<name>/' using cls.name."""

    class SamplePlaceholderProvider(FakeProvider):
        name = "sampleprovider"
        label = "Sample Placeholder"

    assert (
        SamplePlaceholderProvider.normalize_model_id("sampleprovider/some-model")
        == "some-model"
    )
    assert SamplePlaceholderProvider.normalize_model_id("some-model") == "some-model"
    # A different provider's prefix is left alone.
    assert (
        SamplePlaceholderProvider.normalize_model_id("google/gemini-2.5-flash")
        == "google/gemini-2.5-flash"
    )

    from app.llm import base

    del base._REGISTRY["sampleprovider"]


def test_scrub_removes_api_key():
    provider = FakeProvider()
    provider._api_key = "sk-secret-123"
    assert "sk-secret-123" not in provider.scrub("error with sk-secret-123 inside")
