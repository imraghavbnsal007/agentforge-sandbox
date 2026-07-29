"""Worker job and cron registration.

The reaper is only useful if it actually runs, and only safe if it never
touches a healthy long-running task.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RunStatus, TaskStatus
from app.models import AgentRun, Task
from app.services.execution_lock import (
    HEARTBEAT_SECONDS,
    STALE_AFTER_SECONDS,
)
from app.services.run_recovery import reap_stale_runs
from app.worker.settings import REAP_INTERVAL_MINUTES, WorkerSettings


# -- registration -----------------------------------------------------------


def test_every_job_is_registered():
    names = {f.__name__ for f in WorkerSettings.functions}
    assert names == {
        "run_agent",
        "publish_task",
        "analyze_project",
        "reap_abandoned_runs",
    }


def test_the_reaper_is_registered_as_a_cron_job():
    assert len(WorkerSettings.cron_jobs) == 1
    job = WorkerSettings.cron_jobs[0]
    assert job.coroutine.__name__ == "reap_abandoned_runs"


def test_the_reaper_runs_every_five_minutes():
    job = WorkerSettings.cron_jobs[0]
    assert REAP_INTERVAL_MINUTES == 5
    assert job.minute == set(range(0, 60, 5))
    assert job.second == {0} or job.second == 0


def test_a_missed_tick_does_not_pile_up():
    """The next sweep finds the same rows; retrying would be wasted work."""
    assert WorkerSettings.cron_jobs[0].max_tries == 1


def test_the_reaper_does_not_run_at_startup():
    """A worker restarting must not immediately reap runs that other, still
    healthy workers are holding."""
    assert WorkerSettings.cron_jobs[0].run_at_startup is False


# -- the interval is conservative relative to the staleness window ----------


def test_the_sweep_interval_is_shorter_than_the_staleness_window():
    """Otherwise a dead run could sit unnoticed for far longer than intended."""
    assert REAP_INTERVAL_MINUTES * 60 <= STALE_AFTER_SECONDS


def test_workers_heartbeat_far_more_often_than_the_staleness_window():
    """A healthy long-running task must never look abandoned."""
    assert HEARTBEAT_SECONDS * 4 <= STALE_AFTER_SECONDS


# -- the job timeout --------------------------------------------------------


def test_the_job_timeout_is_set_explicitly():
    """arq defaults to 300s. Inheriting that cancelled any agent run whose
    model took longer than five minutes, with a bare TimeoutError that said
    nothing about what the run was doing."""
    assert getattr(WorkerSettings, "job_timeout", None) is not None


def test_the_job_timeout_leaves_room_for_a_slow_model():
    """A cheap model doing one small edit per turn is slow, not broken."""
    assert WorkerSettings.job_timeout > 300
    # And long enough that the reaper, not the timeout, is what notices a
    # genuinely wedged run.
    assert WorkerSettings.job_timeout > STALE_AFTER_SECONDS


# -- only genuinely stale runs are touched ---------------------------------


async def _run(session: AsyncSession, task: Task, heartbeat_age: int) -> AgentRun:
    now = datetime.now(timezone.utc)
    run = AgentRun(
        task_id=task.id,
        mode="mock",
        status=RunStatus.running,
        started_at=now - timedelta(seconds=heartbeat_age),
        heartbeat_at=now - timedelta(seconds=heartbeat_age),
        file_changes=[],
        test_results=[],
    )
    session.add(run)
    task.status = TaskStatus.coding
    await session.commit()
    await session.refresh(run)
    return run


@pytest.mark.parametrize(
    "age",
    [0, HEARTBEAT_SECONDS, HEARTBEAT_SECONDS * 2, STALE_AFTER_SECONDS - 30],
    ids=["just-started", "one-beat", "two-beats", "just-inside-window"],
)
async def test_a_healthy_long_running_task_is_never_reaped(
    session: AsyncSession, task: Task, age: int
):
    """The failure mode that would matter most: killing live work."""
    run = await _run(session, task, age)

    assert await reap_stale_runs(session) == 0

    await session.refresh(run)
    assert run.status == RunStatus.running
    await session.refresh(task)
    assert task.status == TaskStatus.coding


async def test_a_run_just_past_the_window_is_reaped(
    session: AsyncSession, task: Task
):
    run = await _run(session, task, STALE_AFTER_SECONDS + 30)

    assert await reap_stale_runs(session) == 1

    await session.refresh(run)
    assert run.status == RunStatus.abandoned


async def test_repeated_sweeps_are_idempotent(session: AsyncSession, task: Task):
    """The cron fires every 5 minutes; a second pass must be a no-op."""
    await _run(session, task, STALE_AFTER_SECONDS + 30)
    assert await reap_stale_runs(session) == 1
    assert await reap_stale_runs(session) == 0
    assert await reap_stale_runs(session) == 0
