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
