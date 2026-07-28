"""Recovering from a worker that died mid-run.

The guarantee under test: an interrupted run is marked clearly, its task
becomes actionable again, and **nothing it produced is discarded**.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ChangeType,
    ErrorCode,
    RunStage,
    RunStatus,
    TaskStatus,
)
from app.models import AgentRun, FileChange, Task
from app.services.execution_lock import STALE_AFTER_SECONDS
from app.services.kv_store import InMemoryKVStore
from app.services.run_recovery import (
    find_stale_runs,
    publish_needs_manual_check,
    reap_stale_runs,
)
from app.services.task_events import TaskEventService


def _ago(seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _run(
    session: AsyncSession,
    task: Task,
    *,
    heartbeat_age: int,
    stage: RunStage = RunStage.generating,
    with_changes: bool = True,
) -> AgentRun:
    run = AgentRun(
        task_id=task.id,
        mode="mock",
        status=RunStatus.running,
        stage=stage,
        started_at=_ago(heartbeat_age),
        heartbeat_at=_ago(heartbeat_age),
        file_changes=(
            [
                FileChange(
                    path="a.py", change_type=ChangeType.modify,
                    diff="--- a\n+++ b\n", is_binary=False,
                )
            ]
            if with_changes
            else []
        ),
        test_results=[],
    )
    session.add(run)
    task.status = TaskStatus.coding
    await session.commit()
    await session.refresh(run)
    return run


# -- detection --------------------------------------------------------------


async def test_a_live_run_is_not_reaped(session: AsyncSession, task: Task):
    await _run(session, task, heartbeat_age=5)
    assert await find_stale_runs(session) == []
    assert await reap_stale_runs(session) == 0


async def test_a_run_with_a_stale_heartbeat_is_found(
    session: AsyncSession, task: Task
):
    await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 60)
    stale = await find_stale_runs(session)
    assert len(stale) == 1


async def test_a_finished_run_is_never_reaped(session: AsyncSession, task: Task):
    run = await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 600)
    run.status = RunStatus.completed
    await session.commit()
    assert await find_stale_runs(session) == []


# -- reaping ----------------------------------------------------------------


async def test_reaping_marks_the_run_abandoned(session: AsyncSession, task: Task):
    run = await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 60)

    assert await reap_stale_runs(session) == 1

    await session.refresh(run)
    assert run.status == RunStatus.abandoned
    assert run.error_code == ErrorCode.worker_interrupted
    assert run.finished_at is not None


async def test_reaping_preserves_everything_the_run_produced(
    session: AsyncSession, task: Task
):
    """The whole point: an infrastructure failure must not lose work."""
    run = await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 60)
    await reap_stale_runs(session)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    reloaded = (
        await session.execute(
            select(AgentRun)
            .where(AgentRun.id == run.id)
            .options(selectinload(AgentRun.file_changes))
        )
    ).scalar_one()
    assert len(reloaded.file_changes) == 1
    assert reloaded.file_changes[0].diff


async def test_reaping_makes_the_task_actionable_again(
    session: AsyncSession, task: Task
):
    await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 60)
    await reap_stale_runs(session)

    await session.refresh(task)
    assert task.status == TaskStatus.failed

    from app.core.task_state import is_retryable

    assert is_retryable(task.status) is True


async def test_reaping_emits_an_explanatory_event(
    session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    run = await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 60)
    events = TaskEventService(session, kv)

    await reap_stale_runs(session, events)

    history = await events.history(task.id)
    assert history[-1].error_code == ErrorCode.worker_interrupted
    assert "worker stopped" in history[-1].message.lower()


async def test_reaping_is_idempotent(session: AsyncSession, task: Task):
    """A second reaper pass must not double-handle the same run."""
    await _run(session, task, heartbeat_age=STALE_AFTER_SECONDS + 60)
    assert await reap_stale_runs(session) == 1
    assert await reap_stale_runs(session) == 0


async def test_reaping_handles_several_runs(session: AsyncSession, project):
    tasks = []
    for i in range(3):
        t = Task(project_id=project.id, title=f"T{i}", request="r")
        session.add(t)
        await session.flush()
        tasks.append(t)
    await session.commit()
    for t in tasks:
        await _run(session, t, heartbeat_age=STALE_AFTER_SECONDS + 60)

    assert await reap_stale_runs(session) == 3


# -- crash during publishing ------------------------------------------------


@pytest.mark.parametrize("stage", [RunStage.pushing, RunStage.creating_pr])
async def test_a_crash_while_publishing_is_flagged_for_reconciliation(
    session: AsyncSession, task: Task, stage: RunStage
):
    """Push and PR creation are not idempotent — a crash there may or may not
    have changed the remote, so a retry must reconcile rather than assume."""
    run = await _run(session, task, heartbeat_age=10, stage=stage)
    assert await publish_needs_manual_check(run) is True


async def test_a_completed_publish_needs_no_reconciliation(
    session: AsyncSession, task: Task
):
    run = await _run(session, task, heartbeat_age=10, stage=RunStage.creating_pr)
    run.pr_url = "https://github.com/o/r/pull/1"
    await session.commit()
    assert await publish_needs_manual_check(run) is False


async def test_a_crash_before_publishing_needs_no_reconciliation(
    session: AsyncSession, task: Task
):
    run = await _run(session, task, heartbeat_age=10, stage=RunStage.generating)
    assert await publish_needs_manual_check(run) is False
