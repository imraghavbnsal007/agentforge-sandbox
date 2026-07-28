"""Normalised, run-level usage derived from existing `llm_runs` rows.

No migration: every field here is aggregated on read from records Phase 5
already writes. Existing usage data is preserved untouched, and a provider
added later needs no schema change.

The rule that matters: **unknown cost is `None`, never `0`.** A missing price
is not a free call, and rendering it as zero would quietly understate spend.
`estimated_cost` is therefore null whenever *any* contributing call had no
price, and `cost_is_partial` says why.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, LLMRun


@dataclass
class RunUsage:
    """One run's usage, normalised across providers."""

    input_tokens: int = 0
    output_tokens: int = 0
    #: Providers that do not report cached tokens leave this at 0.
    cached_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    #: USD. None means "unavailable", never "free".
    estimated_cost: float | None = None
    #: True when some calls had no known price, so the figure is incomplete.
    cost_is_partial: bool = False
    #: Dominant provider/model for the run, by call count.
    provider: str | None = None
    model: str | None = None
    #: Per-provider breakdown for runs that fell back mid-flight.
    by_provider: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "estimated_cost": self.estimated_cost,
            "cost_is_partial": self.cost_is_partial,
            "provider": self.provider,
            "model": self.model,
        }


async def usage_for_run(session: AsyncSession, run: AgentRun) -> RunUsage:
    """Aggregate one run's LLM calls into the common schema."""
    rows = (
        await session.execute(
            select(
                LLMRun.provider,
                LLMRun.model,
                LLMRun.tokens_in,
                LLMRun.tokens_out,
                LLMRun.estimated_cost,
            ).where(LLMRun.agent_run_id == run.id)
        )
    ).all()

    usage = RunUsage(tool_calls=run.tool_calls or 0)
    if not rows:
        # A mock run makes no model calls; that is genuinely zero usage, but
        # cost stays None because nothing priced it.
        return usage

    counts: dict[tuple[str, str], int] = {}
    priced_total = 0.0
    any_unpriced = False

    for provider, model, tokens_in, tokens_out, cost in rows:
        usage.model_calls += 1
        usage.input_tokens += tokens_in or 0
        usage.output_tokens += tokens_out or 0
        key = (provider or "unknown", model or "unknown")
        counts[key] = counts.get(key, 0) + 1
        usage.by_provider[provider or "unknown"] = (
            usage.by_provider.get(provider or "unknown", 0) + 1
        )
        if cost is None:
            # An unknown price makes the whole figure unreliable.
            any_unpriced = True
        else:
            priced_total += float(cost)

    dominant = max(counts.items(), key=lambda item: item[1])[0]
    usage.provider, usage.model = dominant
    usage.cost_is_partial = any_unpriced
    # None, not 0.0, when anything was unpriced.
    usage.estimated_cost = None if any_unpriced else round(priced_total, 6)
    return usage


async def refresh_run_counters(session: AsyncSession, run: AgentRun) -> None:
    """Denormalise the model-call count onto the run.

    Cheap to keep current and saves the list view an aggregate per row.
    `tool_calls` is incremented by the runner as calls happen.
    """
    total = (
        await session.execute(
            select(func.count(LLMRun.id)).where(LLMRun.agent_run_id == run.id)
        )
    ).scalar_one()
    run.model_calls = int(total)
