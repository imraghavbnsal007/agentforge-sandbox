from arq.connections import RedisSettings

from app.core.config import settings
from app.db.session import async_session_factory
from app.services.analysis_service import AnalysisService
from app.services.execution_lock import (
    PUBLISH_LOCK_PREFIX,
    CancellationSignal,
    ExecutionLock,
)
from app.services.kv_store import get_shared_kv
from app.services.publisher import PublishService
from app.services.run_service import RunService
from app.services.task_events import TaskEventService


async def run_agent(ctx: dict, task_id: int) -> None:
    """Execute one agent run, under a lease so two workers cannot overlap.

    The payload carries only the task id — everything else is re-read from the
    database, so a redelivered or duplicated job cannot smuggle in stale state.
    """
    kv = get_shared_kv()
    lock = ExecutionLock(kv)
    lease = await lock.acquire(task_id)
    if lease is None:
        # Another worker already holds it. Standing down is the correct
        # response to a duplicate delivery, not an error.
        return
    try:
        async with async_session_factory() as session:
            await RunService(
                session,
                events=TaskEventService(session, kv),
                cancellation=CancellationSignal(kv),
                lock=lock,
                lease=lease,
            ).execute_agent_run(task_id)
    finally:
        await lock.release(lease)


async def publish_task(ctx: dict, task_id: int) -> None:
    """Publish an approved run, under its own lease so a duplicate request
    cannot create two branches or two pull requests."""
    kv = get_shared_kv()
    lock = ExecutionLock(kv, prefix=PUBLISH_LOCK_PREFIX)
    lease = await lock.acquire(task_id)
    if lease is None:
        return
    try:
        async with async_session_factory() as session:
            await PublishService(session).publish_task(task_id)
    finally:
        await lock.release(lease)


async def analyze_project(ctx: dict, analysis_id: int) -> None:
    async with async_session_factory() as session:
        await AnalysisService(session).run_analysis(analysis_id)


async def reap_abandoned_runs(ctx: dict) -> int:
    """Mark runs whose worker died, so they stop looking active.

    A crashed worker used to leave a task in `coding` forever, with nothing
    distinguishing "still working" from "gone". A stale heartbeat is that
    distinction: the run becomes `abandoned` and retryable, with whatever it
    produced preserved.
    """
    from app.services.run_recovery import reap_stale_runs

    kv = get_shared_kv()
    async with async_session_factory() as session:
        return await reap_stale_runs(session, TaskEventService(session, kv))


async def _startup(ctx: dict) -> None:
    """Fail fast on a misconfigured worker, exactly as the API does."""
    from app.core.startup_checks import enforce_configuration

    enforce_configuration()


class WorkerSettings:
    functions = [run_agent, publish_task, analyze_project, reap_abandoned_runs]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = _startup
