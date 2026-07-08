"""LLM usage analytics aggregated from llm_runs."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.api.deps import DbSession
from app.models import LLMRun, Project

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


class UsageBucket(BaseModel):
    key: str
    requests: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    avg_latency_ms: int
    success_rate: float


class UsageReport(BaseModel):
    total_requests: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    avg_latency_ms: int
    success_rate: float
    by_provider: list[UsageBucket]
    by_model: list[UsageBucket]
    by_project: list[UsageBucket]


_AGGS = (
    func.count(LLMRun.id),
    func.coalesce(func.sum(LLMRun.tokens_in), 0),
    func.coalesce(func.sum(LLMRun.tokens_out), 0),
    func.coalesce(func.sum(LLMRun.estimated_cost), 0.0),
    func.coalesce(func.avg(LLMRun.latency_ms), 0),
    func.coalesce(func.avg(case((LLMRun.success, 1.0), else_=0.0)), 0.0),
)


def _bucket(key: str, row) -> UsageBucket:
    return UsageBucket(
        key=key,
        requests=row[0],
        tokens_in=row[1],
        tokens_out=row[2],
        cost_usd=round(float(row[3]), 4),
        avg_latency_ms=int(row[4]),
        success_rate=round(float(row[5]), 3),
    )


@router.get("", response_model=UsageReport)
async def usage_report(session: DbSession) -> UsageReport:
    totals = (await session.execute(select(*_AGGS))).one()

    by_provider = [
        _bucket(row[6], row)
        for row in (
            await session.execute(
                select(*_AGGS, LLMRun.provider).group_by(LLMRun.provider)
            )
        ).all()
    ]
    by_model = [
        _bucket(f"{row[6]}/{row[7]}", row)
        for row in (
            await session.execute(
                select(*_AGGS, LLMRun.provider, LLMRun.model).group_by(
                    LLMRun.provider, LLMRun.model
                )
            )
        ).all()
    ]
    by_project = [
        _bucket(row[6] or "(no project)", row)
        for row in (
            await session.execute(
                select(*_AGGS, Project.name)
                .join(Project, Project.id == LLMRun.project_id, isouter=True)
                .group_by(Project.name)
            )
        ).all()
    ]
    return UsageReport(
        total_requests=totals[0],
        total_tokens_in=totals[1],
        total_tokens_out=totals[2],
        total_cost_usd=round(float(totals[3]), 4),
        avg_latency_ms=int(totals[4]),
        success_rate=round(float(totals[5]), 3),
        by_provider=by_provider,
        by_model=by_model,
        by_project=by_project,
    )
