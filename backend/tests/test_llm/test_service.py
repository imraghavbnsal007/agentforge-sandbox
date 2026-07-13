import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import service as service_module
from app.llm.profiles import ModelSpec
from app.llm.service import LLMService
from app.llm.types import LLMProviderError
from app.models import LLMRun
from tests.test_llm.fakes import FakeProvider, text_response


@pytest.fixture
def seed_provider(monkeypatch: pytest.MonkeyPatch):
    def seed(provider: FakeProvider, name: str = "anthropic") -> FakeProvider:
        provider.name = name
        service_module._instances[name] = provider
        return provider

    return seed


async def test_successful_call_records_llm_run(
    session: AsyncSession, project, seed_provider
):
    provider = seed_provider(
        FakeProvider([text_response("1. step one", tokens_in=1000, tokens_out=200)])
    )
    service = LLMService(session, project_id=project.id)
    spec = ModelSpec("anthropic", "claude-sonnet-5")

    steps = await service.plan(spec, "T", "R", "ctx")
    assert steps == ["step one"]

    runs = (await session.execute(select(LLMRun))).scalars().all()
    assert len(runs) == 1
    run = runs[0]
    assert run.provider == "anthropic"
    assert run.model == "claude-sonnet-5"
    assert run.phase == "planning"
    assert run.tokens_in == 1000 and run.tokens_out == 200
    assert run.success is True
    assert run.error_message is None
    assert run.project_id == project.id
    # sonnet pricing (3, 15): 1000/1e6*3 + 200/1e6*15
    assert run.estimated_cost == pytest.approx(0.006)


