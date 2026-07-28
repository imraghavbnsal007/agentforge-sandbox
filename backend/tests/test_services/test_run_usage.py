"""Normalised run-level usage.

The rule these exist to protect: **unknown cost is null, never zero.** A
missing price is not a free call.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, LLMRun, Task
from app.services.run_usage import refresh_run_counters, usage_for_run


@pytest.fixture
async def run(session: AsyncSession, task: Task) -> AgentRun:
    run = AgentRun(task_id=task.id, mode="llm", file_changes=[], test_results=[])
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def _call(
    session: AsyncSession,
    run: AgentRun,
    *,
    provider: str = "google",
    model: str = "gemini-3.1-flash-lite",
    tokens_in: int = 1000,
    tokens_out: int = 200,
    cost: float | None = 0.001,
    phase: str = "coding",
) -> None:
    session.add(
        LLMRun(
            agent_run_id=run.id,
            provider=provider,
            model=model,
            phase=phase,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost=cost,
            success=True,
        )
    )
    await session.commit()


# -- aggregation ------------------------------------------------------------


async def test_a_run_with_no_calls_reports_zero_tokens_and_no_cost(
    session: AsyncSession, run: AgentRun
):
    """A mock run genuinely made no calls — but cost is still null, because
    nothing priced it."""
    usage = await usage_for_run(session, run)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.model_calls == 0
    assert usage.estimated_cost is None


async def test_tokens_are_summed_across_calls(session: AsyncSession, run: AgentRun):
    await _call(session, run, tokens_in=1000, tokens_out=200)
    await _call(session, run, tokens_in=500, tokens_out=100)

    usage = await usage_for_run(session, run)
    assert usage.input_tokens == 1500
    assert usage.output_tokens == 300
    assert usage.total_tokens == 1800
    assert usage.model_calls == 2


async def test_costs_are_summed_when_every_call_is_priced(
    session: AsyncSession, run: AgentRun
):
    await _call(session, run, cost=0.001)
    await _call(session, run, cost=0.002)

    usage = await usage_for_run(session, run)
    assert usage.estimated_cost == pytest.approx(0.003)
    assert usage.cost_is_partial is False


# -- the null-not-zero rule -------------------------------------------------


async def test_an_unpriced_call_makes_the_whole_cost_unavailable(
    session: AsyncSession, run: AgentRun
):
    """Reporting 0.001 here would understate spend; null says 'unknown'."""
    await _call(session, run, cost=0.001)
    await _call(session, run, cost=None, model="unknown-model")

    usage = await usage_for_run(session, run)
    assert usage.estimated_cost is None
    assert usage.cost_is_partial is True


async def test_all_calls_unpriced_is_null_not_zero(
    session: AsyncSession, run: AgentRun
):
    await _call(session, run, cost=None)
    usage = await usage_for_run(session, run)
    assert usage.estimated_cost is None
    assert usage.estimated_cost != 0


async def test_a_genuinely_free_call_is_zero_not_null(
    session: AsyncSession, run: AgentRun
):
    """Zero must still be expressible — it means priced at nothing."""
    await _call(session, run, cost=0.0)
    usage = await usage_for_run(session, run)
    assert usage.estimated_cost == 0.0
    assert usage.cost_is_partial is False


# -- provider attribution ---------------------------------------------------


async def test_the_dominant_provider_and_model_are_reported(
    session: AsyncSession, run: AgentRun
):
    await _call(session, run, provider="google", model="gemini-3.1-flash-lite")
    await _call(session, run, provider="google", model="gemini-3.1-flash-lite")
    await _call(session, run, provider="anthropic", model="claude-sonnet-5")

    usage = await usage_for_run(session, run)
    assert usage.provider == "google"
    assert usage.model == "gemini-3.1-flash-lite"


async def test_a_mid_run_fallback_is_visible_in_the_breakdown(
    session: AsyncSession, run: AgentRun
):
    await _call(session, run, provider="google")
    await _call(session, run, provider="anthropic")

    usage = await usage_for_run(session, run)
    assert usage.by_provider == {"google": 1, "anthropic": 1}


async def test_usage_only_counts_its_own_run(
    session: AsyncSession, task: Task, run: AgentRun
):
    other = AgentRun(task_id=task.id, mode="llm", file_changes=[], test_results=[])
    session.add(other)
    await session.commit()
    await session.refresh(other)

    await _call(session, run, tokens_in=100)
    await _call(session, other, tokens_in=999)

    assert (await usage_for_run(session, run)).input_tokens == 100


# -- serialisation ----------------------------------------------------------


async def test_the_dict_shape_is_the_common_schema(
    session: AsyncSession, run: AgentRun
):
    await _call(session, run)
    payload = (await usage_for_run(session, run)).as_dict()

    for key in (
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "model_calls",
        "tool_calls",
        "estimated_cost",
        "provider",
        "model",
    ):
        assert key in payload, key


async def test_tool_calls_come_from_the_run_row(
    session: AsyncSession, run: AgentRun
):
    run.tool_calls = 7
    await session.commit()
    assert (await usage_for_run(session, run)).tool_calls == 7


# -- counters ---------------------------------------------------------------


async def test_refresh_counters_denormalises_the_model_call_count(
    session: AsyncSession, run: AgentRun
):
    await _call(session, run)
    await _call(session, run)

    await refresh_run_counters(session, run)
    assert run.model_calls == 2


async def test_existing_usage_records_are_untouched(
    session: AsyncSession, run: AgentRun
):
    """Normalisation is read-only over Phase 5 data."""
    from sqlalchemy import func, select

    await _call(session, run, cost=0.004)
    before = (
        await session.execute(select(func.count(LLMRun.id)))
    ).scalar_one()

    await usage_for_run(session, run)

    after = (await session.execute(select(func.count(LLMRun.id)))).scalar_one()
    assert after == before
