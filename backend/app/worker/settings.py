from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging_config import configure_logging, log_context
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


async def run_agent(ctx: dict, task_id: int, request_id: str | None = None) -> None:
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
        with log_context(
            request_id=request_id, job_id=ctx.get("job_id"), task_id=task_id
        ):
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


async def publish_task(
    ctx: dict, task_id: int, request_id: str | None = None
) -> None:
    """Publish an approved run, under its own lease so a duplicate request
    cannot create two branches or two pull requests."""
    kv = get_shared_kv()
    lock = ExecutionLock(kv, prefix=PUBLISH_LOCK_PREFIX)
    lease = await lock.acquire(task_id)
    if lease is None:
        return
    try:
        with log_context(
            request_id=request_id, job_id=ctx.get("job_id"), task_id=task_id
        ):
            async with async_session_factory() as session:
                await PublishService(
                    session, events=TaskEventService(session, kv)
                ).publish_task(task_id)
    finally:
        await lock.release(lease)


async def analyze_project(
    ctx: dict, analysis_id: int, request_id: str | None = None
) -> None:
    with log_context(request_id=request_id, job_id=ctx.get("job_id")):
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

    configure_logging()
    enforce_configuration()


#: How often to look for runs whose worker died. Deliberately conservative:
#: a run is only considered abandoned after STALE_AFTER_SECONDS (5 minutes)
#: without a heartbeat, and the worker beats every 30s, so a healthy
#: long-running task is never at risk. Sweeping more often would add load
#: without shortening the detection window.
REAP_INTERVAL_MINUTES = 5


class WorkerSettings:
    functions = [run_agent, publish_task, analyze_project, reap_abandoned_runs]
    #: Set explicitly. arq defaults to 300 seconds, which cancels any agent
    #: run whose model takes longer than five minutes — the run then dies
    #: with a bare TimeoutError that says nothing about what it was doing.
    job_timeout = settings.worker_job_timeout_seconds
    cron_jobs = [
        cron(
            reap_abandoned_runs,
            # Every 5 minutes, on the minute.
            minute=set(range(0, 60, REAP_INTERVAL_MINUTES)),
            second=0,
            # A missed tick must not pile up: the next sweep finds the same
            # rows anyway, and the operation is idempotent.
            max_tries=1,
            run_at_startup=False,
        )
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = _startup
