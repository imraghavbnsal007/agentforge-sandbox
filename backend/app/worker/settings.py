from arq.connections import RedisSettings

from app.core.config import settings
from app.db.session import async_session_factory
from app.services.analysis_service import AnalysisService
from app.services.publisher import PublishService
from app.services.run_service import RunService


async def run_agent(ctx: dict, task_id: int) -> None:
    async with async_session_factory() as session:
        await RunService(session).execute_agent_run(task_id)


async def publish_task(ctx: dict, task_id: int) -> None:
    async with async_session_factory() as session:
        await PublishService(session).publish_task(task_id)


async def analyze_project(ctx: dict, analysis_id: int) -> None:
    async with async_session_factory() as session:
        await AnalysisService(session).run_analysis(analysis_id)


class WorkerSettings:
    functions = [run_agent, publish_task, analyze_project]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