async def test_failed_call_records_llm_run_and_raises(
    session: AsyncSession, project, seed_provider
):
    seed_provider(FakeProvider([LLMProviderError("provider exploded politely")]))
    service = LLMService(session, project_id=project.id)
    spec = ModelSpec("anthropic", "claude-sonnet-5")

    with pytest.raises(LLMProviderError, match="exploded politely"):
        await service.chat(spec, "coding", [{"role": "user", "content": [
            {"type": "text", "text": "x"}]}])

    runs = (await session.execute(select(LLMRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].success is False
    assert "exploded politely" in runs[0].error_message
    assert runs[0].tokens_in == 0


async def test_unknown_provider_recorded_and_readable(session: AsyncSession, project):
    service = LLMService(session, project_id=project.id)
    with pytest.raises(LLMProviderError, match="Unknown LLM provider"):
        await service.chat(
            ModelSpec("doesnotexist", "m"), "coding",
            [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
        )
    runs = (await session.execute(select(LLMRun))).scalars().all()
    assert len(runs) == 1 and runs[0].success is False


async def test_usage_endpoint_aggregates(client, session: AsyncSession, project, seed_provider):
    provider = seed_provider(
        FakeProvider(
            [
                text_response("a", tokens_in=100, tokens_out=10),
                text_response("b", tokens_in=200, tokens_out=20),
                LLMProviderError("nope"),
            ]
        )
    )
    service = LLMService(session, project_id=project.id)
    spec = ModelSpec("anthropic", "claude-sonnet-5")
    await service.summarize(spec, "t", "r", "d", "tests")
    await service.review(spec, "d", "c")
    with pytest.raises(LLMProviderError):
        await service.chat(spec, "coding", [{"role": "user", "content": [
            {"type": "text", "text": "x"}]}])

    report = (await client.get("/api/v1/usage")).json()
    assert report["total_requests"] == 3
    assert report["total_tokens_in"] == 300
    assert report["success_rate"] == pytest.approx(0.667, abs=0.001)
    provider_bucket = next(
        b for b in report["by_provider"] if b["key"] == "anthropic"
    )
    assert provider_bucket["requests"] == 3
    project_bucket = next(
        b for b in report["by_project"] if b["key"] == project.name
    )
    assert project_bucket["requests"] == 3


# -- Transient-unavailability fallback (Gemini 3.5 Flash -> 3.1 Flash Lite) --


async def test_unavailable_gemini_falls_back_to_flash_lite(
    session: AsyncSession, project, seed_provider
):
    from app.llm.types import LLMUnavailableError

    provider = seed_provider(
        FakeProvider(
            [
                LLMUnavailableError("Google Gemini unavailable (503)"),
                text_response("1. recovered step"),
            ]
        ),
        name="google",
    )
    service = LLMService(session, project_id=project.id)
    logs: list[str] = []
    service.log = logs.append
    spec = ModelSpec("google", "gemini-3.5-flash")

    steps = await service.plan(spec, "T", "R", "ctx")
    assert steps == ["recovered step"]

    # First call used Flash, the retry used Flash Lite.
    assert [c["model"] for c in provider.calls] == [
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    ]
    # The task log shows the exact fallback notice.
    assert logs == [
        "Gemini 3.5 Flash unavailable; continued with Gemini 3.1 Flash Lite."
    ]


async def test_fallback_records_actual_model_in_llm_runs(
    session: AsyncSession, project, seed_provider
):
    from app.llm.types import LLMUnavailableError

    seed_provider(
        FakeProvider(
            [
                LLMUnavailableError("Google Gemini unavailable (503)"),
                text_response("1. ok"),
            ]
        ),
        name="google",
    )
    service = LLMService(session, project_id=project.id)
    spec = ModelSpec("google", "gemini-3.5-flash")

    await service.plan(spec, "T", "R", "ctx")

    runs = (await session.execute(select(LLMRun).order_by(LLMRun.id))).scalars().all()
    assert [(r.model, r.success) for r in runs] == [
        ("gemini-3.5-flash", False),
        ("gemini-3.1-flash-lite", True),
    ]
    assert all(r.phase == "planning" for r in runs)


@pytest.mark.parametrize("message", [
    "Google Gemini auth/permission error (401)",
    "Google Gemini auth/permission error (403)",
    "Google Gemini API error (400): malformed request",
    "Response blocked by safety settings",
])
async def test_no_fallback_for_non_transient_errors(
    session: AsyncSession, project, seed_provider, message
):
    provider = seed_provider(
        FakeProvider([LLMProviderError(message)]), name="google"
    )
    service = LLMService(session, project_id=project.id)
    logs: list[str] = []
    service.log = logs.append
    spec = ModelSpec("google", "gemini-3.5-flash")

    with pytest.raises(LLMProviderError, match=message.split("(")[0].strip()[:20]):
        await service.plan(spec, "T", "R", "ctx")

    assert len(provider.calls) == 1  # no second attempt
    assert logs == []
    runs = (await session.execute(select(LLMRun))).scalars().all()
    assert len(runs) == 1 and runs[0].success is False


async def test_no_fallback_for_models_without_a_mapping(
    session: AsyncSession, project, seed_provider
):
    from app.llm.types import LLMUnavailableError

    provider = seed_provider(
        FakeProvider([LLMUnavailableError("unavailable (503)")]), name="google"
    )
    service = LLMService(session, project_id=project.id)
    spec = ModelSpec("google", "gemini-3.1-flash-lite")  # already the fallback

    with pytest.raises(LLMUnavailableError):
        await service.plan(spec, "T", "R", "ctx")
    assert len(provider.calls) == 1


async def test_fallback_applies_to_prefixed_model_ids(
    session: AsyncSession, project, seed_provider
):
    """'google/gemini-3.5-flash' (canonical form) is normalized before the
    fallback lookup."""
    from app.llm.types import LLMUnavailableError

    provider = seed_provider(
        FakeProvider(
            [LLMUnavailableError("unavailable (503)"), text_response("1. ok")]
        ),
        name="google",
    )
    service = LLMService(session, project_id=project.id)
    await service.plan(ModelSpec("google", "google/gemini-3.5-flash"), "T", "R", "c")
    assert provider.calls[1]["model"] == "gemini-3.1-flash-lite"
